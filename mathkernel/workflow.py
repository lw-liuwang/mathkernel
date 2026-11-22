"""Evaluate iterations, recheck proofs, and export portable task deliverables."""

from fractions import Fraction
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import uuid

from .model import InputError, Plan, read_json, seconds_json
from .paths import scratch_directory
from .protocol import builtin_proof, run_lean
from .workspace import (RESOURCE_KEYS, digest, local_file, load_task, now, require_ready,
                        session_status, write_json)


def summarize(raw, task):
    if not isinstance(raw, dict) or type(raw.get("feasible")) is not bool:
        raise InputError("Model evaluation must return a feasible boolean")
    operations = raw.get("operations")
    if not isinstance(operations, list) or not operations:
        raise InputError("Model must return at least one resource-counted operation")
    hardware = task["hardware"]
    ticks = 0
    for op in operations:
        if not isinstance(op, dict) or set(op) != set(RESOURCE_KEYS) or any(type(v) is not int or v < 0 for v in op.values()):
            raise InputError("Each model operation must provide nonnegative integer FLOP, byte and peak-storage counts")
        ticks += max(op["flops"] * hardware["hbm_bytes_per_second"], op["hbm_bytes"] * hardware["peak_flops_per_second"])
    counts = {"flops": sum(op["flops"] for op in operations), "hbm_bytes": sum(op["hbm_bytes"] for op in operations),
              "peak_fast_memory_bytes": max(op["peak_fast_memory_bytes"] for op in operations)}
    violations = [] if raw["feasible"] else ["Task model reports an infeasible plan"]
    limits = {**task["constraints"], "peak_fast_memory_bytes": min(hardware["fast_memory_bytes"], task["constraints"].get("peak_fast_memory_bytes", hardware["fast_memory_bytes"]))}
    for key, limit in limits.items():
        if counts[key] > limit:
            violations.append(f"{key}={counts[key]} exceeds {limit}")
    for key in ("formula", "pseudocode"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise InputError(f"Model must render a nonempty {key} for the plan")
    return {**counts, "operations": operations, "time_ticks": ticks,
            "estimated_seconds": seconds_json(Fraction(ticks, hardware["peak_flops_per_second"] * hardware["hbm_bytes_per_second"])),
            "feasible": not violations, "violations": violations, "formula": raw["formula"], "pseudocode": raw["pseudocode"]}


def compare_evaluation(raw, task, plan):
    baseline, candidate = (summarize(raw[name], task) for name in ("baseline", "candidate"))
    key = "time_ticks" if task["objective"]["metric"] == "estimated_seconds" else task["objective"]["metric"]
    before, after = baseline[key], candidate[key]
    reduction = task["objective"]["minimum_reduction"]
    improves = (baseline["feasible"] and candidate["feasible"] and after < before and
                after * reduction["denominator"] <= before * (reduction["denominator"] - reduction["numerator"]))
    return {"model": task["model"]["kind"], "task": task["name"], "hardware": task["hardware"],
            "baseline_plan": task["baseline"], "candidate_plan": plan,
            "baseline": baseline, "candidate": candidate, "objective": task["objective"],
            "objective_value": after, "model_improvement": improves,
            "model_speedup": float(Fraction(baseline["time_ticks"], candidate["time_ticks"])) if candidate["time_ticks"] else None,
            "verification_status": "not_run"}


def snapshot_task(root, destination, task):
    destination.mkdir(parents=True)
    shutil.copy2(root / "task.json", destination / "task.json")
    shutil.copy2(root / "review.json", destination / "review.json")
    name = task["model"]["definition"]
    target = destination / name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(local_file(root, name), target)


def evaluate_iteration(root, candidate_path, timeout=120):
    root = Path(root).resolve()
    task, definition, revision = require_ready(root)
    candidate_path = Path(candidate_path).resolve()
    candidate = read_json(candidate_path)
    if not isinstance(candidate, dict) or not isinstance(candidate.get("plan"), dict) or not candidate["plan"]:
        raise InputError("A candidate must contain a nonempty plan object, with optional proof file")
    if set(candidate) - {"plan", "proof"}:
        raise InputError("Candidate fields are plan and optional proof")
    if task["model"]["kind"] == "matmul-chain":
        Plan.parse(candidate["plan"])
    proof = local_file(candidate_path.parent, candidate["proof"]).read_text() if candidate.get("proof") else None
    state = session_status(root, revision, task["budget"])
    if state["budget_exhausted"]:
        return {"status": "budget_exhausted", **state, "next_action": "Accept an existing verified candidate or report unfinished work; request user approval before changing the budget"}
    if state["started_at"] is None:
        write_json(root / "session.json", {"revision": revision, "started_at": now()})
    identifier = uuid.uuid4().hex[:12]
    directory = root / "iterations" / identifier
    directory.mkdir(parents=True)
    snapshot_task(root, directory / "input", task)
    write_json(directory / "plan.json", candidate["plan"])
    if proof is not None:
        (directory / "proof.lean").write_text(proof)
    record = {"id": identifier, "revision": revision, "plan_digest": digest(candidate["plan"]),
              "created_at": now(), "verification_status": "not_run"}
    # Reserve the attempt before calling Lean, including failed or interrupted evaluations.
    write_json(directory / "iteration.json", record)
    remaining = task["budget"]["max_seconds"] - state["elapsed_seconds"] if "max_seconds" in task["budget"] else None
    evaluation = run_lean(directory / "evaluation", task, candidate["plan"], definition, timeout, total_timeout=remaining)
    if "evaluation" in evaluation:
        comparison = compare_evaluation(evaluation["evaluation"], task, candidate["plan"])
        write_json(directory / "comparison.json", comparison)
        record.update(objective_value=comparison["objective_value"], model_improvement=comparison["model_improvement"])
    else:
        record.update(evaluation)
        comparison = evaluation
    write_json(directory / "iteration.json", record)
    return {**comparison, "iteration": identifier, "iteration_directory": str(directory),
            "next_action": ("Verify this iteration if it meets the goal; otherwise propose another candidate"
                            if "evaluation" in evaluation else "Resolve the evaluation diagnostic before proposing another candidate")}


def load_iteration(root, identifier):
    root = Path(root).resolve()
    if not isinstance(identifier, str) or not identifier or not identifier.isalnum():
        raise InputError("Use the iteration ID returned by task evaluate")
    task, definition, revision = require_ready(root)
    directory = root / "iterations" / identifier
    record = read_json(directory / "iteration.json")
    plan = read_json(directory / "plan.json")
    if record["revision"] != revision or record["plan_digest"] != digest(plan):
        raise InputError("Task, model or candidate changed; evaluate a new iteration under the confirmed task")
    if load_task(directory / "input")[2] != revision:
        raise InputError("Iteration task snapshot does not match the confirmed task")
    return directory, task, definition, plan, record


def verify_iteration(root, identifier, timeout=120, proof_path=None, fresh=False, update_record=True):
    directory, task, definition, plan, record = load_iteration(root, identifier)
    if proof_path:
        (directory / "proof.lean").write_text(Path(proof_path).read_text())
    if task["model"]["kind"] == "lean" and not (directory / "proof.lean").is_file():
        raise InputError("Supply baselineCorrect and candidateCorrect with task verify --proof FILE")
    proof = builtin_proof() if task["model"]["kind"] == "matmul-chain" else local_file(directory, "proof.lean").read_text()
    run = directory / "checks" / uuid.uuid4().hex[:12]
    if fresh:
        evaluation = run_lean(run / "evaluation", task, plan, definition, timeout)
        if "evaluation" not in evaluation:
            return {**evaluation, "iteration": identifier, "run_directory": str(run)}
        comparison = compare_evaluation(evaluation["evaluation"], task, plan)
        if comparison != read_json(directory / "comparison.json"):
            return {"verification_status": "stale_evaluation", "diagnostic": "Saved costs or rendered plan do not match the current model", "iteration": identifier}
    else:
        comparison = read_json(directory / "comparison.json")
    remaining = None
    if not fresh and "max_seconds" in task["budget"]:
        state = session_status(root, record["revision"], task["budget"])
        remaining = max(0, task["budget"]["max_seconds"] - state["elapsed_seconds"])
    result = run_lean(run / "proof", task, plan, definition, timeout, proof=proof, comparison=comparison, total_timeout=remaining)
    result.update(iteration=identifier, revision=record["revision"], plan_digest=digest(plan),
                  proof_digest=digest(proof), run_directory=str(run), checked_at=now())
    write_json(run / "result.json", result)
    record.update(verification_status=result["verification_status"], last_check=str(run.relative_to(directory)),
                  objective_value=comparison["objective_value"])
    if result["verification_status"] == "verified":
        record["verified_check"] = record["last_check"]
    if update_record:
        write_json(directory / "iteration.json", record)
    return result


def roofline_points(comparison):
    hardware = comparison["hardware"]
    denominator = hardware["peak_flops_per_second"] * hardware["hbm_bytes_per_second"]
    points = []
    for name in ("baseline", "candidate"):
        report = comparison[name]
        for index, op in enumerate([*report["operations"], report]):
            ticks = max(op["flops"] * hardware["hbm_bytes_per_second"], op["hbm_bytes"] * hardware["peak_flops_per_second"]) if index < len(report["operations"]) else report["time_ticks"]
            seconds = Fraction(ticks, denominator)
            points.append({"plan": name, "kind": "total" if op is report else "operation", "label": f"{name} " + ("total" if op is report else f"operation {index + 1}"),
                           "flops": op["flops"], "hbm_bytes": op["hbm_bytes"],
                           "intensity_flops_per_byte": float(Fraction(op["flops"], op["hbm_bytes"])) if op["hbm_bytes"] and op["flops"] else None,
                           "performance_tflops": float(Fraction(op["flops"], 10**12) / seconds) if seconds else 0,
                           "estimated_microseconds": float(seconds * 10**6)})
    return {"model": comparison["model"], "task": comparison["task"], "hardware": hardware,
            "ridge_intensity_flops_per_byte": hardware["peak_flops_per_second"] / hardware["hbm_bytes_per_second"],
            "model_speedup": comparison["model_speedup"], "points": points}


def report_text(task, comparison, record):
    rows = ["# 优化计算方案", "", task["specification"]["description"], "", "## 数学变换", "",
            comparison["baseline"]["formula"], "", "→", "", comparison["candidate"]["formula"], "",
            "## 执行伪代码", "", "```text", comparison["candidate"]["pseudocode"].rstrip(), "```", "",
            "## 成本对比", "", "| 指标 | 基线 | 候选 |", "| --- | ---: | ---: |"]
    for label, key in (("计算量（FLOP）", "flops"), ("搬运量（字节）", "hbm_bytes"), ("快速存储峰值（字节）", "peak_fast_memory_bytes")):
        rows.append(f"| {label} | {comparison['baseline'][key]} | {comparison['candidate'][key]} |")
    times = [comparison[name]["estimated_seconds"]["approximate"] * 1e6 for name in ("baseline", "candidate")]
    rows.extend([f"| 模型耗时（µs） | {times[0]:.6f} | {times[1]:.6f} |", "",
                 f"目标：{json.dumps(task['objective'], ensure_ascii=False)}", "",
                 "Lean 已检查数学规格、基线与候选可行性、成本计数和目标改进。", "",
                 "Roofline 展示确认模型下的预测；执行伪代码用于指导后续实现。", "",
                 "## 适用条件", "", task["specification"]["semantics"], "",
                 *[f"- {item}" for item in task["specification"]["conditions"]], "",
                 "## 探索范围", "", f"尝试次数：{record['iterations']}；停止原因：{record['stop_reason']}。", "",
                 "未声明搜索空间内最优性。", ""])
    return "\n".join(rows)


def artifact_contents(task, comparison, plan, exploration):
    return {"scheme.json": {"baseline": task["baseline"], "candidate": plan,
                            "baseline_formula": comparison["baseline"]["formula"],
                            "candidate_formula": comparison["candidate"]["formula"],
                            "pseudocode": comparison["candidate"]["pseudocode"]},
            "costs.json": comparison, "roofline.json": roofline_points(comparison),
            "exploration.json": exploration}


def check_manifest(root):
    manifest = read_json(root / "bundle.json")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1 or not isinstance(manifest.get("files"), dict) or not manifest["files"]:
        raise InputError("Invalid bundle manifest")
    for name, expected in manifest["files"].items():
        actual = hashlib.sha256(local_file(root, name).read_bytes()).hexdigest()
        if actual != expected:
            raise InputError(f"Bundle file changed: {name}")
    return manifest


def _accept_iteration(root, identifier, timeout, stop_reason):
    root = Path(root).resolve()
    bundle = check_manifest(root) if (root / "bundle.json").is_file() else None
    if bundle:
        if identifier is not None and identifier != bundle["iteration"]:
            raise InputError("Bundle acceptance must use its selected iteration")
        identifier = bundle["iteration"]
    if identifier is None:
        raise InputError("Select an iteration for acceptance")
    if stop_reason not in ("target_met", "budget_exhausted", "user_stopped"):
        raise InputError("Stop reason must be target_met, budget_exhausted, or user_stopped")
    result = verify_iteration(root, identifier, timeout, fresh=True, update_record=bundle is None)
    if result["verification_status"] != "verified":
        result = {**result, "acceptance_status": "rejected"}
        return result
    directory, task, definition, plan, record = load_iteration(root, identifier)
    comparison = read_json(directory / "comparison.json")
    if bundle and bundle.get("revision") != record["revision"]:
        raise InputError("Bundle revision does not match the proven task")
    if not comparison["model_improvement"]:
        return {**result, "acceptance_status": "rejected", "diagnostic": "Goal is not met"}
    artifacts = root / "artifacts" / identifier
    if bundle:
        exploration = read_json(artifacts / "exploration.json")
    else:
        state = session_status(root, record["revision"], task["budget"])
        exploration = {**state, "stop_reason": stop_reason}
    contents = artifact_contents(task, comparison, plan, exploration)
    if bundle:
        for name, expected in contents.items():
            if read_json(artifacts / name) != expected:
                raise InputError(f"Bundle artifact does not match the proven scheme: {name}")
        if (artifacts / "report.md").read_text() != report_text(task, comparison, exploration):
            raise InputError("Bundle report does not match the proven scheme")
        if not (artifacts / "roofline.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
            raise InputError("Roofline artifact is not a PNG")
        # Regeneration checks plotting availability without rewriting the exported evidence.
        with tempfile.TemporaryDirectory(dir=scratch_directory()) as scratch:
            from .roofline import plot_roofline_data
            plot_roofline_data(contents["roofline.json"], Path(scratch) / "roofline")
            if (Path(scratch) / "roofline.png").read_bytes() != (artifacts / "roofline.png").read_bytes():
                raise InputError("Roofline PNG does not match regenerated model data")
    else:
        artifacts.mkdir(parents=True, exist_ok=True)
        for name, value in contents.items():
            write_json(artifacts / name, value)
        (artifacts / "report.md").write_text(report_text(task, comparison, exploration))
        from .roofline import plot_roofline_data
        plot_roofline_data(contents["roofline.json"], artifacts / "roofline")
    result.update(acceptance_status="accepted", artifact_directory=str(artifacts))
    return result


def accept_iteration(root, identifier=None, timeout=120, stop_reason="target_met"):
    root = Path(root).resolve()
    try:
        result = _accept_iteration(root, identifier, timeout, stop_reason)
    except (InputError, OSError) as error:
        # A failed recheck must not leave an earlier accepted status as the latest result.
        if root.is_dir():
            write_json(root / "acceptance.json", {"acceptance_status": "rejected", "diagnostic": str(error), "checked_at": now()})
        raise
    write_json(root / "acceptance.json", result)
    return result


def export_iteration(root, identifier, output, timeout=120, stop_reason="target_met"):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists() or output.is_relative_to(root) or root.is_relative_to(output):
        raise InputError("Export to a new directory outside the task workspace")
    result = accept_iteration(root, identifier, timeout, stop_reason)
    if result["acceptance_status"] != "accepted":
        return result
    directory, task, definition, plan, record = load_iteration(root, identifier)
    snapshot_task(root, output, task)
    selected = output / "iterations" / identifier
    selected.mkdir(parents=True)
    snapshot_task(root, selected / "input", task)
    for name in ("iteration.json", "plan.json", "comparison.json", "proof.lean"):
        if (directory / name).is_file():
            shutil.copy2(directory / name, selected / name)
    # Keep only sources, diagnostics and results; compiled caches are reconstructed.
    shutil.copytree(directory / "checks" / Path(record["last_check"]).name,
                    selected / "evidence", ignore=shutil.ignore_patterns("*.olean", "*.ilean"))
    shutil.copytree(Path(result["artifact_directory"]), output / "artifacts" / identifier)
    (output / "README.md").write_text(
        "# MathKernel deliverable\n\nUse the same MathKernel revision and pinned Lean/Mathlib environment.\n\n"
        "```bash\npython3 /path/to/mathkernel/tools/mathkernel.py task accept /path/to/this/bundle\n```\n\n"
        "See artifacts/ for the scheme, pseudocode, modeled Roofline and cost comparison.\n"
        "User confirmations record decisions; they are not an identity authentication mechanism.\n")
    files = {str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(output.rglob("*")) if path.is_file()}
    write_json(output / "bundle.json", {"schema_version": 1, "iteration": identifier, "revision": record["revision"], "files": files})
    exported = accept_iteration(output, timeout=timeout)
    return {**exported, "bundle_directory": str(output)}
