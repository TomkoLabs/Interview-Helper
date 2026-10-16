# 0.1.2 quality-first comparison

October 14, 2026, development host. Preserve the configured single-host low-reasoning
LiteLLM default. This evaluation broadens the coder's two-question 0.1.1 screening;
no local weights, gateway routing, runtime or infrastructure settings were changed.
Cloud evaluation follows the user's app-owned ChatGPT consent. Short-context low-
reasoning runs completed; a Luna-none timeout stopped the remaining cloud work.

## Fixed method

The [rubric fixture](../tests/fixtures/quality_cases_0.1.2.json) retains all ten
0.1.1 held-out cases and adds eight fresh engineering questions **before inference**:
payment idempotency, transactional outbox, SQL NULL exclusion, LRU updates/eviction,
async cancellation, lower-bound binary search, stale cache refill, and Java 8
inter-process counters. Its frozen SHA-256 is
`3842eb214f6df188541da2c0273adafa15519a7460e1d3f8b2c846c479cae631`.
The old fixtures and evaluation evidence are unchanged. These cases are held out
from this iteration's implementation/prompt tuning; eight were already used in
0.1.1, so they are not all newly unseen questions.

Each profile gets two blocks in forward/reverse profile order, an explicit warmup
per block, and all 18 cases. Each pass has 16 unique actionable questions (32
attempts/profile), plus incomplete-WAIT and exact-repeat decision probes. Repeat
answers are not independent questions. Run both the existing short synthetic recent
playback and the [longer conversation](../tests/fixtures/latency_context.txt).
The longer pass also uses changing first-system prefixes; these two changes are
confounded, so differences do not establish a causal context or cache effect.
The same production prompt/serializer, active question, constraints and explicit
missing-candidate-speech context are used. No prompt change or cherry-picked retry.

Time from request dispatch to the first validated complete useful text record;
exclude headers, WAIT and acknowledgment-only records (use the first record
containing engineering guidance, including a combined acknowledgment/guidance line).
Completion is separate. Local slot wait, ASR, capture and browser polling are excluded. P90 is nearest rank. Timings include delivered answers with
technical errors; full-quality-only medians are also retained privately. Failures
and missing answers do not become fast successful samples.

One manual reviewer assessed every delivered actionable answer against the frozen
facts: **full** (coverage/no material issue identified), **partial** (useful but
missing requirements or needing qualification), **wrong** (material technical error).
Small explanatory overstatements with a correct actionable solution can be partial;
nonexistent APIs, ineffective correctness guarantees and dangerous contradictions
are wrong. Protocol failures, transport failures and missing answers are separate
categories, not wrong technical answers. This is not independent certification or
statistical significance.

## Existing local models

Primary Flash Next: temperature 0, low reasoning/thinking enabled, 4096-token output
budget. Existing secondary Coder Next: native non-thinking route, temperature 0,
1024 tokens. Both have 120-second deadlines and unproven cancellation. Exact aliases,
private mappings/configuration and raw answers remain in private operational evidence.
The prior dated runtime mapping is not a fresh machine-wide infrastructure audit.

| Context/profile | Delivered / attempts | Full / partial / wrong | Protocol / missing | First median / p90 (s) | Complete median / p90 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Short / primary low | 32 / 32 | 15 / 15 / 2 | 0 / 0 | 1.757 / 2.371 | 2.641 / 3.181 |
| Short / coder | 28 / 32 | 8 / 13 / 7 | 2 / 2 | 2.516 / 2.893 | 4.284 / 5.102 |
| Longer / primary low | 32 / 32 | 16 / 11 / 5 | 0 / 0 | 2.382 / 3.520 | 3.091 / 4.206 |
| Longer / coder | 30 / 32 | 11 / 12 / 7 | 0 / 2 | 3.271 / 3.448 | 4.900 / 5.750 |

Neither local model produced a sub-second useful answer. The coder returned WAIT
for every missing-candidate-answer follow-up (4/4); two short binary-search outputs
failed the actionable-header protocol, without enough accepted output to grade the
technical answer. Both models answered all incomplete probes with WAIT and failed
all direct-model exact-repeat probes with NEW. Production's existing consecutive
repeat suppression is independently regression-tested. Overall decision/protocol
passes are primary 34/36 per context, coder 30/36 short and 32/36 longer.

The coder's material mistakes include unsupported shared_ptr-to-unique_ptr
construction, UUIDv7 collision guarantees, permitting changed idempotency bodies,
cache/DB atomicity claims and invalid inter-process suggestions. Many other coder
answers were useful but omitted node identity, cache-map removal, failed-job handling
or consumer deduplication. The primary remains imperfect: it invents Queue.join
timeouts, misstates modern CancelledError inheritance, overclaims UDP latency and
Java inter-process portability. Its SQL fixes mostly work but sometimes overstate
UNKNOWN instead of distinguishing a matching FALSE result. These differences are
why a two-question coder screening success was not enough for selection.

