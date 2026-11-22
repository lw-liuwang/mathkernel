"""Check the repository installation used by an agent or CI runner."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib

from .inputs import InputError, read_json
from .paths import scratch_directory
from .verification import ROOT, lake_environment


def doctor(timeout=120):
    checks = [{"name": "python", "ready": sys.version_info >= (3, 11), "detail": sys.version.split()[0],
               "remedy": "Use Python 3.11 or newer"}]
    os.environ.setdefault("MPLCONFIGDIR", str(scratch_directory() / "matplotlib"))
    plotting = importlib.util.find_spec("matplotlib") is not None
    detail = "matplotlib is not installed in this Python environment"
    if plotting:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            with tempfile.TemporaryDirectory(dir=scratch_directory()) as scratch:
                figure = plt.figure()
                try:
                    figure.savefig(Path(scratch) / "doctor.png")
                finally:
                    plt.close(figure)
            detail = "PNG export is available"
        except (ImportError, OSError, RuntimeError) as error:
            plotting, detail = False, str(error)
    checks.append({"name": "plotting", "ready": plotting, "detail": detail,
                   "remedy": "Install requirements-plot.txt in the Python environment running MathKernel"})
    try:
        lake, environment = lake_environment()
        pinned = (ROOT / "lean" / "lean-toolchain").read_text().strip().split(":")[-1].lstrip("v")
        version = subprocess.run([lake, "env", "lean", "--version"], cwd=ROOT / "lean", env=environment,
                                 capture_output=True, text=True, timeout=timeout)
        matching = version.returncode == 0 and f"version {pinned}," in version.stdout
        checks.append({"name": "lean_version", "ready": matching, "detail": (version.stdout + version.stderr).strip(),
                       "remedy": "Run tools/setup_lean.py or set MATHKERNEL_LAKE to the pinned Lean environment"})
        if matching:
            dependency = tomllib.loads((ROOT / "lean" / "lakefile.toml").read_text())["require"][0]
            manifest = read_json(ROOT / "lean" / "lake-manifest.json")
            locked = next((item for item in manifest["packages"] if item["name"] == dependency["name"]), {})
            checkout = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT / "lean" / ".lake" / "packages" / dependency["name"],
                                      capture_output=True, text=True, timeout=timeout)
            pinned_dependency = locked.get("rev") == dependency["rev"] == checkout.stdout.strip()
            checks.append({"name": "mathlib_version", "ready": pinned_dependency,
                           "detail": checkout.stdout.strip() or checkout.stderr.strip(),
                           "remedy": "Prepare the pinned Mathlib checkout using tools/setup_lean.py"})
            build = subprocess.run([lake, "--no-cache", "build", "MathKernel"], cwd=ROOT / "lean", env=environment,
                                   capture_output=True, text=True, timeout=timeout)
            checks.append({"name": "proof_contract", "ready": build.returncode == 0, "detail": (build.stdout + build.stderr).strip(),
                           "remedy": "Prepare the pinned Mathlib dependencies and rebuild the MathKernel proof contract"})
    except (OSError, InputError, subprocess.TimeoutExpired) as error:
        checks.append({"name": "lean_environment", "ready": False, "detail": str(error),
                       "remedy": "Run tools/setup_lean.py; see README installation requirements"})
    ready = all(item["ready"] for item in checks)
    return {"status": "ready" if ready else "unavailable", "ready": ready, "checks": checks}
