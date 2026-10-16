"""Shared explicit-device model, independent LocalAgreement stream states."""

import asyncio
import time
import numpy as np
from .vendor.local_agreement import OnlineASRProcessor
from .vendor.timed import ASRToken


class Backend:
    sep = ""
    tokenizer = None
    confidence_validation = False
    buffer_trimming = "segment"
    buffer_trimming_sec = 25

    def __init__(self, config):
        from faster_whisper import WhisperModel
        import ctranslate2

        supported = ctranslate2.get_supported_compute_types(config.device)
        if config.compute_type not in supported:
            raise RuntimeError(
                f"Requested {config.device}/{config.compute_type} unavailable; no fallback"
            )
        self.config = config
        model_path = config.model
        if config.model == "large-v3-turbo":
            from faster_whisper.utils import download_model

            model_path = download_model(
                config.model, cache_dir=str(config.model_dir), revision=config.model_revision
            )
        self.model = WhisperModel(
            model_path,
            device=config.device,
            compute_type=config.compute_type,
            download_root=str(config.model_dir),
            cpu_threads=4,
        )

    def transcribe(self, audio, init_prompt=""):
        segments, _ = self.model.transcribe(
            audio,
            language=self.config.language if self.config.language != "auto" else None,
            initial_prompt=self.config.glossary + " " + init_prompt,
            beam_size=5,
            word_timestamps=True,
            condition_on_previous_text=True,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        return list(segments)

    @staticmethod
    def ts_words(segments):
        return [
            ASRToken(w.start, w.end, w.word, w.probability)
            for s in segments
            if s.no_speech_prob <= 0.9
            for w in (s.words or [])
        ]

    @staticmethod
    def segments_end_ts(segments):
        return [s.end for s in segments]

    def warmup(self):
        # Exercise the actual encoder, not a VAD-skipped silent transcribe.
        self.model.encode(np.zeros((self.model.model.n_mels, 3000), dtype=np.float32))


class Recognizer:
    def __init__(self, config):
        self.config = config
        self.backend = None
        self.lock = asyncio.Lock()

    async def load(self):
        self.backend = await asyncio.to_thread(Backend, self.config)
        await asyncio.to_thread(self.backend.warmup)

    async def run_source(self, capture, emit, status):
        online = OnlineASRProcessor(self.backend)
        active = False
        silence = 0.0
        since = 0.0
        pre_roll = []
        started = time.monotonic()

        async def process(final=False):
            nonlocal since, active
            if not active:
                return
            async with self.lock:
                t0 = time.monotonic()
                tokens, _ = await asyncio.to_thread(online.process_iter)
                await emit(tokens, online.get_buffer().text, False)
                if final:
                    tail, _ = online.finish()
                    await emit(tail, "", True)
                status(
                    "ready",
                    {
                        "inference_seconds": round(time.monotonic() - t0, 3),
                        "speech_pause": final,
                        "lag_seconds": round(capture.queue.qsize() * 0.1, 1),
                    },
                )
            since = 0
            if final:
                active = False

        try:
            while not capture.stopping or not capture.queue.empty():
                try:
                    timestamp, block = await asyncio.wait_for(capture.queue.get(), 0.25)
                except asyncio.TimeoutError:
                    continue
                energy = float(np.sqrt(np.mean(block * block)))
                status(
                    "listening",
                    {
                        "level": round(min(1, energy * 12), 3),
                        "speech_active": energy >= self.config.rms_threshold,
                        "lag_seconds": round(capture.queue.qsize() * 0.1, 1),
                    },
                )
                if energy >= self.config.rms_threshold:
                    if not active:
                        first = pre_roll[0][0] if pre_roll else timestamp
                        online.init(offset=first)
                        for _, prior in pre_roll:
                            online.insert_audio_chunk(prior)
                        pre_roll.clear()
                        active = True
                    silence = 0
                else:
                    silence += len(block) / 16000
                if active:
                    online.insert_audio_chunk(block)
                    since += len(block) / 16000
                    if len(online.audio_buffer) > 30 * 16000:
                        raise RuntimeError("Uncommitted ASR audio exceeded 30s; source stopped")
                    if silence >= 1.0:
                        await process(final=True)
                    elif since >= 1.0:
                        await process()
                else:
                    pre_roll.append((timestamp, block))
                    pre_roll = pre_roll[-3:]
            await process(final=True)
        except Exception as exc:
            status("failed", {"error": str(exc), "uptime": time.monotonic() - started})
            await capture.stop()
            raise
