"""Project paths and a caller-selectable directory for temporary artifacts."""

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def scratch_directory():
    directory = Path(os.environ.get("TMPDIR", ROOT / ".cache")) / "mathkernel"
    directory.mkdir(parents=True, exist_ok=True)
    return directory.resolve()
