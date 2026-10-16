"""First-run preparation: backend-only credentials and local ASR, never text inference."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from .storage import atomic_json


def ensure_credentials(config):
    for endpoint in config.endpoints:
        if endpoint.backend == "openai_api" and not endpoint.key:
            helper = config.root / "scripts/configure_openai.py"
            default_key = config.root / ".local/openai-api-key"
            if Path(endpoint.api_key_file) != default_key or not helper.exists():
                raise ValueError(
                    "Selected API profile has no key; configure its backend credential explicitly."
                )
            if not sys.stdin.isatty():
                raise ValueError(
                    "Missing OpenAI API key. In an interactive terminal run "
                    ".venv/bin/python scripts/configure_openai.py, then ./start.sh. "
                    "API billing is separate from a ChatGPT subscription."
                )
            print("OpenAI API sends transcript context to OpenAI with separate API billing.")
            subprocess.run([sys.executable, str(helper)], check=True)
            if not endpoint.key:
                raise ValueError("No API key configured; launch stopped.")
        elif endpoint.backend == "chatgpt" and not Path(endpoint.oauth_file).exists():
            raise ValueError(
                "Saved ChatGPT account is unavailable. Use ./run.sh to complete app-owned sign-in "
                "or explicitly choose another connection. No API fallback was selected."
            )
    if not config.endpoints:
        print(
            "Explicit transcription-only configuration retained; select a connection in the UI for hints."
        )


async def prepare(config):
    ensure_credentials(config)
    from .asr import Recognizer
    import ctranslate2

    if config.compute_type not in ctranslate2.get_supported_compute_types(config.device):
        raise ValueError(
            "Configured ASR compute type unavailable; no CPU fallback. Check ./diagnose.sh."
        )
    fingerprint = hashlib.sha256(
        json.dumps(
            [
                config.model,
                config.model_revision,
                str(config.model_dir),
                config.device,
                config.compute_type,
                ctranslate2.__version__,
            ]
        ).encode()
    ).hexdigest()
    marker = config.root / ".local/asr-ready.json"
    try:
        previous = json.loads(marker.read_text())
    except (OSError, ValueError):
        previous = {}
    models = list(config.model_dir.rglob("model.bin"))
    custom = Path(config.model).expanduser()
    if custom.is_dir():
        models += list(custom.glob("model.bin"))
    if previous.get("fingerprint") == fingerprint and any(p.is_file() for p in models):
        print("Reusing prepared local ASR model; session startup still verifies model loading.")
        return
    print(
        f"Initializing local ASR {config.model} ({config.device}/{config.compute_type}). "
        "Missing weights download to the configured model cache; this can take several minutes. "
        "No text-generation request or driver change is made."
    )
    await Recognizer(config).load()
    marker.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_json(marker, {"fingerprint": fingerprint})
    print("Local ASR warmup passed. Open the displayed local URL and Start session when ready.")
