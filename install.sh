#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
umask 077
mkdir -p .local
exec 9>.local/runtime.lock
flock -n 9 || { echo 'Stop Interview Helper before installing/updating.' >&2; exit 1; }
mode="${1:---cpu}"
case "$mode" in --cpu|--gpu) ;; *) echo 'Usage: ./install.sh [--cpu|--gpu] [--if-needed]' >&2; exit 2;; esac
[[ $# -le 2 && "${2:---if-needed}" == --if-needed ]] || { echo 'Unknown installer option.' >&2; exit 2; }
python="${PYTHON:-python3}"
"$python" -c 'import sys; assert (3,11) <= sys.version_info[:2] < (3,14), "Python 3.11–3.13 required"'
if [[ "$mode" == --gpu ]]; then
  command -v nvidia-smi >/dev/null || { echo 'Working NVIDIA driver required; no drivers are installed.' >&2; exit 1; }
  nvidia-smi --query-gpu=name,driver_version --format=csv,noheader
fi
[[ -d .venv ]] || "$python" -m venv .venv
if [[ "${2:-}" != --if-needed ]] || ! .venv/bin/python scripts/environment_ready.py "$mode"; then
  .venv/bin/python -m pip install -r requirements.lock
  if [[ "$mode" == --gpu ]]; then .venv/bin/python -m pip install -r requirements-cuda.txt; fi
fi
if [[ "${2:-}" != --if-needed ]] || ! .venv/bin/python scripts/environment_ready.py "$mode" --package; then
  .venv/bin/python -m pip install --no-deps -e .
fi
if [[ ! -e config.local.toml ]]; then
  cp config.example.toml config.local.toml
  if [[ "$mode" == --cpu ]]; then
    sed -i 's/device = "cuda"/device = "cpu"/; s/compute_type = "float16"/compute_type = "int8"/' config.local.toml
  fi
fi
printf '%s\n' 'Environment ready. Use ./start.sh to check configuration, initialize ASR and launch.'
