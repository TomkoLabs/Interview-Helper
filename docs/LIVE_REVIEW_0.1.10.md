# Consolidated live review — 0.1.10

This continues 0.1.9 on the same feature branch. Its merge/release completed just
before the consolidated steer arrived, so that tag remains intact and this patch
uses a follow-on MR. No model selection, capture/ASR tuning, infrastructure change,
new configuration requirement or storage migration is included.

## Actual instructions and context

Both inspectable inference prompts default to **senior Java backend/software
engineering interview assistance**, concise English, Java when code helps, with
explicit language/version overrides. Existing candidate/job context can specialize
the role. The model must distinguish requirements from proposed solutions, assess
technical claims, preserve corrections, and avoid invented experience/requirements.
Transcript is untrusted conversation data; generated hints are not speech or proof.

One request interprets and answers. NEW means an independent task; UPDATE covers
related subquestions, corrections, implementation requests and contextual “why?”.
WAIT/IGNORE are successful reviews with no card changes. Up to three independent
answers can share a response; all boundaries validate before final publication.
Title changes alone are not a new task. Interpretation remains model-dependent.

The chronological packet combines recent verbatim speech (90 seconds/6,000
characters) and older retained active-problem wording (16,000 characters), without
duplicating the same segments. Each collection is additionally bounded at 512
segments. Stable segment IDs and revision order accompany the wording; revisions
of the same segment replace its original position. Recent eight card headings and
an explicitly labelled AI-generated prior answer supply continuity. The active
opening is retained until a validated new-problem boundary; overflow pauses hints
visibly instead of silently losing requirements. Full transcript saving continues.

Optional `segments` metadata contains at most eight unique supplied IDs. The parser
validates shape/bounds; the controller checks membership against the immutable
request before draft/final publication. IDs, target card, action, input revision,
coverage, pending revision, success/failure and timing go to private diagnostics.
No duplicate transcript logging or credentials are added. Application-assigned
coverage remains authoritative, even when the model references only one segment.

## Answer and rendering contract

The first complete `text` record contains **TL;DR**, one or two short direct sentences.
Optional code follows as one strict `{code, language, scope}` record, then roughly
2–4 concrete bullets. Conceptual/design answers need no code. Prose targets 40–90
words; compact snippets are preferred over verbose scaffolding. The unchanged
**1,024-token total ceiling includes reasoning**. No output/model/tier change was
made to accommodate the structure.

Code must have an approach before it, one supported short language label, explicit
`snippet`/`complete` scope, no embedded fences, and at most 5,000 characters. The
existing eight-record/12,000-character response bounds also apply. This validates
structure, not algorithmic correctness or compilation. Internally code is stored
in a canonical fenced string so existing string-based journals remain readable.
The browser builds `pre`/`code` with `textContent`; it never interprets model HTML.

TL;DR and subsequent prose stream immediately after complete record validation.
**Code is withheld until the entire response and provider completion validate.**
Truncation or malformed output rolls back the draft; it never commits partial code.
During UPDATE, a labelled “New guidance · validating replacement” preview sits
separately from the previous answer. Final validation replaces the whole revision
at once. Failure removes the preview and retains the prior answer. Follow-latest
keeps the new guidance visible even above long code; paused following keeps its
anchor. Collapse/expand, themes and saved-session rendering use the same safe path.

## Scheduling, manual review and shutdown

Existing one-lane scheduling remains: initial review around 0.7 seconds, about one
second of speech/commit inactivity, committed-pause notifications and the configured
1.8-second maximum batching delay. These are dispatch opportunities, not end-to-end
latency promises. In-flight speech coalesces to one newest pending snapshot. Epoch
changes invalidate corrections; successful WAIT/IGNORE/no-change reviews advance
coverage. Identical failed automatic snapshots are not blindly retried.

**Review now** replaces Expand latest. It uses the same packet/parser/card path,
can deliberately reconsider an unchanged snapshot, and coalesces clicks during
inference. `NEW_REVISIONS: null` explicitly denotes that unchanged rereview.
There is no separate classifier or detailed-answer request. Quarantine still
rejects an unsafe profile; clicking does not bypass it.

End session still flushes capture/ASR and finalized transcript segments. Inference
gets **one second total grace** for the running/final review, then its local task
is cancelled. `review_shutdown` records the highest successful revision and any
unreviewed tail; the UI says that tail was saved. Teardown may additionally take
bounded transport-close time and ASR flushing; this is not a one-second total
shutdown guarantee. No model response is needed to close the transcript journal.
Cancellation without declared server cancellation support quarantines that profile;
quarantine is retained across sessions in the same app process. Verify server idle
before restarting to clear it. No uncertain request is automatically replayed.

