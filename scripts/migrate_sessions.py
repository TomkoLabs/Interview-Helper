#!/usr/bin/env python3
"""Copy legacy sessions, verify them, then switch only legacy data_dir settings."""

import argparse
import json
import os
from pathlib import Path
from interview_helper.migration import migrate

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.local.toml"))
    args = parser.parse_args()
    os.umask(0o077)
    try:
        print(json.dumps(migrate(args.config), indent=2))
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"Migration stopped: {exc}. Originals retained; inspect before retrying.\n")
