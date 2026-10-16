"""Launch, diagnose, inspect/recover and replay without a browser dependency."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import webbrowser
from . import __version__
from .config import Config
from .storage import SessionStore, readable


async def diagnose(config, check_asr=False):
    from .audio import discover
    from .gateway import Gateway

    result = {
        "version": __version__,
        "os": platform.platform(),
        "python": platform.python_version(),
        "audio_commands": {x: shutil.which(x) is not None for x in ("pactl", "parec")},
        "asr": {
            "model": config.model,
            "device": config.device,
            "compute_type": config.compute_type,
        },
    }
    try:
        devices, warnings = await discover(config.include, config.exclude)
        result["devices"] = [d.__dict__ for d in devices]
        result["audio_warnings"] = warnings
    except Exception as exc:
        result["audio_error"] = str(exc)
    try:
        import ctranslate2

        result["compute_types"] = sorted(ctranslate2.get_supported_compute_types(config.device))
    except Exception as exc:
        result["cuda_error"] = str(exc)
    if shutil.which("nvidia-smi"):
        result["nvidia"] = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
        ).stdout.strip()
    gateway = Gateway(config.endpoints)
    result["models"] = {}
    for e in config.endpoints:
        try:
            catalog = await gateway.catalog(e)
            result["models"][e.name] = {
                "configured_model_present": e.model in catalog,
                "aliases": catalog,
            }
        except Exception as exc:
            result["models"][e.name] = {"error": type(exc).__name__}
    await gateway.close()
    if check_asr:
        from .asr import Recognizer

        try:
            recognizer = Recognizer(config)
            await recognizer.load()
            result["asr_warmup"] = "passed"
        except Exception as exc:
            result["asr_warmup"] = type(exc).__name__ + ": " + str(exc)
    print(json.dumps(result, indent=2))
    return result


async def replay(config, path, speed=1):
    from .session import Session

    session = Session(config)
    session.start(replay=True)
    records = json.loads(path.read_text())
    last = 0
    try:
        for record in records:
            delay = max(0, record["at"] - last) / speed
            await asyncio.sleep(delay)
            session.ingest(
                record.get("source", "replay"),
                record.get("label", "Replay playback"),
                record["text"],
                record["at"],
                record.get("end", record["at"] + 1),
            )
            last = record["at"]
    finally:
        await session.shutdown()
    print(
        json.dumps(
            {
                "session_id": session.store.id,
                "state": session.state,
                "cards": len(session.controller.cards),
                "status": session.status,
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description="IH")
    parser.add_argument("--config", type=Path, default=Path("config.local.toml"))
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command")
    commands.add_parser(
        "prepare", help="Check credentials and initialize local ASR without inference"
    )
    serve = commands.add_parser("serve")
    serve.add_argument("--no-browser", action="store_true")
    doctor = commands.add_parser("diagnose")
    doctor.add_argument(
        "--asr", action="store_true", help="Load and warm the configured model (may download it)"
    )
    inspect = commands.add_parser("recover")
    inspect.add_argument("session_id")
    inspect.add_argument("--write-view", action="store_true")
    summary = commands.add_parser("summarize")
    summary.add_argument("session_id")
    play = commands.add_parser("replay")
    play.add_argument("path", type=Path)
    play.add_argument("--speed", type=float, default=1)
    args = parser.parse_args()
    os.umask(0o077)
    config = Config.load(args.config)
    if args.command == "prepare":
        from .setup import prepare

        try:
            asyncio.run(prepare(config))
        except Exception as exc:
            # Credential/provider bodies are never emitted by setup.
            if isinstance(exc, ValueError):
                raise SystemExit(str(exc)) from None
            raise SystemExit(
                f"Local preparation failed ({type(exc).__name__}); run ./diagnose.sh --asr."
            ) from None
    elif args.command == "diagnose":
        asyncio.run(diagnose(config, args.asr))
    elif args.command == "recover":
        data = SessionStore.inspect(config.data_dir, args.session_id)
        if args.write_view:
            path = config.data_dir / args.session_id / "transcript.recovered.txt"
            # Preserve original journals/views and any previous recovery output.
            with path.open("x") as f:
                f.write(readable(data["events"]))
        print(
            json.dumps(
                {
                    "metadata": data["metadata"],
                    "partial_tail": data["partial_tail"],
                    "interrupted": data["interrupted"],
                    "events": len(data["events"]),
                    "hints": len(data["hints"]),
                },
                indent=2,
            )
        )
    elif args.command == "summarize":
        from .summary import summarize

        print(asyncio.run(summarize(config, args.session_id)))
    elif args.command == "replay":
        if args.speed <= 0:
            parser.error("speed must be positive")
        asyncio.run(replay(config, args.path, args.speed))
    else:
        import uvicorn
        from .app import create_app

        # One process: capture/model state is backend-owned and never duplicated.
        if not getattr(args, "no_browser", False):
            import threading

            threading.Timer(1, webbrowser.open, args=[f"http://127.0.0.1:{config.port}"]).start()
        uvicorn.run(create_app(config), host="127.0.0.1", port=config.port, access_log=False)
