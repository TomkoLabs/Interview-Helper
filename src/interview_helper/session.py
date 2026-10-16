"""Backend session owner; no dependency on a browser connection."""

import asyncio
from collections import deque
from pathlib import Path
import time
import uuid
from . import __version__
from .audio import AudioDiscoveryError, Capture, discover
from .asr import Recognizer
from .controller import Controller
from .gateway import Gateway
from .storage import SessionStore, now


class Session:
    def __init__(self, config):
        self.config = config
        self.state = "idle"
        self.store = None
        self.controller = None
        self.recognizer = None
        self.capture_task = None
        self.start_task = None
        self.end_task = None
        self.warm_task = None
        self.captures = {}
        self.devices = {}
        self.transcript = deque(maxlen=200)
        self.provisional = {}
        self.drafts = {}
        self.gateway_quarantine = set()
        self.notices = deque(maxlen=20)
        self.unsaved = []
        self.revision = 0
        self.status = {"capture": "idle", "asr": "idle", "model": "idle", "save": "idle"}
        self.hosts = {}
        self.started = 0
        self.errors = set()
        self.ended_elapsed = None
        self.hint_revision = 0
        self.hint_changed = asyncio.Event()
        self.published = {}
        self.visible = set()

    def view(self):
        return {
            "version": __version__,
            "hint_revision": self.hint_revision,
            "state": self.state,
            "session_id": self.store.id if self.store else None,
            "transcript_path": str(self.store.path / "transcript.txt") if self.store else None,
            "readable_error": self.store.view_error if self.store else None,
            "elapsed": self.ended_elapsed
            if self.ended_elapsed is not None
            else (round(time.monotonic() - self.started) if self.started else 0),
            "status": self.status,
            "hosts": self.hosts,
            "backend": [
                {
                    "name": e.name,
                    "model": e.model,
                    "kind": e.backend,
                    "tier": e.parameters.get("service_tier", "default"),
                    "transport": e.transport,
                    "reasoning": e.parameters.get("reasoning_effort", "low"),
                    "max_output_tokens": e.parameters.get("max_output_tokens"),
                    "account": Path(e.oauth_file).stem if e.backend == "chatgpt" else "",
                }
                for e in (
                    self.config.endpoints[:1]
                    if self.config.strategy == "single"
                    else self.config.endpoints
                )
            ],
            "devices": list(self.devices.values()),
            "transcript": list(self.transcript),
            "provisional": self.provisional,
            "drafts": list(self.drafts.values()),
            "cards": self.controller.cards[-200:] if self.controller else [],
            "notices": list(self.notices),
            "unsaved_count": len(self.unsaved),
        }

    def notice(self, message):
        if not self.notices or self.notices[-1]["message"] != message:
            self.notices.append({"time": now(), "message": message})

    async def publish(self, kind, data):
        self.hint_revision += 1
        self.hint_changed.set()
        self.hint_changed = asyncio.Event()
        if kind in {"draft", "card"}:
            self.published.setdefault(data["request_id"], time.monotonic())
            if len(self.published) > 256:
                self.published.pop(next(iter(self.published)))
        if kind == "draft":
            self.drafts[data["id"]] = data
        else:
            self.drafts = {
                k: v for k, v in self.drafts.items() if v["request_id"] != data["request_id"]
            }
        if kind == "discard" and data.get("error"):
            self.notice("Hint failed: " + data["error"] + "; previous answer retained")

    def acknowledge_visible(self, request_id):
        if (
            request_id not in self.published
            or request_id in self.visible
            or not self.store
            or self.store.closed
        ):
            return
        self.visible.add(request_id)
        self.visible.intersection_update(self.published)
        stamp = time.monotonic()
        start = self.controller.gateway.started.get(request_id) if self.controller else None
        self.save(
            {
                "type": "ui_visible",
                "request_id": request_id,
                "publish_to_ack_seconds": stamp - self.published[request_id],
                "dispatch_to_ack_seconds": stamp - start if start is not None else None,
                "measurement": "server receipt after browser animation frames; upper bound",
            },
            True,
        )

    def save(self, event, hint=False):
        try:
            self.store.append(event, hint)
            self.status["save"] = (
                "saved" if not self.store.view_error else "journal saved; readable view failed"
            )
            if self.store.view_error:
                self.notice(self.store.view_error)
        except OSError as exc:
            self.unsaved.append((event, hint))
            self.status["save"] = "FAILED — capture paused; retry saving before exit"
            self.state = "save_failed"
            self.notice(
                "Disk write failed; unsaved content retained in memory: " + type(exc).__name__
            )
            raise

    def retry_save(self):
        pending, self.unsaved = self.unsaved, []
        for index, (event, hint) in enumerate(pending):
            try:
                self.store.append(event, hint)
            except OSError:
                self.unsaved = pending[index:]
                raise
        self.status["save"] = "saved; end session then start again"

    def start(self, replay=False):
        if self.state not in {"idle", "ended", "failed"} or self.unsaved:
            raise ValueError("End the current session and save pending content first")
        if self.store and not self.store.closed:
            raise ValueError("Previous session still needs End session / recovery")
        self.devices.clear()
        self.transcript.clear()
        self.provisional.clear()
        self.drafts.clear()
        self.hosts.clear()
        self.errors.clear()
        self.notices.clear()
        self.revision = 0
        self.started = time.monotonic()
        self.ended_elapsed = None
        self.store = SessionStore(
            self.config.data_dir,
            {
                "version": __version__,
                "hint_revision": self.hint_revision,
                "mode": "transcript replay" if replay else "live playback",
                "asr": {
                    "model": self.config.model,
                    "device": self.config.device,
                    "compute_type": self.config.compute_type,
                },
            },
        )
        gateway = Gateway(
            self.config.endpoints, lambda name, status: self.hosts.update({name: status})
        )
        gateway.quarantined = self.gateway_quarantine
        self.controller = Controller(
            self.config,
            gateway,
            self.publish,
            lambda e: self.save(e, True),
            lambda s: self.status.update(model=s),
            observe=lambda e: self.save(e, True),
        )
        self.state = "recording" if replay else "starting"
        self.status.update(
            capture="replay" if replay else "discovering",
            asr="replay" if replay else "loading / warming",
            model="connecting"
            if self.config.endpoints
            else "unconfigured; transcription continues",
            save="saved",
        )
        if not replay:
            self.start_task = asyncio.create_task(self._start_live())
        return self.store.id

    async def _start_live(self):
        try:
            self.recognizer = Recognizer(self.config)
            await self.recognizer.load()
            if self.state != "starting":
                return
            self.state = "recording"
            self.status["asr"] = "ready"
            self.capture_task = asyncio.create_task(self._capture_loop())
            self.warm_task = asyncio.create_task(self._warm_models())
        except Exception as exc:
            self.status["asr"] = "failed: " + type(exc).__name__
            self.notice(str(exc))
            self.state = "failed"
            await self.controller.finish()
            self.store.close("startup_failed")

    async def _warm_models(self):
        endpoints = (
            self.config.endpoints[:1] if self.config.strategy == "single" else self.config.endpoints
        )

        async def ignore(*_):
            pass

        while self.state == "recording":
            for e in endpoints:
                if e.backend != "chat_completions":
                    continue  # No paid/plan-usage keepalive inference.
                # Real work has priority. Shared per-host lock bounds warmup too.
                if self.controller.gateway.locks[e.host_id].locked() or self.controller.pending:
                    continue
                if time.monotonic() - self.controller.last_submit < 75:
                    continue
                try:
                    aliases = await self.controller.gateway.catalog(e)
                    if e.model not in aliases:
                        raise ValueError("Configured model absent from authenticated catalog")
                    result = await self.controller.gateway.stream(
                        e,
                        [
                            {
                                "role": "user",
                                "content": 'Output exactly these two JSON lines:\n{"action":"WAIT"}\n{"done":true}',
                            }
                        ],
                        "warmup-" + uuid.uuid4().hex,
                        ignore,
                    )
                    if self.status["model"] == "connecting":
                        self.status["model"] = (
                            "failed: " + result.error if result.error else "ready"
                        )
                except Exception as exc:
                    self.hosts[e.name] = "unavailable: " + type(exc).__name__
                    if self.status["model"] == "connecting":
                        self.status["model"] = "unavailable; transcription continues"
            for _ in range(75):
                if self.state != "recording":
                    return
                await asyncio.sleep(1)

    def capture_status(self, source, state, message):
        self.devices.setdefault(source, {"name": source, "label": source})["state"] = state
        self.notice(message)
        key = (source, message)
        if key not in self.errors and self.store and not self.store.closed:
            self.errors.add(key)
            self.save(
                {
                    "type": "gap",
                    "source": source,
                    "reason": message,
                    "time": now(),
                    "at": time.monotonic() - self.started,
                }
            )

    async def _capture_loop(self):
        while self.state == "recording":
            try:
                monitors, warnings = await discover(self.config.include, self.config.exclude)
                for warning in warnings:
                    self.notice(warning)
                wanted = {m.name: m for m in monitors}
                for name in list(self.captures):
                    capture, worker = self.captures[name]
                    if name not in wanted or capture.stopping or worker.done():
                        await capture.stop()
                        await asyncio.gather(worker, return_exceptions=True)
                        del self.captures[name]
                        self.devices[name]["state"] = "disconnected"
                for name, monitor in wanted.items():
                    if name in self.captures:
                        continue
                    self.errors = {e for e in self.errors if e[0] != name}
                    self.devices[name] = {
                        "name": name,
                        "label": monitor.label,
                        "state": "listening",
                        "level": 0,
                    }
                    capture = Capture(monitor, self.capture_status, self.started)
                    await capture.start()

                    async def emit(tokens, provisional, final, name=name, label=monitor.label):
                        self.provisional[name] = provisional
                        if tokens:
                            self.ingest(
                                name,
                                label,
                                "".join(t.text for t in tokens),
                                tokens[0].start,
                                tokens[-1].end,
                                final,
                            )

                    def status(state, data, name=name):
                        self.devices[name].update(state=state, **data)
                        if data.get("speech_pause"):
                            self.controller.pause()
                        if "speech_active" in data:
                            self.controller.activity(data["speech_active"])
                        if state == "failed":
                            self.capture_status(name, state, data.get("error", "ASR failed"))

                    worker = asyncio.create_task(self.recognizer.run_source(capture, emit, status))
                    self.captures[name] = capture, worker
                self.status["capture"] = (
                    f"{len(self.captures)} playback device(s)"
                    if wanted
                    else "waiting for playback devices"
                )
            except Exception as exc:
                detail = (
                    str(exc)
                    if isinstance(exc, AudioDiscoveryError)
                    else "capture: " + type(exc).__name__
                )
                self.status["capture"] = "unavailable: " + detail
                self.notice(f"Audio unavailable ({detail}); reconnect will be retried")
            await asyncio.sleep(2)
        await self._stop_capture()

    def ingest(self, source, label, text, start, end, final=False):
        if not text.strip():
            return
        if self.state not in {"recording", "stopping"}:
            raise RuntimeError("Session is not accepting transcript")
        self.revision += 1
        event = {
            "type": "transcript",
            "segment_id": uuid.uuid4().hex,
            "revision": self.revision,
            "source": source,
            "source_name": label,
            "start": start,
            "end": end,
            "text": text.strip(),
            "time": now(),
            "commit": "final_flush" if final else "stable_prefix",
        }
        self.save(event)
        self.transcript.append(event)
        self.controller.ingest(event)

    async def _stop_capture(self):
        for capture, _ in self.captures.values():
            await capture.stop()
        for _, worker in self.captures.values():
            await asyncio.gather(worker, return_exceptions=True)
        self.captures.clear()

    def end(self):
        if self.end_task and not self.end_task.done():
            return
        if self.state in {"idle", "ended"}:
            return
        self.state = "stopping"
        self.end_task = asyncio.create_task(self._end())

    async def _end(self):
        try:
            if self.start_task and not self.start_task.done():
                await self.start_task
            if self.capture_task:
                await self.capture_task
            else:
                await self._stop_capture()
            if self.warm_task:
                await self.warm_task
            if self.controller and not self.controller.closed:
                await self.controller.finish()
                self.drafts.clear()
                if self.controller.reviewed < self.controller.revision:
                    self.notice("Unreviewed transcript tail saved; see review_shutdown diagnostics")
            if self.unsaved:
                self.state = "save_failed"
                return
            if self.store:
                self.store.close()
            self.ended_elapsed = round(time.monotonic() - self.started)
            self.state = "ended"
            self.status.update(capture="stopped", asr="flushed", save="saved")
            if self.store and self.store.view_error:
                self.status["save"] = "journal saved; readable view failed"
                self.notice(self.store.view_error)
            self.provisional.clear()
        except Exception as exc:
            self.state = "failed"
            self.notice("Session close failed: " + type(exc).__name__)

    async def shutdown(self):
        self.end()
        if self.end_task:
            await self.end_task