Some adjudication checks: installed Python reports `Queue.join(self)` and
`issubclass(asyncio.CancelledError, Exception) == False`. The
[Python cancellation guide](https://docs.python.org/3.13/library/asyncio-task.html),
[SQL NULL semantics](https://www.postgresql.org/docs/17/functions-subquery.html)
and [Java LongAdder contract](https://docs.oracle.com/javase/8/docs/api/java/util/concurrent/atomic/LongAdder.html)
support the distinction between a working main solution and misleading qualifications.

Local total: 152 requests, including eight warmups, 152 distinct prompt hashes.
Primary prompt usage ranged 1420–1585 short and 1925–2088 longer tokens; coder
1356–1521 and 1859–2028. All observed scored finish reasons were stop; the two coder
protocol failures ended parsing before final usage/finish telemetry. Warmups reached
24.730 seconds and are excluded from answer medians. No measurable cache benefit
or new runtime/cache setting is claimed.

| Context/profile | Observed input / output tokens | Usage coverage (assessed requests) |
| --- | ---: | ---: |
| Short / primary | 54,384 / 9,547 | 36/36 |
| Short / coder | 49,149 / 4,558 | 34/36 (incomplete total) |
| Longer / primary | 72,556 / 10,675 | 36/36 |
| Longer / coder | 70,279 / 4,974 | 36/36 |

## ChatGPT plan usage

The user completed documented dynamic registration for this app; ID-token signature,
identity and plan scope validated. The live account catalog exposes the requested
models. The initial return-to-home navigation was rejected after a successful grant;
a focused guard fix allows callback/home GET navigation while keeping cross-site
API requests and mutations blocked. No repeat authentication or credential borrowing
was needed. The UI successfully loaded account models, selected cloud with visible
transcript disclosure, then restored the configured local selection.

Cloud uses Responses with the same prompt content/history, explicit requested
reasoning, store=false and stream=true. Preview forbids temperature/output-token
caps, so cloud uses provider defaults for those settings; this is a documented
comparability limitation, not silent removal. Account/provider load and caching
are uncontrolled. The requested `none`/`low` field was sent explicitly; short-run
telemetry did not retain a returned model/effort echo, so account catalog and accepted
request settings are the verification scope, not an internal compute guarantee.

| Short context/profile | Delivered / attempted / planned | Full / partial / wrong | Protocol / transport | First median / p90 (s) | Complete median / p90 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| GPT-6 Luna none | 26 / 30 / 32 | 26 / 0 / 0 | 3 / 1 | 3.036 / 3.920 | 4.778 / 9.899 |
| GPT-6 Luna low | 32 / 32 / 32 | 29 / 3 / 0 | 0 / 0 | 3.000 / 4.433 | 4.920 / 6.720 |
| GPT-6.1 Sol low | 32 / 32 / 32 | 30 / 2 / 0 | 0 / 0 | 6.015 / 7.322 | 10.456 / 12.044 |

No material technical error was identified in the delivered cloud answers on these
rubrics. This does not turn failures into quality passes or establish general
correctness. Partial answers mainly omitted the explicit TCP byte-stream/UDP datagram
distinction; one Luna-low cache answer left the coordination mechanism underspecified.
Luna-none produced three actionable protocol failures, plus another on the incomplete
WAIT probe. Its second binary-search request timed out after 120.102 seconds before
headers/text/usage were observed. The evaluator quarantined the uncertain host and
stopped; no retry was substituted. The remaining two Luna-none short cases and **all
cloud longer-context runs are unrun**, not passes. Upstream idle/cancellation cannot
be confirmed with this non-stored streaming contract; the quarantine was not bypassed.
Luna-low and Sol-low had already completed both short blocks.

All six direct-model repeat probes returned NEW; five of six incomplete probes
returned WAIT, with the Luna-none protocol failure above. Overall decision/protocol
passes were Luna-none 27/34 attempted (36 planned), Luna-low and Sol-low each 34/36.
Application repeat suppression remains separate. No cloud answer was sub-second.
For full-grade-only answers, first median/p90 is Luna-none 3.036/3.920s, Luna-low
2.997/4.630s, Sol-low 6.115/7.322s. These are small sequential samples; the one-answer
full-grade difference between low profiles is not a reliable general ranking.

| Short profile | Observed input / output tokens | Reasoning tokens (included in output) | Usage coverage |
| --- | ---: | ---: | ---: |
| Luna none | 41,315 / 4,425 | 0 | 29/34 attempted assessed (incomplete total) |
| Luna low | 51,419 / 5,335 | 21 | 36/36 |
| Sol low | 51,445 / 4,993 | 0 | 36/36 |

These are API-reported token counts, not a subscription allowance percentage or a
monetary bill. All observed cached-token counts were zero. Many low requests reported
zero reasoning tokens; low is a requested mode, not a promise of positive reasoning
usage. Input range was 1332–1505 tokens across cloud profiles. Six warmups are excluded
from these assessed totals and answer timings (warmup completion 1.914–4.062s).
There were 112 actual cloud requests including warmups, versus 114 planned for short
and 114 additionally planned for longer context. Missing usage from failed requests
means actual plan consumption may be higher than these observed totals.

**Selection:** keep the existing local default and make cloud an explicit opt-in.
Luna low is a reasonable optional quality-oriented trial for this workload: more
complete answers than the local models, with a roughly three-second useful-text
median here. Sol low had one more full-grade answer but roughly six-second median;
the sample does not establish enough general advantage to select it automatically.
Luna none's format failures/timeout prevent selecting it from its successful answers
alone. Cloud is not faster in these observations; longer-context cloud quality and
reliability remain unqualified. See [cloud setup and restrictions](CLOUD.md).
Real token refresh/revocation and ordinary API-key live inference remain unverified;
mock regressions cover those contracts. No paid account or automatic billing was enabled.

## UI and operational scope

The decorative intro, headings, styles and reserved space are removed. IH header,
theme/session controls, session clock and status remain. Before a session starts,
AI hints now accurately says idle; configuration/health is checked on start. Browser
checks cover dark
and light, light reload persistence, 4K/mobile layout without horizontal overflow,
anchored history/new-question counts/Return to latest, transcript and cloud controls.
Populated/streamed screenshots use the labelled synthetic fixture. GPU/audio/meeting
and long-duration target checks are not rerun or inferred from this work; follow
[Kraken acceptance](KRAKEN_ACCEPTANCE.md). Previous tags/evidence remain historical.
