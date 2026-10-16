# 0.1.9 progressive transcript review

## Findings and scope

The reported subsequence answer was appropriate. An unchanged card alone cannot
show whether later speech was reviewed, and the original Kraken journals were not
supplied. Inspection confirmed that 0.1.8 locally filtered filler/dangling wording,
removed IGNORE text from retained scenario context, suppressed exact repeated wording,
and had a single-answer protocol. These are application behaviors, not proof of the
cause of the user's particular observation.

A small real Sol replay confirmed that the baseline reviewed the definition/example
and returned IGNORE. It correctly refined for Java and repeated batches over fixed s.
For two distinct questions in one batch, Sol emitted two answers; the baseline parser
rejected the second header. Baseline finish then resubmitted that failed snapshot once.
The new protocol accepts this bounded multi-answer structure; unchanged successful
reviews and failed/superseded attempts are separately observable.

## Context, interpretation and scheduling

Every nonblank committed segment is eligible for review. Local filler, dangling-phrase
and repeated-wording suppression are removed. WAIT/IGNORE advance successful coverage
without deleting speech. The model sees one chronological CONVERSATION containing the
recent window and older retained problem wording once each, not overlapping copies of
pending/scenario/recent text. Revisions distinguish new speech from previously reviewed
history; eight recent card identities/headings and the active answer provide context.
Physical device names are replaced with compact per-packet playback-source labels.

The recent window remains 90 seconds / 6,000 text characters by default. Active verbatim
wording remains bounded at 16,000 characters. Both also have a 512-segment metadata bound.
A model-supplied NEW start_revision is validated against retained chronological positions
before it can reset the active wording. Legacy single-answer headers without that field
remain accepted conservatively, retaining full context. UPDATE retains all accumulated
wording. Overflow pauses hints visibly; it never sends a truncated essential requirement,
stops saving, or silently summarizes speech. Reset context remains explicit.

The same model call interprets examples, candidate explanations, requests, corrections
and follow-ups. No serial classifier was added. One request can return up to three
separate answers in order: only the first may UPDATE; subsequent answers must be NEW.
One final done record validates the whole response. More than three requests must produce
an explicit overflow error, rather than silently omitting requests. Each complete record
carries its own publication state even when a transport delta coalesces several records.
Malformed/truncated batches roll back drafts and preserve previous useful answers.

Scheduling uses a 100ms tick: initial committed content gets a review after about 0.7s;
coalesced continuous speech gets a review within the configured 1.8s interval when a host
is available. About one second of observed speech inactivity triggers a trailing review;
the existing ASR silence-finalization signal also triggers once corresponding words are
committed (150ms coalescing allowance). Without audio activity, commit inactivity is the
fallback. Silence does not declare a question boundary. The existing energy threshold
and ASR processing cadence are unchanged; this is not new VAD or ASR tuning.

There is still one running review and one replaceable pending snapshot. Speech arriving
during inference gets a follow-up. Successful coverage, attempted revision and immutable
snapshot identity are separate: timers/finish do not resubmit the same failed snapshot.
New speech remains eligible after an error, subject to unchanged provider quarantine.
Correction cues only invalidate stale drafts; they never classify or remove speech.
Revised segment identities also invalidate old responses. Final ASR flush is reviewed
through normal bounded provider requests before session close. Existing per-request
limits and drain behavior remain; no promise of instantaneous shutdown is made.

Private review records include included/new revision positions, snapshot hash, trigger,
follow-up revision, decisions/card IDs, validation result, latency and usage. Saved hints
record new/updated/unchanged publication. No duplicate transcript body, credentials or
hidden reasoning are added to diagnostics. The actual speech remains in its journal.
WebSocket mode uses full bounded packets for this new representation; its existing
rotation/recovery still applies, without accumulating an interview-long continuation.

## Real matched replay — October 15, 2026

