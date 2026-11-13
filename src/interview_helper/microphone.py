"""Optional, fail-closed physical microphone + owned PipeWire/WebRTC monitor AEC.

Pulse module indices identify topology; PipeWire node IDs identify live links.
Neither is used in place of the other. No desktop routing/defaults are changed.
"""

import asyncio
from collections import deque
import time
from dataclasses import dataclass
import json
import sys
import uuid
from .audio import AudioDiscoveryError, Monitor, pactl, select_monitors, stop_process


class MicrophoneUnavailable(RuntimeError):
    pass


async def command(*args):
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    try:
        out, _ = await asyncio.wait_for(process.communicate(), 3)
    except BaseException:
        await stop_process(process)
        raise
    if process.returncode:
        raise MicrophoneUnavailable(f"{args[0]} unavailable or permission denied")
    return out.decode()


def physical(record, modules):
    p = record.get("properties", {})
    owner = next((m for m in modules if str(m["index"]) == str(record.get("owner_module"))), {})
    return (
        not str(record["name"]).startswith("ih-aec-")
        and str(p.get("node.virtual", "false")).lower() not in {"true", "1"}
        and p.get("device.class") not in {"monitor", "filter", "abstract"}
        and not any(
            kind in owner.get("name", "")
            for kind in ("loopback", "filter", "echo-cancel", "combine", "remap")
        )
        and (
            owner.get("name")
            in {
                "module-alsa-card",
                "module-alsa-source",
                "module-alsa-sink",
                "module-bluez5-device",
            }
            or (not owner or owner.get("name", "").startswith("libpipewire-module-"))
        )
        and (
            p.get("device.api") in {"alsa", "bluez5"}
            or p.get("device.bus") in {"usb", "pci", "bluetooth"}
            or "api.alsa.path" in p
            or "alsa.card" in p
            or p.get("api.alsa.pcm.stream") in {"capture", "playback"}
        )
    )


@dataclass(frozen=True)
class Selection:
    microphone: Monitor
    reference: str

    def same_devices(self, other):
        return bool(
            other
            and self.microphone.name == other.microphone.name
            and self.reference == other.reference
        )


def select_input(
    sinks, sources, modules, inputs, outputs, default_source, default_sink, current=None
):
    # Use the same sink/source relationships as playback, including pactl 17.
    monitors, _ = select_monitors(sinks, sources, modules, inputs, outputs, include=["*"])
    monitor_names = {m.name for m in monitors}
    eligible = sorted(
        (
            s
            for s in sources
            if s["name"] not in monitor_names
            and physical(s, modules)
            and s.get("properties", {}).get("api.alsa.pcm.stream") != "playback"
        ),
        key=lambda s: s["name"],
    )
    if not eligible:
        raise MicrophoneUnavailable("No eligible physical microphone")
    mic = next((s for s in eligible if current and s["name"] == current), None)
    mic = mic or next((s for s in eligible if s["name"] == default_source), eligible[0])
    physical_sinks = [s for s in sinks if physical(s, modules)]
    active_inputs = [i for i in inputs if str(i.get("corked", False)).lower() not in {"true", "1"}]
    if any(
        str(i.get("sink")) not in {str(s["index"]) for s in physical_sinks} for i in active_inputs
    ):
        raise MicrophoneUnavailable(
            "AEC requires direct physical playback; virtual output routing unsupported"
        )
    # Monitor readers can keep sinks RUNNING. Only uncorked playback streams
    # establish an active output; otherwise use the eligible desktop default.
    active_ids = {str(i.get("sink")) for i in active_inputs}
    active = [s for s in physical_sinks if str(s["index"]) in active_ids]
    if len(active) > 1:
        raise MicrophoneUnavailable("AEC unavailable with multiple active speaker outputs")
    reference = (
        active[0]
        if active
        else next((s for s in physical_sinks if s["name"] == default_sink), None)
    )
    if not reference or reference["name"] not in {m.sink for m in monitors}:
        raise MicrophoneUnavailable("No safe physical playback-monitor reference")
    return Selection(
        Monitor(mic["name"], mic.get("description", mic["name"]), ""), reference["name"]
    )


async def discover_input(current=None):
    data = await asyncio.gather(
        *(pactl(k) for k in ("sinks", "sources", "modules", "sink-inputs", "source-outputs"))
    )
    defaults = await asyncio.gather(
        command("pactl", "get-default-source"), command("pactl", "get-default-sink")
    )
    try:
        return select_input(*data, *(d.strip() for d in defaults), current=current)
    except (ValueError, KeyError, TypeError) as exc:
        raise MicrophoneUnavailable("Invalid microphone/reference topology") from exc


async def graph():
    data = json.loads(await command("pw-dump"))
    if not isinstance(data, list):
        raise MicrophoneUnavailable("Invalid PipeWire graph")
    return data


