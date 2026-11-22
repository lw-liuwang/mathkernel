"""The matrix-chain input boundary and the two-level cost model."""

from dataclasses import asdict, dataclass
from fractions import Fraction
import json
from pathlib import Path


MODEL = "two-level-output-stationary-v1"


class InputError(ValueError):
    pass


def fields(value, required, optional=(), context="input"):
    if not isinstance(value, dict):
        raise InputError(f"{context} must be an object")
    missing = set(required) - value.keys()
    unknown = value.keys() - set(required) - set(optional)
    if missing or unknown:
        raise InputError(f"{context}: missing={sorted(missing)}, unknown={sorted(unknown)}")
    return value


def positive(value, context):
    if type(value) is not int or value <= 0:
        raise InputError(f"{context} must be a positive integer")
    return value


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as error:
        raise InputError(f"Cannot read {path}: {error}") from error


@dataclass(frozen=True)
class Tile:
    m: int
    n: int
    k: int

    @classmethod
    def parse(cls, value):
        fields(value, ("m", "n", "k"), context="tile")
        return cls(*(positive(value[key], f"tile.{key}") for key in ("m", "n", "k")))


@dataclass(frozen=True)
class Plan:
    order: str
    tile: Tile

    @classmethod
    def parse(cls, value):
        fields(value, ("order", "tile"), context="plan")
        if value["order"] not in ("left", "right"):
            raise InputError("plan.order must be 'left' or 'right'")
        return cls(value["order"], Tile.parse(value["tile"]))


@dataclass(frozen=True)
class Hardware:
    name: str
    peak_flops_per_second: int
    hbm_bytes_per_second: int
    fast_memory_bytes: int
    element_bytes: int

    @classmethod
    def parse(cls, value):
        keys = ("peak_flops_per_second", "hbm_bytes_per_second", "fast_memory_bytes", "element_bytes")
        fields(value, ("name", *keys), context="hardware")
        if not isinstance(value["name"], str) or not value["name"]:
            raise InputError("hardware.name must be a nonempty string")
        return cls(value["name"], *(positive(value[key], f"hardware.{key}") for key in keys))


@dataclass(frozen=True)
class Task:
    name: str
    dimensions: tuple[int, int, int, int]
    hardware: Hardware
    baseline: Plan

    @classmethod
    def parse(cls, value):
        fields(value, ("name", "model", "matrices", "hardware", "baseline"), ("description",), "task")
        if not isinstance(value["name"], str) or not value["name"]:
            raise InputError("task.name must be a nonempty string")
        if value["model"] != MODEL:
            raise InputError(f"Only model '{MODEL}' is supported")
        matrices = value["matrices"]
        if not isinstance(matrices, list) or len(matrices) != 3:
            raise InputError("matrices must contain exactly A, B, C")
        shapes = []
        for matrix, name in zip(matrices, ("A", "B", "C")):
            fields(matrix, ("name", "rows", "cols"), context=f"matrix {name}")
            if matrix["name"] != name:
                raise InputError("matrices must be named A, B, C in that order")
            shapes.append((positive(matrix["rows"], f"{name}.rows"), positive(matrix["cols"], f"{name}.cols")))
        if shapes[0][1] != shapes[1][0] or shapes[1][1] != shapes[2][0]:
            raise InputError("Matrix dimensions do not form a compatible chain")
        dimensions = (shapes[0][0], shapes[0][1], shapes[1][1], shapes[2][1])
        return cls(value["name"], dimensions, Hardware.parse(value["hardware"]), Plan.parse(value["baseline"]))

    def to_json(self):
        m, k, n, p = self.dimensions
        return {
            "name": self.name, "model": MODEL,
            "matrices": [{"name": name, "rows": rows, "cols": cols}
                         for name, rows, cols in (("A", m, k), ("B", k, n), ("C", n, p))],
            "hardware": asdict(self.hardware), "baseline": asdict(self.baseline),
        }


def seconds_json(seconds):
    return {"numerator": seconds.numerator, "denominator": seconds.denominator, "approximate": float(seconds)}


def evaluate(task, plan):
    """Count the same blocked schedule interpreted by Lean's Schedule.cost."""
    m, k, n, p = task.dimensions
    gemms = [(m, k, n), (m, n, p)] if plan.order == "left" else [(k, n, p), (m, k, p)]
    tile, hardware = plan.tile, task.hardware
    peak_bytes = hardware.element_bytes * (tile.m * tile.k + tile.k * tile.n + tile.m * tile.n)
    violations = []
    if peak_bytes > hardware.fast_memory_bytes:
        violations.append(f"Working set {peak_bytes} exceeds fast-memory capacity {hardware.fast_memory_bytes}")
    operations = []
    ticks = 0
    for index, (rows, reduction, cols) in enumerate(gemms):
        if rows % tile.m or cols % tile.n or reduction % tile.k:
            violations.append(f"GEMM {index}: dimensions {(rows, reduction, cols)} must be divisible by tile {(tile.m, tile.k, tile.n)}")
            continue
        output_tiles = (rows // tile.m) * (cols // tile.n)
        steps = output_tiles * (reduction // tile.k)
        flops = steps * (2 * tile.m * tile.n * tile.k)
        reads = steps * (tile.m * tile.k + tile.k * tile.n)
        writes = output_tiles * tile.m * tile.n
        hbm_bytes = hardware.element_bytes * (reads + writes)
        compute_ticks = flops * hardware.hbm_bytes_per_second
        memory_ticks = hbm_bytes * hardware.peak_flops_per_second
        operation_ticks = max(compute_ticks, memory_ticks)
        ticks += operation_ticks
        operations.append({
            "shape_mkn": [rows, reduction, cols], "flops": flops,
            "hbm_read_elements": reads, "hbm_write_elements": writes, "hbm_bytes": hbm_bytes,
            "time_ticks": operation_ticks,
            "bottleneck": "compute" if compute_ticks > memory_ticks else "memory" if memory_ticks > compute_ticks else "balanced",
        })
    complete = len(operations) == 2
    seconds = Fraction(ticks, hardware.peak_flops_per_second * hardware.hbm_bytes_per_second) if complete else None
    return {
        "feasible": not violations, "violations": violations, "operations": operations,
        "flops": sum(op["flops"] for op in operations) if complete else None,
        "hbm_bytes": sum(op["hbm_bytes"] for op in operations) if complete else None,
        "peak_fast_memory_bytes": peak_bytes,
        "time_ticks": ticks if complete else None,
        "estimated_seconds": seconds_json(seconds) if seconds is not None else None,
        "communication_bytes": 0,
    }


def compare(task, candidate):
    baseline = evaluate(task, task.baseline)
    proposed = evaluate(task, candidate)
    improves = (baseline["feasible"] and proposed["feasible"] and proposed["time_ticks"] < baseline["time_ticks"])
    return {
        "model": MODEL, "task": task.name, "baseline": baseline, "candidate": proposed,
        "dimensions": list(task.dimensions), "hardware": asdict(task.hardware),
        "baseline_plan": asdict(task.baseline), "candidate_plan": asdict(candidate),
        "model_improvement": improves, "verification_status": "not_run",
        "model_speedup": float(Fraction(baseline["time_ticks"], proposed["time_ticks"])) if baseline["feasible"] and proposed["feasible"] else None,
    }
