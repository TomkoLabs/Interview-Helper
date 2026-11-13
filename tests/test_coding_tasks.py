"""Synthetic coding-task lifecycle; fixtures do not establish model quality."""

from test_live_review import setup, ingest, review, answer


from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import httpx
import pytest
from interview_helper.config import Config, Endpoint
from interview_helper.gateway import Gateway
from interview_helper.protocol import Parser, ProtocolError
from interview_helper.session import Session
from interview_helper.storage import SessionStore

FIXTURES = Path(__file__).with_name("fixtures")
STAGES = json.loads((FIXTURES / "coding_task_0.1.13.json").read_text())
JAVA = (FIXTURES / "StudentDirectory.java").read_text()


async def test_prose_followup_preserves_reference_code(tmp_path):
    c, g, _, saved, _, _ = await setup(tmp_path)
    try:
        ingest(c, 1, "Implement a student directory with add and update.")
        g.next = answer(text="TL;DR: Key students by ID.")
        g.next.lines.append("```java snippet\nMap<Long, Student> byId = new HashMap<>();\n```")
        await review(c)
        ingest(c, 2, "Several students may have the same name.")
        g.next = answer("UPDATE", text="TL;DR: Keep different IDs for duplicate names.")
        await review(c)
        assert "Map<Long, Student>" in c.cards[-1]["answer"]
        assert "Map<Long, Student>" in saved[-1]["answer"]
    finally:
        await c.finish()


async def test_reference_key_points_stay_after_code_across_followups(tmp_path):
    c, g, _, _, _, _ = await coding_setup(tmp_path)
    try:
        before = c.cards[0]
        assert before["answer"].index("```java") < before["answer"].index("Expected exact lookup")
        assert "Expected exact lookup" not in before["guidance"]
        ingest(c, 2, "Explain duplicate name identity.")
        g.next = answer("UPDATE")
        g.next.header["solution"] = "preserve"
        await review(c)
        assert c.cards[0]["reference"]["notes"] == before["reference"]["notes"]
        assert c.cards[0]["answer"].index("```java") < c.cards[0]["answer"].index(
            "Expected exact lookup"
        )
    finally:
        await c.finish()


def records(stage, revision, segment):
    action = stage["action"]
    if action == "IGNORE":
        return [{"action": action}, {"done": True}]
    header = {
        "action": action,
        "question": stage["question"],
        "developing": False,
        "segments": [segment],
    }
    if action == "NEW":
        header["start_revision"] = revision
    for field in ("solution", "reason"):
        if field in stage:
            header[field] = stage[field]
    if "solution" in stage:
        header["task"] = "coding"
    result = [header, {"text": stage["text"]}]
    if stage.get("code"):
        code = JAVA if stage["code"] == "concurrent" else JAVA.replace("synchronized ", "")
        result.append({"code": code, "language": "java", "scope": "complete"})
        result.append(
            {
                "text": "- Expected exact lookup O(name length + matches); prefix O(prefix length + log distinct first names + matching names/students), plus string comparison cost. Names are stored normalized; empty prefix returns all. Update is atomic for ordinary validated inputs, not VM failure."
            }
        )
    if stage.get("facts"):
        result.append({"requirements": [{**f, "segments": [segment]} for f in stage["facts"]]})
    return result + [{"done": True}]


def wire(items):
    return "".join(json.dumps(x) + "\n" for x in items)


def sse(items, incomplete=False):
    # Small deltas exercise real record assembly, not detached card construction.
    output = wire(items)
    events = [
        {"type": "response.output_text.delta", "delta": output[i : i + 97]}
        for i in range(0, len(output), 97)
    ]
    events.append(
        {
            "type": "response.incomplete" if incomplete else "response.completed",
            "response": {
                "status": "incomplete" if incomplete else "completed",
                "incomplete_details": {"reason": "max_output_tokens"} if incomplete else None,
                "model": "gpt-6.1-sol",
                "service_tier": "ultrafast",
                "usage": {"input_tokens": 100, "output_tokens": 100},
            },
        }
    )
    return "".join("data: " + json.dumps(e) + "\n\n" for e in events).encode()


