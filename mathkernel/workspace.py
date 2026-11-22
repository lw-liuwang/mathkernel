"""Task inputs, review records, revisions, and iteration budgets."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from .inputs import Hardware, InputError, read_json
from .protocol import METRICS, lean_value
from .verification import ROOT, source_digest


RESOURCE_KEYS = ("flops", "hbm_bytes", "peak_fast_memory_bytes")


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def local_file(root, name):
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise InputError("Expected a nonempty relative file path")
    root = Path(root).resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise InputError(f"Required file must exist inside the task directory: {name}")
    return path


def validate_task(task):
    """Return actionable omissions without treating a partial task as executable."""
    issues = []

    def require(obj, key, predicate, guidance, prefix=""):
        path = f"{prefix}.{key}" if prefix else key
        if not isinstance(obj, dict) or key not in obj or not predicate(obj[key]):
            issues.append({"field": path, "message": guidance})
            return None
        return obj[key]

    text = lambda value: isinstance(value, str) and bool(value.strip())
    nonempty_list = lambda value: isinstance(value, list) and bool(value)
    require(task, "schema_version", lambda x: type(x) is int and x == 1, "Use task schema_version 1")
    require(task, "name", text, "Ask the user for a task name")
    spec = require(task, "specification", lambda x: isinstance(x, dict), "Describe the requested calculation")
    for key, pred, guidance in (
        ("description", text, "Describe the calculation to preserve"),
        ("inputs", nonempty_list, "List inputs with shapes and value domains"),
        ("outputs", nonempty_list, "List required outputs and their shapes"),
        ("semantics", text, "Confirm exact-real or other numerical semantics"),
        ("conditions", lambda x: isinstance(x, list) and all(text(item) for item in x), "List input conditions; use [] if none"),
    ):
        require(spec, key, pred, guidance, "specification")
    for key in ("inputs", "outputs"):
        entries = (spec or {}).get(key, [])
        if isinstance(entries, list):
            for index, entry in enumerate(entries):
                for field in ("name", "shape", "domain"):
                    require(entry, field, text, f"Describe {field} for this {key[:-1]}", f"specification.{key}[{index}]")
    require(task, "baseline", lambda x: isinstance(x, dict) and bool(x), "Describe the baseline execution plan")
    for key in ("hardware", "model", "objective", "constraints", "budget"):
        require(task, key, lambda x: isinstance(x, dict), f"Supply {key}")
    hardware = task.get("hardware", {}) if isinstance(task, dict) else {}
    if isinstance(hardware, dict):
        for key in ("name", "peak_flops_per_second", "hbm_bytes_per_second", "fast_memory_bytes", "element_bytes"):
            require(hardware, key, text if key == "name" else lambda x: type(x) is int and x > 0,
                    "Supply the hardware value and its basis; do not guess it without authorization", "hardware")
    model = task.get("model", {}) if isinstance(task, dict) else {}
    if isinstance(model, dict) and set(model) - {"definition"}:
        issues.append({"field": "model", "message": "Supply only a task-local Lean definition path"})
    require(model, "definition", text, "Provide the model definition file", "model")
    objective = task.get("objective", {}) if isinstance(task, dict) else {}
    require(objective, "metric", lambda x: isinstance(x, str) and x in METRICS, "Confirm the resource metric to minimize", "objective")
    fraction = require(objective, "minimum_reduction", lambda x: isinstance(x, dict), "Confirm minimum relative reduction as numerator/denominator (0/1 means strictly better)", "objective")
    if fraction is not None:
        n, d = fraction.get("numerator"), fraction.get("denominator")
        if type(n) is not int or type(d) is not int or not 0 <= n < d:
            issues.append({"field": "objective.minimum_reduction", "message": "Require integers with 0 <= numerator < denominator"})
    constraints = task.get("constraints") if isinstance(task, dict) else None
    if isinstance(constraints, dict):
        for key, value in constraints.items():
            if key not in RESOURCE_KEYS or type(value) is not int or value <= 0:
                issues.append({"field": f"constraints.{key}", "message": "Use a positive integer resource limit (flops, hbm_bytes, peak_fast_memory_bytes)"})
    budget = task.get("budget") if isinstance(task, dict) else None
    if isinstance(budget, dict):
        if not budget or any(key not in ("max_iterations", "max_seconds") or type(value) is not int or value <= 0 for key, value in budget.items()):
            issues.append({"field": "budget", "message": "Confirm positive max_iterations, max_seconds, or both"})
    supplements = require(task, "supplements", lambda x: isinstance(x, list), "Record supplements and their user authorization; use [] if none")
    if supplements is not None:
        for index, item in enumerate(supplements):
            for key in ("scope", "content", "basis", "authorized_by", "authorization"):
                require(item, key, text, "Record the supplement, basis, and explicit user authorization", f"supplements[{index}]")
    return issues


def load_task(root):
    root = Path(root).resolve()
    task = read_json(root / "task.json")
    issues = validate_task(task)
    if issues:
        raise InputError("Task is incomplete; run task check: " + "; ".join(item["field"] for item in issues))
    lean_value(task)
    definition_path = local_file(root, task["model"]["definition"])
    definition = definition_path.read_text()
    Hardware.parse(task["hardware"])
    revision = digest({"task": task, "model_definition": definition, "trusted_sources": source_digest()})
    return task, definition, revision


def check_task(root):
    root = Path(root).resolve()
    try:
        task = read_json(root / "task.json")
        issues = validate_task(task)
        if issues:
            return {"status": "needs_information", "issues": issues, "ready": False,
                    "next_action": "Ask the user to supply the missing information or authorize specific supplements"}
        task, definition, revision = load_task(root)
        review_path = root / "review.json"
        review = read_json(review_path) if review_path.is_file() else {}
        confirmed = (isinstance(review, dict) and review.get("revision") == revision and
                     all(isinstance(review.get(key), str) and review[key].strip()
                         for key in ("confirmed_by", "confirmation", "confirmed_at")))
        return {"status": "ready" if confirmed else "needs_confirmation", "ready": confirmed,
                "revision": revision, "information_complete": True, "model_definition_present": True,
                "model_proof_status": "not_checked", "issues": [],
                "next_action": "Evaluate a candidate" if confirmed else "Present the specification, model assumptions, supplements, goal and budget to the user, then record their confirmation"}
    except (InputError, OSError) as error:
        return {"status": "invalid_task", "ready": False, "issues": [{"field": "task", "message": str(error)}]}


def confirm_task(root, confirmed_by, note):
    if not confirmed_by.strip() or not note.strip():
        raise InputError("Record who confirmed the task and the actual confirmation message")
    task, definition, revision = load_task(root)
    review = {"revision": revision, "confirmed_by": confirmed_by, "confirmation": note, "confirmed_at": now()}
    write_json(Path(root) / "review.json", review)
    return check_task(root)


def require_ready(root):
    result = check_task(root)
    if not result["ready"]:
        raise InputError(f"Task is not ready: {result}")
    return load_task(root)


def initialize(root):
    root = Path(root).resolve()
    if root.exists() and any(root.iterdir()):
        raise InputError("Initialize an empty directory; existing task files will not be overwritten")
    root.mkdir(parents=True, exist_ok=True)
    write_json(root / "task.json", {"schema_version": 1, "name": "", "specification": {},
               "hardware": {}, "model": {}, "baseline": {}, "objective": {},
               "constraints": {}, "budget": {}, "supplements": []})
    return check_task(root)


def session_status(root, revision, budget):
    root = Path(root)
    path = root / "session.json"
    state = read_json(path) if path.is_file() else {"revision": revision, "started_at": None}
    if state["revision"] != revision:
        state = {"revision": revision, "started_at": None}
    iterations = []
    for result in sorted((root / "iterations").glob("*/iteration.json")):
        record = read_json(result)
        if record["revision"] == revision:
            iterations.append(record)
    elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(state["started_at"])).total_seconds() if state["started_at"] else 0
    exhausted = (("max_iterations" in budget and len(iterations) >= budget["max_iterations"]) or
                 ("max_seconds" in budget and elapsed >= budget["max_seconds"]))
    verified = [item for item in iterations if item.get("verified_check")]
    best = min(verified, key=lambda item: item["objective_value"]) if verified else None
    return {"revision": revision, "started_at": state["started_at"], "iterations": len(iterations),
            "elapsed_seconds": elapsed, "budget_exhausted": exhausted, "best_verified_iteration": best["id"] if best else None,
            "best_verified_check": best["verified_check"] if best else None}
