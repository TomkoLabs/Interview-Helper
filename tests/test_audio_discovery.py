"""Sanitized pactl 17 / PipeWire 1.4.2 attachment; no hardware capture.

Fixture retains all 18 module names/arguments and 57 short-output physical lines.
Device names/descriptions are generic; hardware serials, host/user, cookie, addresses and
unrelated properties are omitted. Pulse indices and distinct PipeWire object IDs,
monitor fields, class and stream properties retain the observed relationships.
"""

import asyncio
import copy
import json
from pathlib import Path

import pytest

from interview_helper import audio
from interview_helper.config import Config
from interview_helper.session import Session
from interview_helper.storage import SessionStore


@pytest.fixture
def topology():
    return json.loads((Path(__file__).parent / "fixtures/pipewire_pactl17.json").read_text())


def test_multiline_module_records_match_json_not_physical_lines(topology):
    assert len(topology["modules"]) == 18
    assert len(topology["modules_short"].splitlines()) == 57
    modules = audio.parse_short_modules(topology["modules_short"], topology["modules"])
    assert len(modules) == 18
    assert [m["index"] for m in modules[-4:]] == list(range(536870912, 536870916))
    assert [m["argument"] for m in modules] == [m["argument"] for m in topology["modules"]]
    # PipeWire metadata is not the Pulse module identity, even if it happens to agree.
    for m in topology["modules"]:
        m["properties"]["object.id"] = "99999"
        m["properties"]["object.serial"] = "88888"
    assert audio.parse_short_modules(topology["modules_short"], topology["modules"]) == modules


@pytest.mark.parametrize(
    "damage", ["stray", "trailing", "missing", "name", "argument", "duplicate", "conflict", "empty"]
)
def test_inconsistent_module_snapshots_remain_errors(topology, damage):
    text, expected = topology["modules_short"], topology["modules"]
    if damage == "stray":
        text = "unexpected line\n" + text
    elif damage == "trailing":
        text += "unexpected line\n"
    elif damage == "missing":
        text = text[: text.rfind("536870915")]
    elif damage == "name":
        text = text.replace("module-always-sink", "module-different")
    elif damage == "argument":
        text = text.replace("rt.prio       = 88", "rt.prio       = 99")
    elif damage == "duplicate":
        text = text.replace("536870915\t", "536870914\t")
    elif damage == "conflict":
        expected[0]["index"] = 100
    else:
        text = ""
    with pytest.raises(ValueError):
        audio.parse_short_modules(text, expected)


def install_pactl_fixture(monkeypatch, topology, broken=None):
    calls = []

    class Process:
        returncode = 0

        def __init__(self, output):
            self.output = output

        async def communicate(self):
            return self.output, b""

    async def spawn(*args, **kwargs):
        calls.append(args)
        if args == ("pactl", "list", "short", "modules"):
            return Process(topology["modules_short"].encode())
        assert args[:3] == ("pactl", "--format=json", "list")
        # Stream lists were not in the attachment; empty streams are a test condition.
        return Process(
            b"invalid" if args[-1] == broken else json.dumps(topology.get(args[-1], [])).encode()
        )

    monkeypatch.setattr(audio.asyncio, "create_subprocess_exec", spawn)
    return calls


@pytest.mark.asyncio
async def test_pipewire_discovery_excludes_both_physical_inputs(monkeypatch, topology):
    assert all("monitor_of_sink" not in s for s in topology["sources"])
    calls = install_pactl_fixture(monkeypatch, topology)
    monitors, warnings = await audio.discover(include=("*",))
    assert [(m.name, m.sink) for m in monitors] == [
        ("analog.monitor", "analog"),
        ("hdmi.monitor", "hdmi"),
    ]
    assert not warnings
    assert len(calls) == 6 and ("pactl", "list", "short", "modules") in calls
    # Renaming an input to look like a monitor still does not admit it.
    topology["sources"][0]["name"] = "microphone.monitor"
    monitors, _ = await audio.discover(include=("*",))
    assert {m.name for m in monitors} == {"analog.monitor", "hdmi.monitor"}


def test_native_spa_arguments_are_not_parsed_as_shell(topology):
    modules = audio.parse_short_modules(topology["modules_short"], topology["modules"])
    modules[0]["argument"] = "{ # native comment containing an unmatched ' quote\n}"
    monitors, _ = audio.select_monitors(topology["sinks"], topology["sources"], modules, [], [])
    assert len(monitors) == 2
    modules.append({"index": 123, "name": "module-loopback", "argument": "source='"})
    with pytest.raises(ValueError):
        audio.select_monitors(topology["sinks"], topology["sources"], modules, [], [])


@pytest.mark.parametrize("numeric_sink_monitor", [False, True])
def test_forwarding_numeric_source_identity_without_monitor_of_sink(topology, numeric_sink_monitor):
    sinks, sources = topology["sinks"], topology["sources"]
    if numeric_sink_monitor:
        for sink in sinks:
            sink["monitor_source"] = next(
                s["index"] for s in sources if s["name"] == sink["monitor_source"]
            )
    modules = [{"index": 536870916, "name": "module-loopback", "argument": "source=61 sink=111"}]
    monitors, warnings = audio.select_monitors(sinks, sources, modules, [], [])
    assert [m.name for m in monitors] == ["analog.monitor"] and warnings
    monitors, _ = audio.select_monitors(
        sinks, sources, modules, [{"sink": 111, "owner_module": 77}], []
    )
    assert [m.name for m in monitors] == ["hdmi.monitor"]
    # Object ID 45 is NOT Pulse source index 61: no inferred forwarding edge.
    modules[0]["argument"] = "source=45 sink=111"
    monitors, warnings = audio.select_monitors(sinks, sources, modules, [], [])
    assert len(monitors) == 2 and not warnings


@pytest.mark.asyncio
async def test_indexed_json_modules_validate_identity_without_short_fallback(monkeypatch, topology):
    topology["modules"] = audio.parse_short_modules(topology["modules_short"], topology["modules"])
    calls = install_pactl_fixture(monkeypatch, topology)
    assert len(await audio.pactl("modules")) == 18 and len(calls) == 1
    topology["modules"][1]["index"] = topology["modules"][0]["index"]
    with pytest.raises(audio.AudioDiscoveryError, match="pactl modules: Invalid or duplicate"):
        await audio.pactl("modules")


@pytest.mark.asyncio
async def test_stage_errors_remain_visible_and_saving_continues(monkeypatch, topology, tmp_path):
    install_pactl_fixture(monkeypatch, topology, broken="sources")
    with pytest.raises(audio.AudioDiscoveryError, match="pactl sources: invalid JSON"):
        await audio.discover()
    broken = copy.deepcopy(topology)
    broken["modules_short"] += "unexpected\n"
    install_pactl_fixture(monkeypatch, broken)
    with pytest.raises(audio.AudioDiscoveryError, match="pactl modules: Unexpected trailing"):
        await audio.discover()
    session = Session(Config.load(tmp_path / "config.local.toml"))
    session.start(replay=True)
    session.capture_task = asyncio.create_task(session._capture_loop())
    try:
        for _ in range(20):
            await asyncio.sleep(0)
            if "pactl modules" in session.status["capture"]:
                break
        assert "pactl modules" in session.view()["status"]["capture"]
        assert session.state == "recording"
        session.ingest("fixture", "Playback", "Finalized speech remains saved.", 0, 1, True)
    finally:
        await session.shutdown()
    saved = SessionStore.inspect(session.config.data_dir, session.store.id)
    assert len(saved["events"]) == 1 and saved["metadata"]["status"] == "ended"
