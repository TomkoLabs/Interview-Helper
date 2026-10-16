"""Offline installed-pin check used by the existing installer (no network)."""

import importlib.metadata
import importlib.util
from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parents[1]
files = [root / "requirements.lock"]
if "--gpu" in sys.argv:
    files.append(root / "requirements-cuda.txt")
try:
    for path in files:
        for line in path.read_text().splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            name, version = line.split("==")
            if importlib.metadata.version(name) != version:
                raise ValueError("Dependency mismatch")
    if "--package" in sys.argv:
        expected = re.search(
            r'__version__ = "([^"]+)"', (root / "src/interview_helper/__init__.py").read_text()
        )[1]
        if importlib.metadata.version("interview-helper") != expected:
            raise ValueError("Package version mismatch")
        spec = importlib.util.find_spec("interview_helper")
        if not spec or Path(spec.origin).resolve().parent != root / "src/interview_helper":
            raise ValueError("Wrong editable installation")
except (importlib.metadata.PackageNotFoundError, ValueError, OSError):
    raise SystemExit(1) from None
