#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
umask 077
mkdir -p .local
exec 9>.local/runtime.lock
flock -sn 9 || { echo 'Installation is in progress.' >&2; exit 1; }
[[ -x .venv/bin/python ]] || { echo 'Run ./install.sh first.' >&2; exit 1; }
cuda_libs="$(.venv/bin/python -c 'import glob; print(":".join(glob.glob(".venv/lib/python*/site-packages/nvidia/*/lib")))')"
export LD_LIBRARY_PATH="${cuda_libs}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec .venv/bin/python -m interview_helper "$@"