async def test_progressive_real_session_gateway_protocol_and_archive(tmp_path, monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(
        "interview_helper.controller.time", SimpleNamespace(monotonic=lambda: clock[0])
    )
    cfg = Config.load(tmp_path / "missing.toml")
    cfg.endpoints = [
        Endpoint(
            "fixture",
            "https://api.openai.com/v1",
            "gpt-6.1-sol",
            api_key="fixture",
            backend="openai_api",
            compact=True,
            parameters={
                "reasoning_effort": "low",
                "service_tier": "ultrafast",
                "max_output_tokens": 1024,
            },
        )
    ]
    session = Session(cfg)
    session.start(replay=True)
    c = session.controller
    c.stopping = True
    await c.tick_task
    c.stopping = False
    gateway = c.gateway
    await gateway.client.aclose()
    payloads = []
    response = [b""]

    def serve(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(
            200, content=response[0], headers={"Content-Type": "text/event-stream"}
        )

    gateway.client = httpx.AsyncClient(transport=httpx.MockTransport(serve))
    try:
        for rev, stage in enumerate(STAGES, 1):
            clock[0] = 10 + stage["at"]
            session.ingest(
                "fixture", "Synthetic playback", stage["speech"], stage["at"], stage["at"] + 1
            )
            segment = session.transcript[-1]["segment_id"]
            response[0] = sse(records(stage, rev, segment))
            c.submit()
            await c.runner
            assert c.reviewed == rev
            assert session.status["save"] == "saved"
            if rev == 1:
                parent = c.cards[0]["id"]
                assert c.cards[0]["reference"]["status"] == "current"
            if rev <= 7:
                assert len(c.cards) == 1 and c.cards[0]["id"] == parent
                assert c.cards[0]["question"] == "Implement a student directory"
                assert not c.cards[0]["developing"]
                assert "StudentDirectory" in c.cards[0]["reference"]["code"]
            if rev == 3:
                assert c.cards[0]["reference"]["status"] == "needs_revision"
            if rev >= 4:
                assert "synchronized" in c.cards[0]["reference"]["code"]
                assert c.cards[0]["reference"]["status"] == "current"
            if rev == 7:
                packet = json.loads(payloads[-1]["input"][-1]["content"])
                assert packet["CONVERSATION"][0]["text"] == STAGES[0]["speech"]
                assert packet["ACTIVE_QUESTION"]["reference"]["code"].startswith("```java complete")
                assert len(c.recent) == 1  # Forty-four virtual minutes, original speech retained.
                assert not any(e["text"] == "Okay." for e in c.events)
                notes = c.cards[0]["requirements"]
                assert any(f["status"] == "superseded" and f["kind"] == "assumption" for f in notes)
                assert all(f["evidence_revisions"] for f in notes)
        assert len(c.cards) == 2 and c.cards[1]["id"] != parent
        assert payloads[0]["max_output_tokens"] == 2048
        assert payloads[-1]["max_output_tokens"] == 1024
        assert all(
            p["model"] == "gpt-6.1-sol"
            and p["service_tier"] == "ultrafast"
            and p["reasoning"] == {"effort": "low"}
            for p in payloads
        )
        assert len(c.scenario) < cfg.scenario_chars
        data = SessionStore.inspect(cfg.data_dir, session.store.id)
        assert len([e for e in data["events"] if e["type"] == "transcript"]) == len(STAGES)
        latest = {h["id"]: h for h in data["hints"] if h["type"] == "hint"}
        assert latest[parent]["reference"]["status"] == "current"
        assert "synchronized" in latest[parent]["reference"]["code"]
    finally:
        await session.shutdown()


async def coding_setup(tmp_path):
    c, g, pub, saved, logs, status = await setup(tmp_path)
    ingest(c, 1, STAGES[0]["speech"], "s1")
    from interview_helper.gateway import Outcome

    parser = Parser()
    parser.feed(wire(records(STAGES[0], 1, "s1")))
    parser.finish()
    g.next = Outcome("fixture", parser.header, parser.lines)
    await review(c)
    return c, g, pub, saved, logs, status


async def test_failed_or_truncated_revision_keeps_previous_code_and_saving(tmp_path):
    from interview_helper.gateway import Outcome

    c, g, _, saved, _, _ = await coding_setup(tmp_path)
    original = c.cards[0]["reference"]["code"]
    try:
        ingest(c, 2, "Actually require concurrent callers.", "s2")
        assert c.cards[0]["reference"]["status"] == "unreviewed"
        g.next = Outcome("fixture", error="Responses incomplete: max_output_tokens")
        await review(c)
        assert c.reviewed == 1
        assert c.cards[0]["reference"]["code"] == original
        assert c.cards[0]["review_status"] == "failed"
        assert saved[-1]["reference"]["status"] == "unreviewed"
        ingest(c, 3, "Also keep all name indexes consistent.", "s3")
        assert c.revision == 3 and "concurrent" in c.scenario
    finally:
        c.attempted = c.revision
        await c.finish()


@pytest.mark.parametrize("effect", ["invalidate", "clear", "replace", "preserve"])
async def test_explicit_reference_semantics(tmp_path, effect):
    c, g, _, _, _, _ = await coding_setup(tmp_path)
    old = c.cards[0]["reference"]["code"]
    try:
        ingest(c, 2, "Consider concurrent callers.", "s2")
        g.next = answer("UPDATE", text="TL;DR: Coordinate all index mutations.")
        g.next.header.update(task="coding", solution=effect, reason="New concurrency requirements.")
        if effect == "replace":
            g.next.lines.append("```java snippet\nsynchronized void update() {}\n```")
        await review(c)
        ref = c.cards[0]["reference"]
        if effect == "clear":
            assert ref is None
        elif effect == "replace":
            assert ref["code"] != old and ref["status"] == "current"
        else:
            assert ref["code"] == old
            assert ref["status"] == ("needs_revision" if effect == "invalidate" else "current")
    finally:
        await c.finish()


async def test_invalidated_code_cannot_be_revalidated_by_preserve_alone(tmp_path):
    c, g, _, _, _, _ = await coding_setup(tmp_path)
    try:
        for rev, effect in [(2, "invalidate"), (3, "preserve")]:
            ingest(c, rev, "Concurrent callers matter.")
            g.next = answer("UPDATE")
            g.next.header.update(solution=effect, reason="Unsynchronized code is unsafe.")
            await review(c)
        assert c.cards[0]["reference"]["status"] == "needs_revision"
    finally:
        await c.finish()


async def test_stale_code_and_requirements_do_not_replace_latest_state(tmp_path):
    c, g, _, _, logs, _ = await coding_setup(tmp_path)
    old = c.cards[0]["reference"]["code"]
    try:
        g.entered.clear()
        g.release.clear()
        ingest(c, 2, "Explain IDs.")
        g.next = answer("UPDATE")
        g.next.header.update(solution="replace", task="coding")
        g.next.lines.append("```java snippet\nlong wrong = 1;\n```")
        c.submit()
        await g.entered.wait()
        ingest(c, 3, "Actually updates must be thread safe.")
        g.release.set()
        await c.runner
        assert logs[-1]["stale"]
        assert c.cards[0]["reference"]["code"] == old
        assert c.cards[0]["reference"]["status"] == "unreviewed"
        c.attempted = c.revision
    finally:
        await c.finish()


@pytest.mark.parametrize(
    "patch",
    [
        {"solution": []},
        {"_requirements": []},
    ],
)
def test_invalid_task_headers_rejected(patch):
    with pytest.raises(ProtocolError):
        Parser().feed(wire([{**records(STAGES[0], 1, "s1")[0], **patch}]))


async def test_forged_requirement_evidence_and_supersession_reject_entire_update(tmp_path):
    c, g, _, _, logs, _ = await coding_setup(tmp_path)
    try:
        for revision, fact in [
            (2, {"segments": ["absent"]}),
            (3, {"segments": ["s1"], "supersedes": ["invented"]}),
        ]:
            ingest(c, revision, "Duplicate names are allowed.")
            g.next = answer("UPDATE")
            g.next.header["_requirements"] = [
                {"text": "Preserve duplicate records.", "kind": "requirement", **fact}
            ]
            previous = deepcopy(c.cards[0]["requirements"])
            await review(c)
            assert logs[-1]["outcome"] == "rejected"
            assert c.cards[0]["requirements"] == previous and c.reviewed == 1
    finally:
        await c.finish()


def test_partial_code_or_protocol_cannot_be_complete():
    items = records(STAGES[0], 1, "s1")
    p = Parser()
    p.feed(wire(items[:-1]))
    with pytest.raises(ProtocolError, match="Truncated"):
        p.finish()
    p = Parser()
    p.feed(wire(items[:2]) + json.dumps(items[2])[:150])
    with pytest.raises(ProtocolError):
        p.finish()
    assert not any(line.startswith("```") for line in p.lines)


async def test_capacity_and_subscription_contract(tmp_path):
    cfg = Config.load(tmp_path / "missing")
    c, _, _, _, _, _ = await setup(tmp_path)
    try:
        ingest(c, 1, STAGES[0]["speech"])
        messages = c.messages(c.snapshot())
        for backend, params in [
            ("openai_api", {"max_output_tokens": 1024}),
            ("openai_api", {"max_output_tokens": 512}),
            ("chatgpt", {}),
        ]:
            ep = Endpoint(
                "fixture",
                "https://api.openai.com/v1",
                "gpt-6.1-sol",
                backend=backend,
                compact=True,
                oauth_file=str(tmp_path / "nonexistent"),
                parameters=params,
            )
            gateway = Gateway([ep])
            payload = gateway.payload(ep, messages)
            assert payload.get("max_output_tokens") == (
                2048 if params.get("max_output_tokens") == 1024 else params.get("max_output_tokens")
            )
            await gateway.close()
        cfg.coding_output_tokens = 9000
        with pytest.raises(ValueError):
            cfg.validate()
    finally:
        c.closed = True
        await c.finish()


def test_java_reference_duplicates_updates_and_concurrent_operations(tmp_path):
    if not shutil.which("javac"):
        pytest.skip("JDK unavailable: no compilation claim")
    shutil.copy2(FIXTURES / "StudentDirectory.java", tmp_path)
    (tmp_path / "Verify.java").write_text("""
import java.util.*;
import java.util.concurrent.*;
public class Verify {
  public static void main(String[] args) throws Exception {
    StudentDirectory d = new StudentDirectory();
    for (int i=0;i<10;i++) d.add("Ada", "Lovelace");
    if (d.exact(" ADA  LOVELACE ").size()!=10) throw new AssertionError("duplicates");
    var first = d.exact("ada lovelace").get(0);
    d.update(first.id(), "Grace", "Hopper");
    if (d.prefix("ad").size()!=9 || d.prefix("GR").size()!=1 || d.exact("ada lovelace").size()!=9) throw new AssertionError("old indexes");
    try { d.update(first.id(), null, "bad"); throw new AssertionError("null accepted"); }
    catch (NullPointerException expected) {}
    if (d.exact("grace hopper").get(0).id()!=first.id()) throw new AssertionError("invalid update mutated");
    var pool=Executors.newFixedThreadPool(8);
    List<Callable<Void>> tasks=new ArrayList<>();
    for(int t=0;t<8;t++) tasks.add(()->{for(int i=0;i<200;i++){var s=d.add("Test", "Same"); d.update(s.id(), "Renamed", "Same"); for(var hit:d.prefix("ren")) if(hit==null || !hit.first().equals("renamed")) throw new AssertionError("partial index");} return null;});
    for(var result:pool.invokeAll(tasks)) result.get();
    pool.shutdown();
    if(d.prefix("ren").size()!=1600 || !d.exact("test same").isEmpty() || d.prefix("").size()!=1610) throw new AssertionError("counts");
    Set<Long> ids=new HashSet<>(); for(var s:d.prefix("")) ids.add(s.id());
    if(ids.size()!=1610) throw new AssertionError("ID uniqueness");
  }
}
""")
    subprocess.run(
        ["javac", "--release", "17", "StudentDirectory.java", "Verify.java"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["java", "-cp", str(tmp_path), "Verify"], check=True, capture_output=True, timeout=30
    )


async def test_provider_incomplete_never_publishes_code_and_keeps_transcription(tmp_path):
    cfg = Config.load(tmp_path / "missing")
    cfg.endpoints = [
        Endpoint(
            "fixture",
            "https://api.openai.com/v1",
            "gpt-6.1-sol",
            backend="openai_api",
            api_key="fixture",
            compact=True,
            parameters={"max_output_tokens": 1024},
        )
    ]
    session = Session(cfg)
    session.start(replay=True)
    c, gateway = session.controller, session.controller.gateway
    await gateway.client.aclose()
    replies = [b""]
    gateway.client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=replies[0]))
    )
    try:
        for rev, stage in enumerate(STAGES[:2], 1):
            session.ingest("fixture", "Synthetic", stage["speech"], rev, rev + 1)
            segment = session.transcript[-1]["segment_id"]
            replies[0] = sse(records(stage, rev, segment), incomplete=rev == 2)
            c.submit()
            await c.runner
        assert c.reviewed == 1 and c.cards[-1]["review_status"] == "failed"
        assert c.cards[-1]["reference"]["status"] == "unreviewed"
        assert not session.drafts
        logs = SessionStore.inspect(cfg.data_dir, session.store.id)["hints"]
        result = [x for x in logs if x["type"] == "review"][-1]
        assert result["diagnostics"]["incomplete_reason"] == "max_output_tokens"
        assert "max_output_tokens" in session.status["model"]
        session.ingest("fixture", "Synthetic", "Continue saving while hints fail.", 3, 4)
        data = SessionStore.inspect(cfg.data_dir, session.store.id)
        assert len([e for e in data["events"] if e["type"] == "transcript"]) == 3
        c.attempted = c.revision
    finally:
        await session.shutdown()


