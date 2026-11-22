"""Pinned Lean environment, source identity, and proof axiom checks."""

import hashlib
import os
from pathlib import Path
import re
import shutil

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
