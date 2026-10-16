#!/usr/bin/env python3
"""User-run hidden credential entry; never reads another application's secrets."""

import getpass
import os
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1] / ".local"
    root.mkdir(mode=0o700, exist_ok=True)
    path = root / "openai-api-key"
    if path.exists():
        raise SystemExit("An app-owned key file already exists; no changes made.")
    if not sys.stdin.isatty():
        raise SystemExit(
            "Interactive terminal required; run .venv/bin/python scripts/configure_openai.py yourself."
        )
    key = getpass.getpass("Existing authorized OpenAI API key (hidden): ").strip()
    if not key or any(c.isspace() for c in key):
        raise SystemExit("No valid key entered; no changes made.")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as target:
        target.write(key + "\n")
        target.flush()
        os.fsync(target.fileno())
    print("Saved backend-only key in ignored .local/openai-api-key (0600).")
    print("No network call, account creation or billing change was performed.")


if __name__ == "__main__":
    main()