@pytest.mark.parametrize(
    "tail",
    [
        ["Okay."],
        ["Multiple processes also need to access these records."],
        ["Multiple processes also need to access these records.", "Okay."],
    ],
)
async def test_inflight_append_keeps_reference_unchecked_until_pending_review(tmp_path, tail):
    c, g, _, _, _, _ = await coding_setup(tmp_path)
    try:
        g.entered.clear()
        g.release.clear()
        ingest(c, 2, "Explain the ID generator.")
        g.next = answer("UPDATE")
        g.next.header["solution"] = "preserve"
        c.submit()
        await g.entered.wait()
        for revision, text in enumerate(tail, 3):
            ingest(c, revision, text)
        g.release.set()
        await c.runner
        ref = c.cards[-1]["reference"]
        assert ref["status"] == ("current" if tail == ["Okay."] else "unreviewed")
        if ref["status"] == "unreviewed":
            assert ref["pending_from"] == 3
        assert c.reviewed == 2 and c.revision == 2 + len(tail)
        c.attempted = c.revision
    finally:
        await c.finish()


@pytest.mark.parametrize("correction", ["Use exact case-sensitive names instead.", "Okay."])
async def test_corrected_evidence_and_requirement_bound_are_visible(tmp_path, correction):
    c, g, _, _, logs, _ = await coding_setup(tmp_path)
    try:
        ingest(c, 2, correction, "s1")
        assert c.cards[0]["requirements"][1]["status"] == "source_changed"
        assert c.cards[0]["requirements"][1]["evidence_revisions"] == {"s1": 1}
        facts = c.cards[0]["requirements"]
        for i in range(3, 24):
            facts.append(
                {**facts[0], "id": f"old-{i}", "text": f"Synthetic retained requirement {i}."}
            )
        g.next = answer("UPDATE")
        g.next.header["_requirements"] = [
            {"text": "One more change.", "kind": "requirement", "segments": ["s1"]}
        ]
        await review(c)
        assert c.reviewed == 1 and "requirement limit" in logs[-1]["error"]
        assert len(c.cards[0]["requirements"]) == 24
        assert c.cards[0]["reference"]["status"] == "unreviewed"
    finally:
        await c.finish()