Ordinary API, existing app-owned key, gpt-6.1-sol / low / Ultrafast / HTTP / 1024 output
ceiling. All eleven responses reported effective `ultrafast`; no model/profile search.
Five matched progressive stages: subsequence opening; definition/example and candidate
explanation; Java/duplicates/empty words; correction to repeated small batches over a
fixed large string; two independent mutex/semaphore and composite-index questions.
Baseline ran first on the frozen 0.1.8 tree; proposed ran second, one pass each. No warmups.
The baseline's sixth call was its automatic shutdown retry, not a sixth matched case.
No additional Why? live probe was run; contextual follow-ups are covered offline.

| Measure | 0.1.8 baseline | Proposed |
| --- | --- | --- |
| Accepted grouping/decision stages | 4/5 | 5/5 |
| Final cards (expected 3) | 1; batch rejected | 3 |
| Material later constraints missed | 0 in accepted refinements | 0 |
| Unnecessary accepted cards | 0 | 0 |
| Requests / avoidable repeat | 6 / 1 | 5 / 0 |
| Protocol failures | 2 including repeat | 0 |
| Initial useful complete record | 1.508s | 1.132s |
| Accepted useful median / empirical p90 | 1.666 / 1.859s (n=3) | 1.147 / 1.382s (n=4) |
| Accepted completion median / empirical p90 | 2.687 / 2.823s | 1.830 / 2.139s |
| Final correction commit → completed refinement | 2.833s | 1.326s |
| Usage-based cost | $0.1603524 | $0.1456140 |

Timings are synthetic committed-text replay, not playback-to-ASR latency. Reviews were
submitted at identical deterministic commit points, so these do not measure automatic
trigger delay. Median/p90 exclude rejected drafts and IGNORE; different accepted counts
and fixed baseline-first ordering prevent a reliable speedup/general p90 claim. The
existing benchmark latency does not qualify these new prompts. Final source-label
compaction and publication diagnostics were checked offline after this replay.

Manual answer review: both solutions handled detached buckets, duplicate/empty words,
and the fixed-string correction. Proposed Java guidance was concrete and the two new
answers retained ownership and index/skip-scan qualifiers. Proposed initial complexity
omitted the per-word initialization term for empty words; later Java/corrected answers
included it. This is useful-but-incomplete precision, not a fully correct blanket result.
Implementation requests produced longer code records than normal hints. Classification
and technical quality remain imperfect; one short run is not production qualification.

Total new spend **$0.3059664**, 11,444 input and 2,722 output tokens (344 reasoning tokens
included in output). Historical ledger entries and $0.27608925 missing-usage reservations
are unchanged. Original cumulative usage-based cost is now $1.387248225; accounted total
including reservations **$1.663337475**, leaving **$3.336662525** under the original $5 cap.
Every request reserved cost before dispatch, with a second ceiling of starting accounted
usage + $0.75; neither ledger authorization nor normal session controls were reset.
Prices use [official Sol pricing](https://developers.openai.com/api/docs/models/gpt-6.1-sol)
verified October 15: Ultrafast $12/$0.60/$15/$60 per million input/cached/cache-write/output.
Usage-derived cost is an estimate of the provider charge, not an independently audited invoice.

Raw synthetic evidence stays private. Baseline raw-delta diagnostic text inserted spaces
between chunks; accepted parsed records, protocol errors, timing and usage are authoritative.
Proposed raw deltas preserve exact concatenation. No live Kraken journals were read.

## Offline and browser acceptance

140 offline tests passed at the implementation checkpoint, including verbatim coverage
through WAIT/IGNORE, in-flight constraints, final flush, pause/delayed-commit/maximum-delay
triggers, corrected segments, long-window eviction, multi-answer/coalesced records,
invalid boundaries, overflow, unchanged snapshots and provider failure rollback.
Existing audio, storage/recovery, transport/quarantine and WebSocket recovery checks pass.
Browser inspection uses a separate localhost mock transport: old useful answer survives a
truncated update with visible error; one batch creates two distinct cards; themes and
session saving remain available. This is synthetic UI validation, not real audio or GPU
endurance. No new three-hour soak, storage migration, model download or infrastructure
change. Revised real Kraken playback, delayed GPU commits and long meeting behavior remain
acceptance checks in the [Kraken checklist](KRAKEN_ACCEPTANCE.md#updating-to-019).
