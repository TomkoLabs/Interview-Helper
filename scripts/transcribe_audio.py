#!/usr/bin/env python3
"""Replay recorded audio through the same independent streaming ASR state.

No recording is created. Existing files are decoded to bounded PCM blocks via PyAV.
"""

import argparse
import asyncio
import json
from pathlib import Path
import time
import numpy as np
from interview_helper.asr import Recognizer
from interview_helper.config import Config


async def transcribe(config, path, output, realtime=False):
    from faster_whisper.audio import decode_audio

    # File-based diagnostic is intentionally separate from bounded live capture.
    audio = await asyncio.to_thread(decode_audio, str(path), sampling_rate=16000)
    recognizer = Recognizer(config)
    started = time.monotonic()
    await recognizer.load()
    loaded = time.monotonic() - started

    class ReplayCapture:
        queue = asyncio.Queue(maxsize=300)
        stopping = False

        async def stop(self):
            self.stopping = True

    capture = ReplayCapture()
    events = []

    async def emit(tokens, provisional, final):
        events.append(
            {
                "at": time.monotonic() - started,
                "text": "".join(t.text for t in tokens),
                "provisional": provisional,
                "final": final,
                "start": tokens[0].start if tokens else None,
                "end": tokens[-1].end if tokens else None,
            }
        )

    statuses = []
    worker = asyncio.create_task(
        recognizer.run_source(capture, emit, lambda s, d: statuses.append({"state": s, **d}))
    )

    async def feed():
        padded = np.concatenate([audio, np.zeros(16000, dtype=np.float32)])
        for pos in range(0, len(padded), 1600):
            if worker.done():
                break
            await capture.queue.put((pos / 16000, padded[pos : pos + 1600]))
            if realtime:
                await asyncio.sleep(0.1)
        capture.stopping = True

    await feed()
    await worker
    result = {
        "model": config.model,
        "device": config.device,
        "compute": config.compute_type,
        "audio_seconds": len(audio) / 16000,
        "load_seconds": loaded,
        "elapsed_seconds": time.monotonic() - started,
        "realtime_feed": realtime,
        "text": " ".join(e["text"].strip() for e in events if e["text"].strip()),
        "events": events,
        "max_queue_lag_seconds": max((s.get("lag_seconds", 0) for s in statuses), default=0),
    }
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "events"}, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("audio", type=Path)
    p.add_argument("--config", type=Path, default=Path("config.local.toml"))
    p.add_argument("--output", type=Path, default=Path(".local/asr-validation.json"))
    p.add_argument("--realtime", action="store_true")
    a = p.parse_args()
    asyncio.run(transcribe(Config.load(a.config), a.audio, a.output, a.realtime))
