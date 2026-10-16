#!/usr/bin/env bash
# One entrypoint; install.sh and run.sh still own installation and runtime locks.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
umask 077
cpu=()
browser=()
for arg in "$@"; do
  case "$arg" in
    --cpu) cpu=(--cpu) ;;
    --no-browser) browser=(--no-browser) ;;
    *) echo 'Usage: ./start.sh [--cpu] [--no-browser]' >&2; exit 2 ;;
  esac
done
mode="$("${PYTHON:-python3}" scripts/start_prerequisites.py "${cpu[@]}")"
./install.sh "$mode" --if-needed
./run.sh prepare
if [[ ! -t 0 || -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then browser=(--no-browser); fi
exec ./run.sh serve "${browser[@]}"
