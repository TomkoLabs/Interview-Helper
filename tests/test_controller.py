import asyncio
import json
import pytest
from interview_helper.config import Config, Endpoint
from interview_helper.controller import Controller
from interview_helper.gateway import Outcome


class Fake:
    def __init__(self):
        self.calls = []
        self.release = asyncio.Event()
        self.active = 0
        self.peak = 0

    async def race(self, messages, request_id, on_line, strategy, current=None):
        self.active += 1
        self.peak = max(self.peak, self.active)
        data = json.loads(messages[-1]["content"])
        self.calls.append(data)
        await self.release.wait()
        header = {"action": "NEW", "question": "Explain a counter", "developing": False}
        await on_line("test", header, ["A useful answer."])
        self.active -= 1
        return Outcome("test", header, ["A useful answer."], 0.1, 0.2)

    async def close(self):
        pass


async def setup(tmp_path):
    config = Config.load(tmp_path / "config.local.toml")
    gateway = Fake()
    published = []
    saved = []
    statuses = []

    async def publish(kind, data):
        published.append((kind, data))

    controller = Controller(config, gateway, publish, saved.append, statuses.append)
    return controller, gateway, published, saved, statuses


def event(revision, text):
    return {"revision": revision, "source_name": "speaker", "text": text}


@pytest.mark.asyncio
async def test_pending_latest_stale_and_no_fifo(tmp_path):
    c, g, p, s, _ = await setup(tmp_path)
    c.ingest(event(1, "Explain a counter"))
    c.submit()
    await asyncio.sleep(0.01)
    for i in range(2, 30):
        c.ingest(event(i, "Actually use multiple processes " + str(i)))
        c.submit()
    assert c.pending.revision == 29
    g.release.set()
    await asyncio.sleep(0.05)
    assert len(g.calls) == 2 and g.peak == 1
    assert len(s) == 1 and s[0]["revision"] == 29
    assert any(kind == "discard" for kind, _ in p)
    await c.finish()


@pytest.mark.asyncio
async def test_unchanged_not_resent(tmp_path):
    c, g, _, s, _ = await setup(tmp_path)
    g.release.set()
    c.ingest(event(1, "Explain a counter"))
    c.submit()
    await asyncio.sleep(0.05)
    c.submit()
    await asyncio.sleep(0.05)
    assert len(g.calls) == 1
    await c.finish()


@pytest.mark.asyncio
async def test_context_bounds_preserve_scenario(tmp_path):
    c, g, _, _, status = await setup(tmp_path)
    for i in range(100):
        c.ingest(event(i + 1, ("without locks " + str(i) + " ") * 20))
    assert sum(len(r[2]) for r in c.recent) <= c.config.context_chars
    assert c.context_overflow and len(c.scenario) <= c.config.scenario_chars
    c.submit()
    assert c.pending is None
    assert "context limit" in status[-1]
    await c.finish()


@pytest.mark.asyncio
async def test_append_does_not_starve_answer(tmp_path):
    c, g, _, saved, _ = await setup(tmp_path)
    c.ingest(event(1, "Explain a counter"))
    c.submit()
    await asyncio.sleep(0.01)
    c.ingest(event(2, "that counts requests"))
    g.release.set()
    await asyncio.sleep(0.05)
    assert len(saved) == 1
    await c.finish()


def test_configuration_rejects_same_host_and_routing_overrides(tmp_path):
    c = Config.load(tmp_path / "missing")
    c.strategy = "race"
    c.endpoints = [
        Endpoint("a", "https://example.invalid/v1", "a", host_id="same"),
        Endpoint("b", "https://example.invalid/v1", "b", host_id="same"),
    ]
    with pytest.raises(ValueError):
        c.validate()
    with pytest.raises(ValueError):
        Endpoint(
            "a", "https://example.invalid/v1", "a", parameters={"api_base": "https://other.invalid"}
        )


@pytest.mark.asyncio
async def test_wait_prefix_retained_for_long_scenario(tmp_path):
    c, g, _, _, _ = await setup(tmp_path)

    class Decisions:
        count = 0

        async def race(self, messages, request_id, on_line, strategy, current=None):
            self.count += 1
            if self.count == 1:
                return Outcome("test", {"action": "WAIT"}, [], None, 0.01)
            return Outcome(
                "test",
                {"action": "NEW", "question": "Design it", "developing": False},
                ["Answer"],
                0.01,
                0.02,
            )

        async def close(self):
            pass

    c.gateway = Decisions()
    c.ingest(event(1, "A scenario with a mandatory durable key and no locks."))
    c.submit()
    await asyncio.sleep(0.03)
    c.ingest(event(2, "Walk me through the design."))
    c.submit()
    await asyncio.sleep(0.03)
    assert "mandatory durable key and no locks" in c.scenario
    await c.finish()


@pytest.mark.asyncio
async def test_hint_save_error_remains_recoverable(tmp_path):
    c, g, p, _, _ = await setup(tmp_path)
    g.release.set()
    c.save = lambda _: (_ for _ in ()).throw(OSError("full"))
    c.ingest(event(1, "Explain a counter"))
    c.submit()
    await asyncio.sleep(0.03)
    assert not c.cards and any(k == "discard" for k, _ in p)
    await c.finish()


@pytest.mark.asyncio
async def test_new_revisions_even_with_identical_wording_are_reviewed(tmp_path):
    c, g, _, saved, _ = await setup(tmp_path)
    g.release.set()
    for revision, text in enumerate(
        [
            "Explain a Python tuple.",
            "Explain a Python tuple!",
            "Explain C++ RAII.",
            "Explain a Python tuple.",
        ],
        1,
    ):
        c.ingest(event(revision, text))
        c.submit()
        await c.runner
    assert len(g.calls) == 4 and len(saved) == 4 and len(c.cards) == 4
    await c.finish()