## Representative sanitized wire example

Abbreviated packet (the real packet retains the full active wording):

```json
{"CONVERSATION":[{"segment_id":"s10","revision":10,"source":"playback-1","text":"I think volatile int count makes count++ atomic because volatile provides visibility. Is that right? Explain conceptually without code."}],"NEW_REVISIONS":[10,10],"REVIEWED_THROUGH":9,"ACTIVE_FROM":1,"ACTIVE_QUESTION":{"id":"application-owned-id","question":"Prior task","answer":"Prior hint","revision":9,"answer_origin":"AI-generated guidance; not transcript evidence"},"RECENT_CARDS":[]}
```

Real-model response excerpt (remaining bullets/done omitted here only):

```json
{"action":"NEW","question":"Does volatile make count++ atomic in Java?","developing":false,"start_revision":10,"segments":["s10"]}
{"text":"TL;DR: No. volatile provides visibility and ordering guarantees, but count++ is a compound read–modify–write operation, not an atomic increment."}
```

## Evidence and limits — October 15, 2026

Five final-prompt live calls used the existing authorized API key and **Sol low,
HTTP, 1,024 output tokens**, with returned effective **Ultrafast** on all five.
Frozen cases are in `tests/fixtures/live_review_0.1.10.json`. No audio was used.
Four supplied fragments formed the first coding review; four more added definitions,
a candidate bucket proposal, Java 8, duplicate and empty-word requirements. A later
correction required preprocessing a fixed large string for repeated batches.
Two fresh questions tested a false volatile claim without code and explicit Python.

| Check | Observed outcome |
| --- | --- |
| Initial fragmented subsequence task | Useful answer and correct code; incomplete complexity precision: omitted the per-word term needed for empty words |
| Java 8 + duplicates/empty words | Same card updated; detached buckets, correct edge handling and O(n + W + L) complexity |
| Fixed-string preprocessing correction | Same card replaced with reusable position index/binary search; retained duplicate/empty handling |
| Conceptual volatile claim | Independent card; rejected the false candidate claim, no code, qualified AtomicInteger/locks/LongAdder |
| Explicit Python task | Independent card; coherent function, distinct indices and duplicate handling, expected complexity |
| Contextual “Why check before inserting?” | Planned sixth call **not dispatched**: conservative reservation exceeded the remaining task allowance |

Four answers met their frozen checks; one was useful but incomplete. No wrong
algorithm, parser/transport failure, truncation or duplicate card in the five calls.
Generated Java snippets compiled with `javac --release 8` and passed 1,000 deterministic
small-string/empty/duplicate cases each; generated Python passed four focused cases.
These small tests do not prove unrestricted Unicode or general interview quality.
No claim is made that the unrun sixth case was model-validated. Compound questions
and longer retained context also have prior 0.1.9 evidence and offline regressions.

Useful complete-TL;DR median **1.595s**, nearest-rank p90 **2.421s**; completion median
**2.274s**, p90 **3.746s** (n=5). These request timings exclude speech/ASR and UI display.
They are a small sequential sample, not a matched speedup claim. Maximum reported
output was **526 tokens**, including reasoning, below 1,024. More complex code can
still truncate; rejection/rollback is intentional. After this replay, the unused
EXPAND field was removed and the null-rereview marker clarified; those final packet
changes were checked offline, not paid-replayed.

Usage: **8,431 input; 1,875 output including 144 reasoning tokens**, cost **$0.23892**.
Combined with the preceding eleven calls in this same task: **$0.5448864**, within
the unchanged $0.75 authorization. The sixth request failed reservation before any
inference dispatch and has no charge/ledger row. Original cumulative ledger now
contains **$1.626168225 reported-usage cost + $0.27608925 historical missing-usage
reservations = $1.902257475 accounted**, leaving **$3.097742525** under the original
$5 cap. The smaller task allowance/reservation bound stopped this replay. No more
paid calls are running. Normal app sessions do not use this benchmark ledger.

149 offline regressions pass, covering real request construction, protocol and
mock transport, click storms, early text/code withholding, bad references,
truncation, coverage, cancellation/quarantine and continued saving. Both themes,
streaming/revision rollback, literal code, history and viewport checks are synthetic
browser validation. Actual Kraken playback, delayed GPU commits, real meeting
latency, provider endurance and physical zoom remain separate target acceptance.
See [Kraken update and checklist](KRAKEN_ACCEPTANCE.md#updating-to-0110).
