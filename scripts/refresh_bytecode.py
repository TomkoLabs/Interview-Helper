"""Invalidate IH bytecode before any application import after source replacement.

Standalone stdlib script: executing this file never imports interview_helper.
Call without --check only while holding .local/runtime.lock exclusively.
"""

import hashlib
import importlib.util
from pathlib import Path
import sys


def main():
    if sys.argv[1:] not in ([], ["--check"]):
        raise SystemExit("Usage: python scripts/refresh_bytecode.py [--check]")
    root = Path(__file__).resolve().parents[1]
    package = root / "src/interview_helper"
    if package.is_symlink() or not (package / "__init__.py").is_file():
        raise SystemExit("IH source package unavailable; restore the source archive first.")
    sources = sorted(package.rglob("*.py"))
    digest = hashlib.sha256(Path(__file__).read_bytes())
    digest.update(
        f"{package}:{sys.implementation.cache_tag}:{sys.pycache_prefix}:{sys.flags.optimize}".encode()
    )
    for source in sources:
        digest.update(str(source.relative_to(package)).encode() + b"\0")
        digest.update(source.read_bytes())
    expected = digest.hexdigest() + "\n"
    marker = root / ".local/application-source.sha256"
    if marker.is_file() and marker.read_text() == expected:
        return
    if "--check" in sys.argv:
        raise SystemExit(1)

    # Only IH's bytecode, including vendored IH modules and other Python tags.
    # Also cover an explicitly configured Python cache prefix without touching
    # any dependency caches there. Never remove directories or private data.
    caches = set(package.rglob("*.pyc"))
    caches.update(Path(importlib.util.cache_from_source(str(source))) for source in sources)
    for cache in caches:
        cache.unlink(missing_ok=True)
    marker.parent.mkdir(mode=0o700, exist_ok=True)
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(expected)
    temporary.chmod(0o600)
    temporary.replace(marker)


if __name__ == "__main__":
    main()
