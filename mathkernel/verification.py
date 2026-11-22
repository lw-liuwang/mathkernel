"""Generate task-bound Lean certificates and preserve verification artifacts."""

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid

from .model import compare
from .paths import ROOT, scratch_directory


TRUSTED_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}


def lake_environment():
    local = ROOT / "lean" / ".toolchain" / "bin" / "lake"
    configured = os.environ.get("MATHKERNEL_LAKE")
    executable = configured or (str(local) if local.is_file() else shutil.which("lake"))
    if not executable:
        raise FileNotFoundError("Lean is not installed; see README.md setup instructions")
    environment = os.environ.copy()
    environment["PATH"] = str(Path(executable).resolve().parent) + os.pathsep + environment.get("PATH", "")
    environment["TMPDIR"] = str(scratch_directory())
    return executable, environment


def lean_plan(name, plan):
    b = plan.tile
    return f"def {name} : Plan := ⟨.{plan.order}, ⟨{b.m}, {b.n}, {b.k}⟩⟩"


def certificate_source(task, candidate, comparison):
    m, k, n, p = task.dimensions
    h = task.hardware
    reports = []
    for name in ("baseline", "candidate"):
        report = comparison[name]
        if report["time_ticks"] is not None:
            reports.append(f"ReportMatches task {name} {report['flops']} {report['hbm_bytes']} {report['peak_fast_memory_bytes']} {report['time_ticks']}")
    report_type = " ∧ ".join(reports)
    report_proof = "\n  · refine ⟨?_, ?_⟩ <;> constructor <;> decide" if len(reports) == 2 else "\n  · constructor <;> decide" if reports else ""
    extra_type = f" ∧ ({report_type})" if reports else ""
    opening = "\n  constructor\n  · " if reports else "\n  "
    indent = "    " if reports else "  "
    return f"""import MathKernel.Verification

set_option maxRecDepth 8192
set_option maxHeartbeats 2000000

namespace MathKernel.Instance

def task : Task := ⟨{m}, {k}, {n}, {p},
  ⟨{h.peak_flops_per_second}, {h.hbm_bytes_per_second}, {h.fast_memory_bytes}, {h.element_bytes}⟩⟩
{lean_plan('baseline', task.baseline)}
{lean_plan('candidate', candidate)}

theorem verified : Verified task baseline candidate{extra_type} := by{opening}refine ⟨plans_equivalent task baseline candidate, ?_, ?_, ?_⟩
{indent}· decide
{indent}· decide
{indent}· exact lower_time_of_ticks task baseline candidate (by decide) (by decide){report_proof}

#print axioms verified

end MathKernel.Instance
"""


def source_digest():
    paths = [ROOT / "lean" / "lean-toolchain", ROOT / "lean" / "lakefile.toml", ROOT / "lean" / "MathKernel.lean"]
    manifest = ROOT / "lean" / "lake-manifest.json"
    if manifest.is_file():
        paths.append(manifest)
    paths.extend(sorted((ROOT / "lean" / "MathKernel").rglob("*.lean")))
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def checked_axioms(output):
    declaration = "MathKernel.Instance.verified"
    pattern = rf"'{re.escape(declaration)}' depends on axioms:\s*\[([^\]]*)\]"
    reports = re.findall(pattern, output)
    no_axioms = output.count(f"'{declaration}' does not depend on any axioms")
    if len(reports) + no_axioms != 1:
        raise ValueError("Lean must report exactly one axiom record for the expected certificate")
    if reports:
        axioms = {item.strip() for item in reports[0].split(",") if item.strip()}
        if axioms <= TRUSTED_AXIOMS:
            return sorted(axioms)
        raise ValueError(f"Unexpected proof axioms: {sorted(axioms - TRUSTED_AXIOMS)}")
    return []


def verify(task, candidate, timeout=120):
    evaluation = compare(task, candidate)
    run_name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    directory = ROOT / "runs" / run_name
    directory.mkdir(parents=True)
    source = certificate_source(task, candidate, evaluation)
    (directory / "Instance.lean").write_text(source)
    (directory / "task.json").write_text(json.dumps(task.to_json(), indent=2) + "\n")
    (directory / "candidate.json").write_text(json.dumps(asdict(candidate), indent=2) + "\n")
    result = {**evaluation, "run_directory": str(directory), "source_digest": source_digest(), "axioms": None}
    log = []
    try:
        lake, environment = lake_environment()
        for arguments in (("--no-cache", "build", "MathKernel"), ("env", "lean", str(directory / "Instance.lean"))):
            completed = subprocess.run(
                [lake, *arguments], cwd=ROOT / "lean", env=environment,
                capture_output=True, text=True, timeout=timeout,
            )
            output = completed.stdout + completed.stderr
            log.append(f"$ lake {' '.join(arguments)}\n{output}")
            if completed.returncode:
                result["verification_status"] = "proof_failed"
                result["diagnostic"] = output
                break
        else:
            result["axioms"] = checked_axioms(output)
            result["verification_status"] = "verified"
    except subprocess.TimeoutExpired as error:
        result["verification_status"] = "timeout"
        result["diagnostic"] = f"Lean command exceeded the {timeout}-second timeout"
        partial = error.stdout or b""
        log.append(partial.decode(errors="replace") if isinstance(partial, bytes) else partial)
    except (OSError, ValueError) as error:
        result["verification_status"] = "unavailable" if isinstance(error, OSError) else "untrusted_proof"
        result["diagnostic"] = str(error)
    (directory / "lean.log").write_text("\n".join(log))
    (directory / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def render_report(result):
    baseline, candidate = result["baseline"], result["candidate"]
    expressions = {"left": "(AB)C", "right": "A(BC)"}
    initial, selected = result["baseline_plan"], result["candidate_plan"]
    tile = selected["tile"]
    rows = [
        "# 数学计算方案验证报告", "", f"任务：{result['task']}",
        "", f"硬件模型：{result['hardware']['name']}", "",
        f"方案：{expressions[initial['order']]} → {expressions[selected['order']]}；"
        f"分块 tm={tile['m']}、tn={tile['n']}、tk={tile['k']}。", "",
        f"验证状态：{result['verification_status']}", "",
        "| 指标 | 基线 | 候选 |", "| --- | ---: | ---: |",
    ]
    for label, key in (("计算量（FLOP）", "flops"), ("显存搬运（字节）", "hbm_bytes"), ("快速存储峰值（字节）", "peak_fast_memory_bytes")):
        rows.append(f"| {label} | {baseline[key]} | {candidate[key]} |")
    def time_text(value):
        return f"{value['approximate'] * 1e6:.6f} µs" if value else "不可计算"
    rows.append(f"| 模型耗时 | {time_text(baseline['estimated_seconds'])} | {time_text(candidate['estimated_seconds'])} |")
    rows.extend(["", "模型：实数矩阵链；单设备两级存储；顺序 GEMM；峰值 Roofline。"])
    if result["verification_status"] == "verified":
        rows.extend(["", "Lean 已检查数学等价、基线与候选可行，以及候选估计耗时严格降低。"])
    if "diagnostic" in result:
        rows.extend(["", "```text", result["diagnostic"].rstrip(), "```"])
    return "\n".join(rows) + "\n"