@pytest.mark.parametrize(
    "speech,extended",
    [
        ("Explain Java volatile visibility.", False),
        ("Implement binary search in Java.", True),
        ("Implement an LRU cache with get, put and evict operations.", True),
        ("Implement a concurrent queue with enqueue and dequeue.", True),
    ],
)
def test_response_capacity_uses_content_not_elapsed_time(speech, extended):
    from interview_helper.coding import coding_capacity

    assert coding_capacity([{"text": speech}], None) is extended


@pytest.mark.parametrize(
    "fragments, expected",
    [
        (["What does volatile mean in Java?"], 1024),
        (["Implement a Java cache."], 2048),
        # No implementation/operation keyword list: substantive accumulated ASR wording.
        (
            [
                "A student directory is our exercise. It needs insertion and editing of students.",
                "There are tens of thousands of entries. Case insensitive full name matching and first name filtering should be fast. Each student has an immutable identity, including when several people share a name.",
            ],
            2048,
        ),
    ],
)
async def test_first_request_capacity_uses_accumulated_context(tmp_path, fragments, expected):
    c, _, _, _, _, _ = await setup(tmp_path)
    ep = Endpoint(
        "fixture",
        "https://api.openai.com/v1",
        "gpt-6.1-sol",
        backend="openai_api",
        compact=True,
        parameters={
            "max_output_tokens": 1024,
            "reasoning_effort": "low",
            "service_tier": "default",
        },
    )
    g = Gateway([ep])
    try:
        for rev, text in enumerate(fragments, 1):
            ingest(c, rev, text)
        assert not c.cards
        payload = g.payload(ep, c.messages(c.snapshot()))
        assert payload["max_output_tokens"] == expected
        assert payload["reasoning"] == {"effort": "low"}
        assert payload["service_tier"] == "default"
    finally:
        c.closed = True
        await c.finish()
        await g.close()


