#!/usr/bin/env python3
"""Isolated real PulseAudio topology/capture checks; no desktop route changes."""

import asyncio
import json
import os
from pathlib import Path
import tempfile
import time
import numpy as np
from interview_helper.audio import discover, Capture


async def command(*args):
    p = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await p.communicate()
    if p.returncode:
        raise RuntimeError(err.decode())
    return out.decode().strip()


async def main():
    root = Path(".local/audio-acceptance")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix="ih-pulse-") as tmp:
        socket = Path(tmp) / "native"
        log = (root / "pulse.log").open("w")
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
            "--load=module-null-sink sink_name=ih-speakers",
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        previous = os.environ.get("PULSE_SERVER")
        os.environ["PULSE_SERVER"] = "unix:" + str(socket)
        captures = []
        try:
            for _ in range(50):
                if socket.exists():
                    break
                await asyncio.sleep(0.1)
            devices, _ = await discover()
            assert [d.sink for d in devices] == ["ih-speakers"]
            cap = Capture(devices[0], lambda *_: None, time.monotonic())
            await cap.start()
            captures.append(cap)
            samples = (0.1 * np.sin(2 * np.pi * 440 * np.arange(16000) / 16000)).astype("<f4")
            player = await asyncio.create_subprocess_exec(
                "pacat",
                "--playback",
                "--raw",
                "--format=float32le",
                "--rate=16000",
                "--channels=1",
                "--device=ih-speakers",
                stdin=asyncio.subprocess.PIPE,
            )
            await player.communicate(samples.tobytes())
            await asyncio.sleep(0.2)
            peak = 0
            while not cap.queue.empty():
                _, block = cap.queue.get_nowait()
                peak = max(peak, float(np.max(np.abs(block))))
            assert peak > 0.02
            headset = await command(
                "pactl", "load-module", "module-null-sink", "sink_name=ih-headset"
            )
            devices, _ = await discover()
            assert len(devices) == 2
            loop = await command(
                "pactl",
                "load-module",
                "module-loopback",
                "source=ih-speakers.monitor",
                "sink=ih-headset",
                "latency_msec=20",
            )
            devices, warnings = await discover()
            assert [d.sink for d in devices] == ["ih-speakers"]
            await command("pactl", "unload-module", loop)
            await command("pactl", "unload-module", headset)
            devices, _ = await discover()
            assert len(devices) == 1
            result = {
                "passed": True,
                "server": "isolated PulseAudio",
                "real_pcm_peak": peak,
                "checks": [
                    "monitor discovery",
                    "16kHz mono float32 capture",
                    "null-sink hotplug",
                    "loopback deduplication",
                    "disconnect discovery",
                ],
                "limits": ["not PipeWire", "not physical speaker/headset switching", "not GPU ASR"],
            }
            (root / "receipt.json").write_text(json.dumps(result, indent=2))
            print(json.dumps(result, indent=2))
        finally:
            for capture in captures:
                await capture.stop()
            if server.returncode is None:
                import signal

                os.killpg(server.pid, signal.SIGTERM)
                await server.wait()
            log.close()
            if previous is None:
                os.environ.pop("PULSE_SERVER", None)
            else:
                os.environ["PULSE_SERVER"] = previous


if __name__ == "__main__":
    asyncio.run(main())