def nodes(data):
    return {
        r["info"]["props"].get("node.name"): r
        for r in data
        if r.get("type") == "PipeWire:Interface:Node" and "info" in r
    }


class EchoCancel:
    """pw-cli owns a LOCAL module; exit removes only this client's three nodes.

    Requires native monitor.mode (verified against PipeWire 1.4.2), its WebRTC
    SPA library, session-manager autoconnect and readable live link topology.
    The Pulse module-echo-cancel wrapper does not expose monitor.mode.
    """

    def __init__(self, selection):
        self.selection = selection
        self.name = "ih-aec-" + uuid.uuid4().hex
        self.process = None
        self.targets = None

    def arguments(self):
        def props(suffix, **extra):
            return {
                "node.name": self.name + suffix,
                "node.description": "IH microphone (local AEC)",
                "node.virtual": True,
                "priority.session": -10000,
                "node.dont-fallback": True,
                "node.dont-reconnect": True,
                **extra,
            }

        return json.dumps(
            {
                "monitor.mode": True,
                "library.name": "aec/libspa-aec-webrtc",
                "audio.rate": 48000,
                "audio.channels": 1,
                "audio.position": ["MONO"],
                "capture.props": props(
                    "-capture", **{"target.object": self.selection.microphone.name}
                ),
                "sink.props": props("-reference", **{"target.object": self.selection.reference}),
                "source.props": props(
                    "", **{"media.class": "Audio/Source", "device.class": "filter"}
                ),
            }
        )

    def verify(self, data, require_reader=False):
        ns = nodes(data)
        names = [self.name, self.name + "-capture", self.name + "-reference"]
        if any(n not in ns for n in names):
            raise MicrophoneUnavailable("AEC nodes not ready; native monitor mode/WebRTC required")
        own = [n for n in ns if n and n.startswith(self.name) and n != self.name + "-reader"]
        if (
            set(own) != set(names)
            or ns[self.name]["info"]["props"].get("media.class") != "Audio/Source"
        ):
            raise MicrophoneUnavailable("Unexpected AEC nodes; refusing a playback route")
        for suffix in ("-capture", "-reference"):
            if ns[self.name + suffix]["info"]["props"].get("media.class") != "Stream/Input/Audio":
                raise MicrophoneUnavailable("AEC mode created an unexpected stream type")
        targets = []
        for target in (self.selection.microphone.name, self.selection.reference):
            if target not in ns:
                raise MicrophoneUnavailable("AEC physical input/reference disconnected")
            # Include serial to detect object-ID reuse after device removal.
            r = ns[target]
            targets.append((r["id"], str(r["info"]["props"].get("object.serial"))))
        if self.targets and self.targets != targets:
            raise MicrophoneUnavailable("AEC physical input/reference changed")
        ports = {
            r["id"]: r.get("info", {}).get("props", {})
            for r in data
            if r.get("type") == "PipeWire:Interface:Port"
        }
        links = [
            r["info"] for r in data if r.get("type") == "PipeWire:Interface:Link" and "info" in r
        ]
        for suffix, (target, _) in zip(("-capture", "-reference"), targets):
            incoming = [
                link for link in links if link.get("input-node-id") == ns[self.name + suffix]["id"]
            ]
            if not incoming or any(
                link.get("output-node-id") != target
                or link.get("state") not in {"active", "paused"}
                for link in incoming
            ):
                raise MicrophoneUnavailable("AEC input/reference links unavailable or misrouted")
            if suffix == "-reference" and any(
                str(ports.get(link["output-port-id"], {}).get("port.monitor", "false")).lower()
                not in {"true", "1"}
                for link in incoming
            ):
                raise MicrophoneUnavailable("AEC reference is not a speaker monitor")
        if require_reader and self.name + "-reader" not in ns:
            raise MicrophoneUnavailable("Microphone reader node not ready")
        if self.name + "-reader" in ns:
            incoming = [
                link
                for link in links
                if link.get("input-node-id") == ns[self.name + "-reader"]["id"]
            ]
            if not incoming:
                raise MicrophoneUnavailable("Microphone reader has no links yet")
            if any(link.get("output-node-id") != ns[self.name]["id"] for link in incoming):
                raise MicrophoneUnavailable(
                    "Microphone reader linked to an unsafe source; capture rejected"
                )
            if any(link.get("state") not in {"active", "paused"} for link in incoming):
                raise MicrophoneUnavailable("Microphone reader links still negotiating")
        self.targets = targets

    async def start(self):
        before = nodes(await graph())
        if any(n not in before for n in (self.selection.microphone.name, self.selection.reference)):
            raise MicrophoneUnavailable("Physical Pulse devices not found in native PipeWire graph")
        try:
            self.process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "interview_helper.aec_owner",
                self.arguments(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            for _ in range(12):
                if self.process.returncode is not None:
                    raise MicrophoneUnavailable("Native PipeWire/WebRTC AEC could not start")
                try:
                    await self.check()
                    return Monitor(self.name, "Microphone", "")
                except MicrophoneUnavailable:
                    await asyncio.sleep(0.2)
            raise MicrophoneUnavailable(
                "AEC links not ready; check PipeWire/WebRTC and session manager"
            )
        except BaseException:
            await self.stop()
            raise

    async def check(self, require_reader=False):
        if self.process and self.process.returncode is not None:
            raise MicrophoneUnavailable("AEC process stopped")
        self.verify(await graph(), require_reader)

    async def stop(self):
        await stop_process(self.process)


SAFE_ERRORS = (MicrophoneUnavailable, AudioDiscoveryError, OSError, ValueError, TimeoutError)


class MicrophoneWorker:
    """Optional lifecycle with one outage interval and independent ASR recovery."""

    def __init__(self, session):
        self.session = session
        self.current = self.selection = self.aec = self.capture = self.worker = None
        self.valid = self.closed = False
        self.task = self.cleanup_task = None
        self.retry_at = 0
        self.attempts = 0
        self.outage = None
        self.diagnostics = deque(maxlen=20)
        self.last_diagnostic = 0
        self.switch_candidate = None

    def state(self, state, **data):
        self.session.microphone_state.update(state=state, **data)

    def record(self, event):
        if self.session.store and not self.session.store.closed:
            from .storage import now

            self.session.save(
                {
                    "source_kind": "microphone",
                    "time": now(),
                    "at": max(0, time.monotonic() - self.session.started),
                    **event,
                }
            )

    def gap(self, reason, kind="capture"):
        self.state("unavailable", reason=reason)
        if not self.outage:
            self.outage = {
                "id": uuid.uuid4().hex,
                "kind": kind,
                "reason": reason,
                "started_at": max(0, time.monotonic() - self.session.started),
            }
            self.record({"type": "outage", "phase": "start", **self.outage})
        self.session.microphone_state["outage"] = dict(self.outage)
        stamp = time.monotonic()
        if (
            not self.diagnostics
            or self.diagnostics[-1]["reason"] != reason
            or stamp - self.last_diagnostic >= 60
        ):
            self.diagnostics.append(
                {
                    "at": max(0, stamp - self.session.started),
                    "reason": reason,
                    "attempts": self.attempts,
                }
            )
            if stamp - self.last_diagnostic >= 60:
                self.record({"type": "microphone_diagnostic", **self.diagnostics[-1]})
                self.last_diagnostic = stamp
        self.session.microphone_state["diagnostics"] = list(self.diagnostics)

    def recovered(self, reason):
        if self.outage:
            self.record({"type": "outage", **self.outage, "phase": "recovered", "reason": reason})
            self.outage = None
            self.session.microphone_state.pop("outage", None)
        self.attempts = 0
        self.state("listening", reason=reason, attempts=0, retry_seconds=0)

    def capture_status(self, source, state, message):
        if state == "gap":
            self.gap(message, "recognition")
        elif state in {"failed", "disconnected"}:
            self.valid = False
            self.gap(message)

    async def emit(self, tokens, provisional, final):
        if not self.valid:
            return
        if not self.selection.same_devices(await discover_input(self.current)):
            raise MicrophoneUnavailable(
                "Physical microphone or speaker reference changed before publication"
            )
        await self.aec.check(require_reader=True)
        if not self.valid:
            return
        self.session.microphone_state["provisional"] = provisional
        if tokens:
            self.session.ingest(
                self.current,
                "Microphone",
                "".join(t.text for t in tokens),
                tokens[0].start,
                tokens[-1].end,
                final,
                source_kind="microphone",
            )
            self.session.microphone_state["last_segment_at"] = (
                time.monotonic() - self.session.started
            )

    def status(self, state, data):
        if not self.valid and state in {"ready", "listening"}:
            # A paused worker may finish while topology is being checked. It
            # cannot establish recovery or publish speech from that interval.
            return
        if state == "gap":
            self.session.microphone_state.pop("provisional", None)
            self.gap(data.get("error", "Microphone continuity reset"), "recognition")
            return
        if state == "failed":
            self.gap(data.get("error", "Microphone ASR failed"), "recognition")
            return
        if state == "ready":
            self.recovered("Recognition resumed after verified capture")
        elif state == "listening" and self.outage and self.outage["kind"] == "capture":
            self.recovered("Verified capture resumed; recognition awaiting speech")
        # Listening samples do not erase deferral/quarantine or an unresolved gap.
        if state == "listening" and self.session.microphone_state.get("state") in {
            "deferred",
            "quarantined",
            "unavailable",
        }:
            self.session.microphone_state.update(data)
        else:
            self.state(state, **data)
        if self.capture:
            self.session.microphone_state["dropped_seconds"] = self.capture.dropped_seconds

    async def settle_reader(self):
        deadline = time.monotonic() + 3
        while True:
            if self.capture.stopping:
                raise MicrophoneUnavailable("Microphone reader exited during startup")
            try:
                await self.aec.check(require_reader=True)
                return
            except MicrophoneUnavailable:
                if time.monotonic() >= deadline:
                    raise
                await asyncio.sleep(0.1)

    async def cleanup(self, flush=False):
        if not flush:
            self.valid = False
        if self.capture:
            await self.capture.stop()
        if self.worker:
            if flush and not self.worker.done():
                try:
                    await asyncio.wait_for(asyncio.shield(self.worker), 2)
                except TimeoutError:
                    self.gap("Microphone final flush timed out; tail omitted", "recognition")
                except Exception:
                    self.gap("Microphone final flush failed; tail omitted", "recognition")
            if not self.worker.done():
                self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
        self.valid = False
        if self.aec:
            await self.aec.stop()
        self.session.microphone_state.pop("provisional", None)
        self.capture = self.worker = self.aec = self.selection = None

    async def run(self):
        from .audio import Capture

        try:
            while not self.closed and self.session.state == "recording":
                try:
                    if time.monotonic() < self.retry_at:
                        await asyncio.sleep(0.5)
                        continue
                    selection = await discover_input(self.current)
                    if self.selection and not self.selection.same_devices(selection):
                        # Suspend publication immediately, but require two stable
                        # observations before rebuilding on a routing change.
                        self.valid = False
                        self.gap("Physical microphone or speaker reference changed")
                        if not selection.same_devices(self.switch_candidate):
                            self.switch_candidate = selection
                            if self.capture:
                                self.capture.discard_buffer()
                            await asyncio.sleep(0.5)
                            continue
                        await self.cleanup()
                    self.switch_candidate = None
                    if not self.selection:
                        self.current, self.selection = selection.microphone.name, selection
                        self.state(
                            "connecting",
                            name=self.current,
                            label=selection.microphone.label,
                            reference=selection.reference,
                            reason="Preparing verified echo cancellation",
                        )
                        self.aec = EchoCancel(selection)
                        monitor = await self.aec.start()
                        self.capture = Capture(
                            monitor, self.capture_status, self.session.started, microphone=True
                        )
                        await self.capture.start()
                        await self.settle_reader()
                        # Do not transcribe frames captured before exclusive
                        # cleaned-source links were verified.
                        self.capture.discard_buffer()
                        self.state("listening", reason="Verified capture; awaiting speech")
                    await self.aec.check(require_reader=True)
                    if self.capture.stopping:
                        raise MicrophoneUnavailable("Microphone capture stopped")
                    self.valid = True
                    if self.worker and self.worker.done():
                        exc = None if self.worker.cancelled() else self.worker.exception()
                        self.gap(
                            "Microphone recognition stopped: "
                            + (type(exc).__name__ if exc else "stream ended"),
                            "recognition",
                        )
                        self.worker = None
                        self.capture.discard_buffer()
                        self.retry_at = time.monotonic() + 2
                        continue
                    if not self.worker:
                        if self.session.recognizer.microphone_overloaded:
                            self.state(
                                "quarantined", reason="Previous native ASR operation still running"
                            )
                        else:
                            self.worker = asyncio.create_task(
                                self.session.recognizer.run_source(
                                    self.capture, self.emit, self.status
                                )
                            )
                except Exception as exc:
                    reason = (
                        str(exc)
                        if isinstance(exc, SAFE_ERRORS)
                        else "Microphone processing failed: " + type(exc).__name__
                    )
                    self.attempts += 1
                    self.gap(reason)
                    await self.cleanup()
                    self.retry_at = time.monotonic() + min(30, 2 ** min(self.attempts, 5))
                    self.session.microphone_state.update(
                        retry_seconds=round(self.retry_at - time.monotonic()),
                        attempts=self.attempts,
                    )
                await asyncio.sleep(0.5)
        finally:
            self.cleanup_task = asyncio.create_task(
                self.cleanup(flush=self.closed or self.session.state == "stopping")
            )
            await asyncio.shield(self.cleanup_task)
            if self.outage:
                self.record(
                    {
                        "type": "outage",
                        **self.outage,
                        "phase": "unresolved",
                        "reason": "Session ended before recovery",
                    }
                )
            if self.closed or self.session.state == "stopping":
                self.state("stopped")

    async def stop(self):
        self.closed = True
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.cleanup_task:
            await self.cleanup_task
        self.state("stopped")
