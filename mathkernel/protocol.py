"""Bind task snapshots to the shared Lean proof obligations."""

import json
import os
from pathlib import Path
import subprocess
import time

from .model import InputError, Task
from .verification import ROOT, checked_axioms, lake_environment


MARKER = "MATHKERNEL_EVALUATION:"
METRICS = {"estimated_seconds": "time", "flops": "flops", "hbm_bytes": "bytes", "peak_fast_memory_bytes": "storage"}


def lean_value(value):
    if value is None:
        return ".null"
    if type(value) is bool:
        return f"(.bool {str(value).lower()})"
    if type(value) is int:
        return f"(.int ({value}))"
    if isinstance(value, str):
        return f"(.str {json.dumps(value, ensure_ascii=False)})"
    if isinstance(value, list):
        return "(.array [" + ", ".join(lean_value(item) for item in value) + "])"
    if isinstance(value, dict):
        return "(.object [" + ", ".join(f"({json.dumps(key, ensure_ascii=False)}, {lean_value(item)})" for key, item in sorted(value.items())) + "])"
    raise InputError("Task and plan numbers must be integers; express fractions as numerator/denominator objects")


def instance_source(task, candidate, definition):
    hardware = task["hardware"]
    h = "⟨" + ", ".join(str(hardware[key]) for key in ("peak_flops_per_second", "hbm_bytes_per_second", "fast_memory_bytes", "element_bytes")) + "⟩"
    objective = task["objective"]
    reduction = objective["minimum_reduction"]
    limits = task["constraints"]
    limit_terms = [f"(some {limits[key]})" if key in limits else "none" for key in ("flops", "hbm_bytes", "peak_fast_memory_bytes")]
    goal = f"⟨.{METRICS[objective['metric']]}, {reduction['numerator']}, {reduction['denominator']}, {', '.join(limit_terms)}⟩"
    if task["model"]["kind"] == "matmul-chain":
        parsed = Task.parse(definition)
        dims = ", ".join(map(str, parsed.dimensions))
        model = f"MathKernel.MatrixChainWorkflow.model ⟨{dims}, {h}⟩"
        imported = "MathKernel.MatrixChainWorkflow"
    else:
        model = "MathKernel.TaskModel.model task"
        imported = "Model"
    return f"""import {imported}

namespace MathKernel.TaskInstance
open Workflow

def task : Value := {lean_value(task)}
def baseline : Value := {lean_value(task['baseline'])}
def candidate : Value := {lean_value(candidate)}
def hardware : Hardware := {h}
def goal : Goal := {goal}
def model : Model := {model}

end MathKernel.TaskInstance
"""


def certificate_source(comparison):
    def report(name):
        return "[" + ", ".join(f"⟨{op['flops']}, {op['hbm_bytes']}, {op['peak_fast_memory_bytes']}⟩" for op in comparison[name]["operations"]) + "]"
    return f"""import Proof

set_option maxRecDepth 8192
set_option maxHeartbeats 2000000

namespace MathKernel.Instance
open Workflow TaskInstance

theorem verified : Workflow.Verified model baseline candidate hardware goal
    {report('baseline')} {report('candidate')} := by
  exact ⟨TaskProof.baselineCorrect, TaskProof.candidateCorrect,
    by decide, by decide, by decide, by decide, by decide⟩

#print axioms verified
end MathKernel.Instance
"""


def builtin_proof():
    return """import TaskInstance
namespace MathKernel.TaskProof
open TaskInstance

theorem baselineCorrect : ∀ x, model.execute baseline x = model.specification x :=
  MatrixChainWorkflow.correct _ _
theorem candidateCorrect : ∀ x, model.execute candidate x = model.specification x :=
  MatrixChainWorkflow.correct _ _
end MathKernel.TaskProof
"""


def run_lean(directory, task, candidate, definition, timeout, proof=None, comparison=None, total_timeout=None):
    """Evaluate a model, or check fixed certificate obligations with submitted proofs."""
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "TaskInstance.lean").write_text(instance_source(task, candidate, definition))
    commands = [("--no-cache", "build", "MathKernel")]
    if task["model"]["kind"] == "lean":
        (directory / "Model.lean").write_text(definition)
        commands.append(("env", "lean", "-o", str(directory / "Model.olean"), str(directory / "Model.lean")))
    commands.append(("env", "lean", "-o", str(directory / "TaskInstance.olean"), str(directory / "TaskInstance.lean")))
    if comparison is None:
        (directory / "Evaluate.lean").write_text(
            'import TaskInstance\nopen MathKernel.Workflow MathKernel.TaskInstance\n'
            f'#eval IO.println ("{MARKER}" ++ (Lean.Json.mkObj '
            '[("baseline", evaluationJson model baseline), ("candidate", evaluationJson model candidate)]).compress)\n'
        )
        commands.append(("env", "lean", str(directory / "Evaluate.lean")))
    else:
        (directory / "Proof.lean").write_text(proof)
        (directory / "Certificate.lean").write_text(certificate_source(comparison))
        commands.extend([
            ("env", "lean", "-o", str(directory / "Proof.olean"), str(directory / "Proof.lean")),
            ("env", "lean", str(directory / "Certificate.lean")),
        ])
    log = []
    deadline = time.monotonic() + total_timeout if total_timeout is not None else None
    try:
        lake, environment = lake_environment()
        environment["LEAN_PATH"] = str(directory) + os.pathsep + environment.get("LEAN_PATH", "")
        for arguments in commands:
            if arguments[:2] == ("env", "lean"):
                arguments = (*arguments[:2], f"--root={directory}", *arguments[2:])
            remaining = min(timeout, deadline - time.monotonic()) if deadline is not None else timeout
            if remaining <= 0:
                raise subprocess.TimeoutExpired("task exploration budget", timeout)
            completed = subprocess.run([lake, *arguments], cwd=ROOT / "lean", env=environment,
                                       capture_output=True, text=True, timeout=remaining)
            output = completed.stdout + completed.stderr
            log.append(f"$ lake {' '.join(arguments)}\n{output}")
            if completed.returncode:
                return {"verification_status": "proof_failed", "diagnostic": output}
        if comparison is not None:
            return {"verification_status": "verified", "axioms": checked_axioms(output)}
        lines = [line[len(MARKER):] for line in output.splitlines() if line.startswith(MARKER)]
        if len(lines) != 1:
            raise ValueError("Expected exactly one model evaluation record")
        return {"verification_status": "not_run", "evaluation": json.loads(lines[0])}
    except subprocess.TimeoutExpired as error:
        partial = error.stdout or b""
        log.append(partial.decode(errors="replace") if isinstance(partial, bytes) else partial)
        return {"verification_status": "timeout", "diagnostic": f"Lean command exceeded its timeout or the remaining task budget ({timeout}-second command limit)"}
    except OSError as error:
        return {"verification_status": "unavailable", "diagnostic": str(error)}
    except (ValueError, TypeError) as error:
        return {"verification_status": "untrusted_proof", "diagnostic": str(error)}
    finally:
        (directory / "lean.log").write_text("\n".join(log))