async def test_failed_reference_recovery_resolves_notice_but_keeps_diagnostics(tmp_path):
    cfg = Config.load(tmp_path / "missing")
    cfg.endpoints = [
        Endpoint(
            "fixture",
            "https://api.openai.com/v1",
            "gpt-6.1-sol",
            backend="openai_api",
            api_key="fixture",
            compact=True,
            parameters={"max_output_tokens": 1024},
        )
    ]
    session = Session(cfg)
    session.start(replay=True)
    c = session.controller
    c.stopping = True
    await c.tick_task
    c.stopping = False
    g = c.gateway
    await g.client.aclose()
    replies = [b""]
    g.client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=replies[0]))
    )
    try:
        for rev, (index, fail) in enumerate([(0, False), (2, False), (3, True), (3, False)], 1):
            stage = STAGES[index]
            session.ingest("fixture", "Synthetic", stage["speech"], rev, rev + 1)
            replies[0] = sse(
                records(stage, rev, session.transcript[-1]["segment_id"]), incomplete=fail
            )
            if rev == 4:
                import asyncio

                entered, release = asyncio.Event(), asyncio.Event()
                original = g.race

                async def held(*args, **kwargs):
                    entered.set()
                    await release.wait()
                    return await original(*args, **kwargs)

                g.race = held
            c.submit()
            if rev == 4:
                await entered.wait()
                assert session.status["model"] == "reviewing"
                assert c.cards[0]["reference"]["status"] == "needs_revision"
                assert not session.notices[-1].get("resolved")
                release.set()
            await c.runner
            ref = c.cards[0]["reference"]
            if rev == 2:
                assert ref["status"] == "needs_revision"
            if rev == 3:
                assert ref["status"] == "needs_revision"
                assert c.cards[0]["review_status"] == "failed"
                assert not session.notices[-1].get("resolved")
            if rev == 4:
                assert ref["status"] == "current" and c.cards[0]["review_status"] == "reviewed"
                assert session.status["model"] == "ready"
                assert session.notices[-1]["resolved"]
        # A late error from an obsolete snapshot must not replace recovered status.
        await session.publish(
            "discard", {"request_id": "old", "error": "old failure", "stale": True}
        )
        assert session.notices[-1]["resolved"]
        history = SessionStore.inspect(cfg.data_dir, session.store.id)["hints"]
        assert any(row.get("error") == "Responses incomplete: max_output_tokens" for row in history)
        assert len([row for row in history if row["type"] == "review"]) == 4
    finally:
        await session.shutdown()


