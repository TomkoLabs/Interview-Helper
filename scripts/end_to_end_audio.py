#!/usr/bin/env python3
"""Real isolated audio -> streaming ASR -> gateway -> durable session acceptance.

Supply a permitted recorded question. This creates its own PulseAudio/D-Bus
instance; desktop routing/volume is never modified. Real model requests are made.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path
import signal
import tempfile
import time
from interview_helper.budget import reject_unbudgeted_api
from interview_helper.config import Config
from interview_helper.session import Session
from interview_helper.storage import SessionStore


async def run(config, audio, output, expect_model_unavailable=False):
    reject_unbudgeted_api(config.endpoints)
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    config.data_dir = output / "sessions"
    with tempfile.TemporaryDirectory(prefix="ih-e2e-") as tmp:
        socket = Path(tmp) / "native"
        log = (output / "pulse.log").open("w")
        server = await asyncio.create_subprocess_exec(
            "dbus-run-session",
            "--",
            "pulseaudio",
            "-n",
            "--daemonize=no",
            "--use-pid-file=no",
            "--exit-idle-time=-1",
            "--disable-shm=yes",
            "--load=module-native-protocol-unix socket=" + str(socket) + " auth-anonymous=1",
            "--load=module-null-sink sink_name=ih-test-playback",
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        previous = os.environ.get("PULSE_SERVER")
        os.environ["PULSE_SERVER"] = "unix:" + str(socket)
        session = Session(config)
        started = time.monotonic()
        try:
            for _ in range(50):
                if socket.exists():
                    break
                await asyncio.sleep(0.1)
            session.start()
            for _ in range(180):
                if session.captures:
                    break
                if session.state == "failed":
                    raise RuntimeError(session.notices)
                await asyncio.sleep(1)
            assert session.captures, "Capture did not start"
            player = await asyncio.create_subprocess_exec(
                "paplay", "--device=ih-test-playback", str(audio)
            )
            await player.wait()
            assert player.returncode == 0
            for tick in range(180):
                if tick % 10 == 0:
                    print(
                        json.dumps(
                            {
                                "elapsed": time.monotonic() - started,
                                "state": session.state,
                                "status": session.status,
                                "hosts": session.hosts,
                                "provisional": session.provisional,
                            }
                        ),
                        flush=True,
                    )
                if session.controller.cards and not any(session.provisional.values()):
                    break
                if (
                    expect_model_unavailable
                    and session.transcript
                    and not any(session.provisional.values())
                    and any(word in session.status["model"] for word in ("failed", "unavailable"))
                ):
                    break
                await asyncio.sleep(1)
            await session.shutdown()
            data = SessionStore.inspect(config.data_dir, session.store.id)
            text = " ".join(e["text"] for e in data["events"] if e["type"] == "transcript")
            result = {
                "session_id": session.store.id,
                "state": session.state,
                "elapsed_seconds": time.monotonic() - started,
                "text": text,
                "cards": session.controller.cards,
                "status": session.status,
                "notices": list(session.notices),
                "scope": "real isolated PulseAudio + CPU ASR + configured authenticated gateway",
            }
            if expect_model_unavailable:
                result["scope"] = (
                    "real isolated PulseAudio + CPU ASR with intentionally unreachable test endpoint"
                )
            (output / "receipt.json").write_text(json.dumps(result, indent=2))
            assert text and session.state == "ended", result
            if expect_model_unavailable:
                assert not session.controller.cards and any(
                    word in session.status["model"] for word in ("failed", "unavailable")
                ), result
                assert session.status["save"] == "saved", result
            else:
                assert session.controller.cards, result
            print(json.dumps(result, indent=2))
        finally:
            await session.shutdown()
            if server.returncode is None:
                os.killpg(server.pid, signal.SIGTERM)
                await server.wait()
            log.close()
            if previous is None:
                os.environ.pop("PULSE_SERVER", None)
            else:
                os.environ["PULSE_SERVER"] = previous


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("audio", type=Path)
    p.add_argument("--config", type=Path, default=Path("config.local.toml"))
    p.add_argument("--output", type=Path, default=Path(".local/e2e-audio"))
    p.add_argument(
        "--expect-model-unavailable",
        action="store_true",
        help="Use only with an intentionally unreachable separate test configuration",
    )
    a = p.parse_args()
    asyncio.run(run(Config.load(a.config), a.audio, a.output, a.expect_model_unavailable))
