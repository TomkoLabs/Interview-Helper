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


class RecognitionDeferred(RuntimeError):
    """No inference started; captured audio is still buffered."""


class RecognitionPending(RuntimeError):
    """The native operation still owns the model lane."""


def trim_microphone_committed(online):
    """Reclaim already-published PCM before applying the unchanged 6s loss guard.

    LocalAgreement normally retains committed audio until its 25s segment trim.
    Its buffer length therefore does not measure uncommitted speech. Use its
    existing committed-boundary trim; never discard an unstable hypothesis here.
    Called only while no native inference is running on this processor.
    """
    if len(online.audio_buffer) > 6 * 16000 and online.committed:
        boundary = online.committed[-1].end
        if online.buffer_time_offset < boundary <= online.get_audio_buffer_end_time():
            online.chunk_at(boundary)


class Recognizer:
    def __init__(self, config):
        self.config = config
        self.backend = None
        self.lock = asyncio.Lock()
        self.playback_waiters = 0
        self.microphone_job = None
        self.microphone_metrics = {}

    @property
    def microphone_overloaded(self):
        return bool(self.microphone_job and not self.microphone_job.done())

    async def infer(self, online, microphone=False):
        if microphone and self.microphone_overloaded:
            raise RecognitionPending("Microphone ASR still running; no concurrent retry")
        queued = time.monotonic()

        async def work():
            if microphone:
                if self.lock.locked() or self.playback_waiters:
                    raise RecognitionDeferred("Microphone ASR deferred: playback has priority")
                await self.lock.acquire()
            else:
                self.playback_waiters += 1
                try:
                    if self.microphone_overloaded:
                        await asyncio.wait_for(self.lock.acquire(), 3)
                    else:
                        await self.lock.acquire()
                finally:
                    self.playback_waiters -= 1
            started = time.monotonic()
            try:
                return await asyncio.to_thread(online.process_iter)
            finally:
                if microphone:
                    self.microphone_metrics = {
                        "scheduling_seconds": round(started - queued, 3),
                        "inference_seconds": round(time.monotonic() - started, 3),
                    }
                self.lock.release()

        if not microphone:
            return await work()
        job = asyncio.create_task(work())
        self.microphone_job = job
        try:
            # The deadline changes status, not ownership. A later completion permits
            # recovery; unresolved native work is never cancelled or retried over.
            return await asyncio.wait_for(asyncio.shield(job), 1.5)
        except TimeoutError as exc:
            raise RecognitionPending("Microphone ASR exceeded 1.5s; awaiting completion") from exc
        finally:
            if not job.done():
                job.add_done_callback(
                    lambda task: task.exception() if not task.cancelled() else None
                )

    async def load(self):
        self.backend = await asyncio.to_thread(Backend, self.config)
        await asyncio.to_thread(self.backend.warmup)

    async def run_source(self, capture, emit, status):
        if getattr(capture, "microphone", False):
            return await self._run_microphone(capture, emit, status)
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
            t0 = time.monotonic()
            tokens, _ = await self.infer(online, getattr(capture, "microphone", False))
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

    async def _run_microphone(self, capture, emit, status):
        """Bounded independent history. Deferral/slow calls keep the verified AEC."""
        online = OnlineASRProcessor(self.backend)
        active, since, silence = False, 0.0, 0.0
        generation = capture.generation
        pre_roll = []
        retry_at = 0.0
        deferred_at = None

        def reset():
            nonlocal online, active, since, silence, generation
            # Only called after any native operation has completed.
            online = OnlineASRProcessor(self.backend)
            active, since, silence = False, 0.0, 0.0
            generation = capture.generation
            pre_roll.clear()

        async def process(final=False):
            nonlocal active, since, retry_at, deferred_at
            if not active or time.monotonic() < retry_at:
                return
            try:
                tokens, _ = await self.infer(online, True)
            except RecognitionDeferred:
                deferred_at = deferred_at or time.monotonic()
                status(
                    "deferred",
                    {
                        "reason": "Playback has priority; audio buffered",
                        "scheduling_seconds": round(time.monotonic() - deferred_at, 3),
                    },
                )
                retry_at = time.monotonic() + 0.5
                return
            except RecognitionPending:
                status("quarantined", {"reason": "Native ASR still running; waiting safely"})
                # Keep draining in the capture process into its bounded queue. If
                # it overflows, generation changes and this result is discarded.
                tokens, _ = await asyncio.shield(self.microphone_job)
            if capture.generation != generation:
                reset()
                return
            deferred_at = None
            await emit(tokens, online.get_buffer().text, False)
            if final:
                tail, _ = online.finish()
                await emit(tail, "", True)
                active = False
            since = 0
            status(
                "ready",
                {
                    **self.microphone_metrics,
                    "reason": "Recognition completed",
                    "lag_seconds": round(capture.queue.qsize() * 0.1, 1),
                },
            )

        while not capture.stopping or not capture.queue.empty():
            try:
                timestamp, block = await asyncio.wait_for(capture.queue.get(), 0.25)
            except TimeoutError:
                continue
            if capture.generation != generation:
                reset()
            energy = float(np.sqrt(np.mean(block * block)))
            status(
                "listening",
                {
                    "level": round(min(1, energy * 12), 3),
                    "lag_seconds": round(capture.queue.qsize() * 0.1, 1),
                    "buffer_seconds": round(len(online.audio_buffer) / 16000, 1),
                },
            )
            if energy >= self.config.rms_threshold:
                if not active:
                    online.init(offset=pre_roll[0][0] if pre_roll else timestamp)
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
                trim_microphone_committed(online)
                if len(online.audio_buffer) > 6 * 16000:
                    status(
                        "gap",
                        {"error": "Uncommitted microphone audio exceeded 6s; continuity reset"},
                    )
                    reset()
                elif silence >= 1 or since >= 1:
                    await process(final=silence >= 1)
            else:
                pre_roll.append((timestamp, block))
                pre_roll = pre_roll[-3:]
        await process(final=True)
        if active:
            status(
                "gap",
                {
                    "error": "Microphone stopped before buffered speech could be recognized; tail omitted"
                },
            )