async def test_partial_replacement_retains_full_task_scope_and_labels_omissions(tmp_path):
    from interview_helper.gateway import Outcome

    c, g, _, saved, _, _ = await coding_setup(tmp_path)
    try:
        original_facts = deepcopy(c.cards[0]["requirements"])
        ingest(c, 2, "Start by explaining the core identity storage only.", "s2")
        p = Parser()
        p.feed(
            wire(
                [
                    {
                        "action": "UPDATE",
                        "question": "Core identity storage",
                        "developing": False,
                        "segments": ["s2"],
                        "task": "coding",
                        "solution": "replace",
                    },
                    {"text": "TL;DR: This core snippet stores distinct students by stable ID."},
                    {
                        "code": "Map<Long, Student> students = new HashMap<>();\nvoid add(Student student) {\n    students.put(student.id, student);\n}",
                        "language": "java",
                        "scope": "snippet",
                    },
                    {
                        "text": "- Implements ID storage/add only. Indexed exact/prefix search and consistent updates still need implementation."
                    },
                    {"done": True},
                ]
            )
        )
        p.finish()
        g.next = Outcome("fixture", p.header, p.lines)
        await review(c)
        card = c.cards[0]
        assert card["requirements"] == original_facts
        assert card["reference"]["code"].startswith("```java snippet")
        assert "still need implementation" in card["reference"]["notes"]
        assert "StudentDirectory" not in card["reference"]["code"]
        assert saved[-1]["reference"] == card["reference"]
    finally:
        await c.finish()


