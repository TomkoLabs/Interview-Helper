"""Read-only system checks before creating or changing the project environment."""

from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tomllib


def main():
    if sys.platform != "linux" or platform.machine() not in {"x86_64", "AMD64"}:
        raise SystemExit("Supported setup: Linux x86-64 with PulseAudio/PipeWire and NVIDIA CUDA.")
    if not (3, 11) <= sys.version_info[:2] < (3, 14):
        raise SystemExit("Python 3.11–3.13 with venv/pip is required; set PYTHON explicitly.")
    path = Path("config.local.toml")
    try:
        raw = tomllib.loads(path.read_text()) if path.exists() else {}
        device = raw.get("asr", {}).get("device", "cpu" if "--cpu" in sys.argv else "cuda")
    except (OSError, ValueError):
        raise SystemExit(
            "Cannot read config.local.toml; repair it without replacing your settings."
        ) from None
    for command in ("flock", "pactl", "parec"):
        if not shutil.which(command):
            raise SystemExit(
                f"Missing {command}; install the system prerequisite, then retry ./start.sh."
            )
    if subprocess.run(["pactl", "info"], capture_output=True, timeout=10).returncode:
        raise SystemExit(
            "Playback server unavailable. Run in your desktop login with PulseAudio/PipeWire Pulse compatibility."
        )
    if device == "cuda":
        if (
            not shutil.which("nvidia-smi")
            or subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True,
                timeout=10,
            ).returncode
        ):
            raise SystemExit(
                "Working NVIDIA driver required; IH never installs or changes drivers."
            )
    elif device != "cpu":
        raise SystemExit("ASR device must be explicitly cpu or cuda in config.local.toml.")
    print("--gpu" if device == "cuda" else "--cpu")


if __name__ == "__main__":
    main()
