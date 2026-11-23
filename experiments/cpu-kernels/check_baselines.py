"""Check the C baselines against exact expressions and accurate dot products."""

import argparse
from array import array
import ctypes
from fractions import Fraction
import json
import math
from pathlib import Path
import random
import subprocess

from calibrate import FLAGS


def buffer(values):
    return (ctypes.c_double * len(values)).from_buffer(values)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", required=True, type=Path)
    args = parser.parse_args()
    build = args.build_dir.resolve()
    build.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).with_name("baselines.c")
    library_path = build / "baselines.so"
    command = ["cc", *FLAGS, "-shared", "-fPIC", str(source), "-o", str(library_path)]
    subprocess.run(command, check=True)
    library = ctypes.CDLL(str(library_path))
    pointer = ctypes.POINTER(ctypes.c_double)
    library.fusion_baseline.argtypes = [ctypes.c_size_t, *([pointer] * 7)]
    library.fusion_baseline.restype = None
    library.matmul_baseline.argtypes = [ctypes.c_size_t, pointer, pointer, pointer]
    library.matmul_baseline.restype = None
    rng = random.Random(20261123)
    checks = []

    for n in (0, 1, 17, 1025):
        for case in ("dyadic", "zero", "cancellation", "random"):
            inputs = [array("d", (rng.randrange(-256, 257) / 256 for _ in range(n))) for _ in range(4)]
            if case == "zero":
                inputs[0] = array("d", [0.0]) * n
                inputs[2] = array("d", [-0.0]) * n
            elif case == "cancellation":
                inputs[2] = array("d", (-a * b for a, b in zip(inputs[0], inputs[1])))
            elif case == "random":
                inputs = [array("d", (rng.uniform(-1, 1) for _ in range(n))) for _ in range(4)]
            first, second, out = (array("d", [0.0]) * n for _ in range(3))
            library.fusion_baseline(n, *(buffer(values) for values in [*inputs, first, second, out]))
            expected = [float((Fraction(a) * Fraction(b) + Fraction(c)) * Fraction(d))
                        for a, b, c, d in zip(*inputs)]
            # Dyadic cases fit FP64 exactly, including every intermediate.
            tolerance = 16 * math.ulp(1.0) if case == "random" else 0
            errors = [abs(actual - reference) for actual, reference in zip(out, expected)]
            if any(not math.isfinite(value) for value in out) or max(errors, default=0) > tolerance:
                raise AssertionError(f"fusion baseline numerical check failed at n={n}, case={case}")
            checks.append({"kernel": "fusion", "n": n, "case": case,
                           "max_absolute_error": max(errors, default=0), "absolute_tolerance": tolerance})

    for n in (0, 1, 3, 17, 65):
        for case in ("zero", "identity", "random"):
            a = array("d", (rng.uniform(-1, 1) for _ in range(n * n)))
            if case == "random":
                b = array("d", (rng.uniform(-1, 1) for _ in range(n * n)))
            else:
                b = array("d", (float(case == "identity" and i == j) for i in range(n) for j in range(n)))
            out = array("d", [0.0]) * (n * n)
            library.matmul_baseline(n, buffer(a), buffer(b), buffer(out))
            if case == "identity":
                expected = list(a)
            elif case == "zero":
                expected = [0.0] * (n * n)
            else:
                expected = [math.fsum(a[i * n + k] * b[k * n + j] for k in range(n))
                            for i in range(n) for j in range(n)]
            errors = [abs(actual - reference) for actual, reference in zip(out, expected)]
            tolerance = 8 * math.ulp(1.0) * max(1, n * n)
            if any(not math.isfinite(value) for value in out) or max(errors, default=0) > tolerance:
                raise AssertionError(f"matmul baseline numerical check failed at n={n}, case={case}")
            checks.append({"kernel": "matmul", "n": n, "case": case,
                           "max_absolute_error": max(errors, default=0), "absolute_tolerance": tolerance})
    print(json.dumps({"status": "passed", "compile_command": command, "seed": 20261123,
                      "checks": checks, "scope": "Baseline correctness only; no candidate evaluation or comparative timing."}, indent=2))


if __name__ == "__main__":
    main()