@pytest.mark.parametrize("known_conflict", [False, True])
async def test_independent_question_preserves_prior_reference_validity(tmp_path, known_conflict):
    c, g, _, saved, _, _ = await coding_setup(tmp_path)
    original = c.cards[0]["reference"]["code"]
    try:
        revision = 2
        if known_conflict:
            ingest(c, revision, "Concurrent callers must see consistent indexes.")
            g.next = answer("UPDATE")
            g.next.header.update(
                solution="invalidate", reason="Index updates need synchronization."
            )
            await review(c)
            revision += 1
        ingest(c, revision, "Independent Java question: what does volatile guarantee?")
        g.next = answer("NEW", start=revision, text="TL;DR: Volatile provides visibility.")
        await review(c)
        assert len(c.cards) == 2
        prior = c.cards[0]
        assert prior["reference"]["code"] == original
        assert prior["reference"]["status"] == ("needs_revision" if known_conflict else "current")
        persisted = {row["id"]: row for row in saved}
        assert persisted[prior["id"]]["reference"] == prior["reference"]
    finally:
        await c.finish()


@pytest.mark.parametrize("tail", [False, True])
async def test_end_and_archive_do_not_turn_review_freshness_into_conflict(tmp_path, tail):
    cfg = Config.load(tmp_path / "missing")
    cfg.endpoints = [
        Endpoint(
            "fixture",
            "https://api.openai.com/v1",
            "gpt-6.1-sol",
            backend="openai_api",
            api_key="fixture",
            compact=True,
        )
    ]
    session = Session(cfg)
    session.start(replay=True)
    c = session.controller
    c.stopping = True
    await c.tick_task
    c.stopping = False
    g = c.gateway
    await g.client.aclose()
    replies = [b""]
    g.client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=replies[0]))
    )
    try:
        session.ingest("fixture", "Synthetic", STAGES[0]["speech"], 0, 1)
        replies[0] = sse(records(STAGES[0], 1, session.transcript[-1]["segment_id"]))
        c.submit()
        await c.runner
        original = c.cards[0]["reference"]["code"]
        if tail:
            session.ingest("fixture", "Synthetic", "All right, that answers that.", 2, 3)
            assert c.cards[0]["reference"]["status"] == "unreviewed"
            replies[0] = sse([{"action": "IGNORE"}, {"done": True}])
        session.end()
        await session.end_task
        assert session.state == "ended"
        archive = SessionStore.inspect(cfg.data_dir, session.store.id)
        card = [h for h in archive["hints"] if h["type"] == "hint"][-1]
        assert card["reference"]["code"] == original
        assert card["reference"]["status"] == ("unreviewed" if tail else "current")
        # Freshness survives truthfully in saved metadata; it is not a known conflict.
        assert card["reference"]["status"] != "needs_revision"
        if tail:
            assert card["reference"]["pending_from"] == 2
            assert any(
                h.get("action") == "IGNORE" and h.get("outcome") == "unchanged"
                for h in archive["hints"]
            )
    finally:
        await session.shutdown()
