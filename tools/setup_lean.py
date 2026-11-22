#!/usr/bin/env python3
"""Install the pinned Linux x86_64 Lean environment locally and build the model."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import tomllib


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mathkernel.paths import ROOT, scratch_directory


VERSION = "4.24.0"
ARCHIVE = f"lean-{VERSION}-linux.tar.zst"
SHA256 = "b14f5e5159219dd1a1956c3b806813319f5e94ccd5bdfd56f54520609a5bb5ec"


def prepare_packages(environment):
    """Materialize the pinned upstream dependency graph without Git history."""
    lean = ROOT / "lean"
    dependency = tomllib.loads((lean / "lakefile.toml").read_text())["require"][0]
    packages = lean / ".lake" / "packages"
    packages.mkdir(parents=True, exist_ok=True)

    def checkout(name, url, revision):
        directory = packages / name
        if not directory.exists():
            directory.mkdir()
            for arguments in (("init", "-q"), ("remote", "add", "origin", url), ("fetch", "--depth", "1", "origin", revision), ("checkout", "--detach", "FETCH_HEAD")):
                subprocess.run(["git", *arguments], cwd=directory, env=environment, check=True)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=directory, env=environment, text=True).strip()
        if head != revision:
            raise SystemExit(f"{directory} is at {head}, expected {revision}")
        return directory

    mathlib = checkout(dependency["name"], dependency["git"], dependency["rev"])
    upstream = json.loads((mathlib / "lake-manifest.json").read_text())
    entries = []
    for package in upstream["packages"]:
        directory = checkout(package["name"], package["url"], package["rev"])
        tag = package.get("inputRev", "")
        if tag.startswith("v"):
            tag_present = subprocess.run(["git", "show-ref", "--verify", "--quiet", f"refs/tags/{tag}"], cwd=directory, env=environment)
            if tag_present.returncode:
                subprocess.run(["git", "fetch", "--depth", "1", "origin", "tag", tag], cwd=directory, env=environment, check=True)
        entries.append({**package, "inherited": True})
    entries.append({
        "url": dependency["git"], "type": "git", "subDir": None, "scope": "",
        "rev": dependency["rev"], "name": dependency["name"],
        "manifestFile": "lake-manifest.json", "inputRev": dependency["rev"],
        "inherited": False, "configFile": "lakefile.lean",
    })
    manifest = {**upstream, "name": "mathkernel", "packages": entries}
    (lean / "lake-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, help="Cache directory; defaults to TMPDIR/mathkernel or .cache/mathkernel")
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        parser.error("This bootstrap supports Linux x86_64; install Lean 4.24.0 and set MATHKERNEL_LAKE on other systems")
    try:
        from compression.zstd import ZstdFile
    except ImportError:
        parser.error("Bootstrap extraction requires Python 3.14; the agent CLI itself requires only Python 3.11+")
    cache = args.cache_dir.resolve() if args.cache_dir else scratch_directory()
    cache.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["TMPDIR"] = str(cache)
    environment["MATHLIB_CACHE_DIR"] = str(cache / "mathlib-cache")
    environment["MATHLIB_NO_CACHE_ON_UPDATE"] = "1"
    toolchain = ROOT / "lean" / ".toolchain"
    if not (toolchain / "bin" / "lake").is_file():
        archive = cache / ARCHIVE
        if not archive.exists() or archive.stat().st_size != 459625674:
            subprocess.run([
                "curl", "-fL", "--retry", "2", "--continue-at", "-",
                f"https://github.com/leanprover/lean4/releases/download/v{VERSION}/{ARCHIVE}",
                "-o", str(archive),
            ], env=environment, check=True)
        with archive.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if digest != SHA256:
            raise SystemExit(f"Toolchain checksum mismatch: {archive}")
        extracted = cache / f"lean-{VERSION}-linux"
        if not (extracted / "bin" / "lake").is_file():
            with ZstdFile(archive, "rb") as source, tarfile.open(fileobj=source, mode="r|") as tar:
                tar.extractall(cache, filter="data")
        toolchain.symlink_to(extracted, target_is_directory=True)
    environment["PATH"] = str(toolchain / "bin") + os.pathsep + environment.get("PATH", "")
    lake = str(toolchain / "bin" / "lake")
    prepare_packages(environment)
    commands = [
        ("--no-cache", "exe", "cache", "get", "Mathlib.Data.Matrix.Mul", "Mathlib.Data.Real.Basic"),
        ("--no-cache", "build", "MathKernel"),
    ]
    for arguments in commands:
        subprocess.run([lake, *arguments], cwd=ROOT / "lean", env=environment, check=True)
    print("Pinned Lean environment ready. Run python3 tools/mathkernel.py verify TASK CANDIDATE.")


if __name__ == "__main__":
    main()
