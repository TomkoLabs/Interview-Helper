# Validation and known limitations

Evidence below is dated and scoped to the tested checkpoint. It is not a guarantee
for every desktop, account or future model version. Current behavior is described in
[the specification](../PROJECT_SPEC.md); [installation](INSTALLATION.md#desktop-smoke-test)
provides physical desktop acceptance steps. Historical results do not establish that
an untested setting is faster, that hosted CI ran, or that a launch proves speech quality.

## Offline checks

Using the existing project environment, without model calls or downloads:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
.venv/bin/ruff check src tests scripts --exclude vendor --no-cache
.venv/bin/ruff format --check src tests scripts --exclude vendor --no-cache
bash -n install.sh run.sh start.sh diagnose.sh
```

The 0.1.19 suite has 264 tests. It covers persistence/recovery/disk failures, question
assembly, source discovery/deduplication, revisions, protocol/stream rollback, context
bounds, mic consent/recovery, shutdown, timeout quarantine, cloud contracts/budgets,
connection recovery, setup, migration and upgrade caches. Test doubles and simulated
time are explicit; these are not live provider, audio or GPU endurance tests.

For packaging, use isolated staging with the declared build backend. Verify packaged
prompts/static resources and the licenses listed in [third-party attribution](../THIRD_PARTY.md).
Do not upgrade the running environment or execute the launcher merely to inspect source.
Hosted CI status is a per-commit delivery result, separate from local checks.

## Current answer and microphone checks

**November 12, 2026, 0.1.19:** 264 offline regressions passed. Browser checks used a
labelled synthetic live/archive fixture, both themes at 1280×720, 18 cards, streaming,
manual tail scroll and warm reload. This validates presentation behavior, not real zoom
on all browsers or actual meeting speech.

A synthetic microphone state with 6.1 seconds retained, including 3.8 seconds already
committed, reproduced a false six-second buffer reset. Reclaiming only finalized PCM
before the existing guard avoided that reset. A genuinely starved lane still reported
a gap and discarded results spanning missing audio. The guard and quarantine were not
relaxed. Other historical reset causes were not established without original timing,
request journals, audio and a contemporaneous graph.

Thirteen de-identified synthetic GPT-6.1 Sol / low / Standard / HTTP requests checked
main-answer preservation, concise follow-ups, real constraint changes and corrections.
Twelve were accepted; one omitted required `developing` and was rejected without
replacing the existing card. Explicit protocol guidance was retained in final checks.
This is a small semantic comparison, not an Ultrafast latency or reliability estimate.

- Earlier recursion/clock answers kept code but redirected main prose and repeated notes;
  final checked follow-ups kept the main/code and used 15, 17 and 14 words.
- Both versions ignored a navigation-only comment.
- A no-rescan playback constraint correctly introduced a reusable position index.
- A real empty-word bug triggered an explicit correction rather than preserving bad code.
- Actual generated index and corrected scan code compiled and passed 600 deterministic
  batches. This does not prove all future generated code is correct.

Reported usage was 48,246 input and 2,275 output tokens, including 48 reasoning tokens;
usage-priced cost was US$0.0748663 at the rates used for that run. No real interview was
sent for these checks. Private evidence is not part of the source distribution.

## Extended coding checks

**October 26, 2026, 0.1.14:** six synthetic stages used GPT-6.1 Sol / low / Standard /
HTTP with a 2,048-token ceiling. Returned model, tier and requested effort were checked.
All six completed and preserved/refined the same task until an independent transition.

| Stage | First useful / complete (s) | Output tokens |
| --- | ---: | ---: |
| Initial implementation | 8.257 / 16.230 | 1,222 |
| Identity clarification | 2.399 / 4.473 | 202 |
| Duplicate names | 4.388 / 7.336 | 333 |
| Concurrent updates | 4.037 / 10.561 | 1,003 |
| Feedback about unseen code | 2.989 / 5.540 | 259 |
| Independent transition | 1.832 / 3.516 | 158 |

Useful median/p90 was 3.513/8.257s; completion 6.438/16.230s. With six observations,
nearest-rank p90 is the maximum. Usage: 22,728 input / 3,177 output, including 217
reasoning tokens; reported-usage cost US$0.063177. These are Standard-tier measurements,
not deployment latency. There was no cap-increasing retry.

Two actual generated Java 8 references compiled and passed duplicate/update/prefix,
rename membership, detached-snapshot and eight-worker checks (1,610 IDs). Caller-supplied
IDs were distinguished from name fields and ID allocation. Complete references reached
74 lines, exceeding the soft 50-line target while fitting the token cap. These checks
are not a proof for every Unicode input, production failure mode or generated solution.
Offline fixtures also cover a virtual 40-minute pause, retention, invalidation and
transition; simulated elapsed time is not provider endurance.

## Measurement method

Frozen fixtures distinguish **full** (no material issue found against the rubric),
**partial** (useful but incomplete or requiring qualification), and **wrong** (material
technical error). Protocol, transport and decision failures remain separate. One manual
reviewer assessed small samples; this is not independent correctness certification.
Repeated cases are not independent unseen questions. Technical hints need human review.

First-useful timing starts at dispatch and ends at a validated complete useful sentence
or bullet. Headers, metadata, acknowledgments alone and incomplete fragments do not
count. ASR, local queueing and browser paint are excluded. Completion is separate;
p90 uses nearest rank. Delivered wrong answers remain visible in latency denominators
unless explicitly stated otherwise; failed/missing answers never become fast successes.
Runs were sequential with uncontrolled provider load and cache state. Dates, model,
reasoning, tier, transport and prompt generation matter; cross-date results are not
causal comparisons of a single change.

Fixtures remain in `tests/fixtures`: the earlier latency cases, 18 held-out quality
cases (including eight fresh engineering cases), cloud cases, coding sequences and
paired simple/explicit-optimization solution-selection cases. The longer conversation
is synthetic. Some held-out questions were used in previous iterations; they are not
all newly unseen. Evaluation scripts remain available with their spending safeguards.

## Paid cloud comparison

**October 14, 2026, 0.1.4:** four low-reasoning HTTP profiles, 1,024 output tokens
including reasoning, 30 matched cases each: 24 short (18 frozen, four fresh, two
fragments) and six long. Each profile had 27 actionable questions and three decision
probes. All 120 responses completed with the terminal requested tier confirmed and
zero protocol/transport failures. HTTP 200 or a creation-event echo alone was not used
as tier proof. Prices below are historical reported-usage costs, not current quotes.

| Profile | Full / partial / wrong | Decision failures | Useful median / p90 (s) | Complete median / p90 (s) | Cost (US$) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Luna Standard | 25 / 2 / 0 | 1 | 2.054 / 3.143 | 2.760 / 4.120 | 0.006463175 |
| Luna Fast | 25 / 2 / 0 | 2 | 1.528 / 2.150 | 2.142 / 3.093 | 0.013113350 |
| Sol Fast | 25 / 2 / 0 | 2 | 1.529 / 1.953 | 2.749 / 3.146 | 0.198627 |
| Sol Ultrafast | 26 / 1 / 0 | 1 | 1.015 / 1.516 | 1.363 / 1.752 | 0.588921000 |

Input was 28,684 tokens per profile. Output/reasoning counts respectively:
6,788/2,248; 6,975/2,525; 3,793/101; 3,677/64. Reasoning is included in output.
All profiles omitted the explicit UDP datagram distinction in one answer. Luna also
underqualified pagination snapshots; Sol Fast underqualified cancellation bookkeeping.
All repeated-question probes produced NEW; Luna Fast and Sol Fast also answered a
fragment prematurely. Corrections produced UPDATE. App repeat suppression is separate.

A smaller Sol Ultrafast WebSocket set had 12 protocol passes, 11 actionable answers
(10 full, one wrong Bellman–Ford qualification) and a correct WAIT; 11 connections were
reused. Useful median/p90 across the 11 answers was 0.721/1.214s. Across only ten correct
answers it was 0.707/0.841s, with a 2.173s maximum. The paired HTTP actionable set was
11/11 full, 1.015/1.128s. Different run times/provider load prevent a causal transport
ranking, and the smaller set is not a general quality estimate. Five further WS
fragment/correction requests passed, including three continuations and clean reconnect.

The broader quality result supports the fresh Sol low / Ultrafast / HTTP default;
it does not guarantee sub-second useful text. WebSocket remains optional/experimental.
First response events around 0.424–0.456s were not useful hints; generation to a complete
validated record dominated. An earlier coalesced header/text telemetry bug affected
`first_answer_delta`; fixed regressions cover it. Independent complete-useful-record
timings were not reinterpreted as metadata timing.

## Subscription and protocol investigation

**October 14, 2026, 0.1.3:** 90 matched Luna-low subscription requests (30 per profile,
27 actionable plus three decision probes) compared legacy HTTP and compact HTTP/WS.
Preview restrictions prevented ordinary-API output caps; do not treat this as an equal
compute-budget comparison with the paid profiles.

| Profile | Full / partial / wrong | Protocol failures | Useful median / p90 (s) | Complete median / p90 (s) |
| --- | ---: | ---: | ---: | ---: |
| Legacy HTTP | 23 / 3 / 1 | 0 | 3.043 / 4.206 | 4.761 / 6.740 |
| Compact HTTP | 23 / 2 / 0 | 2 | 2.673 / 3.549 | 5.012 / 5.839 |
| Compact WS | 25 / 2 / 0 | 0 | 2.173 / 3.248 | 4.249 / 5.327 |

Compact instructions reduced input from 45,118 to 27,704 tokens per profile. A later
24-request final-prompt bridge had HTTP 11/11 actionable accepted (ten full, one partial)
and WS 10/11 accepted (all full, one missing-header failure). Useful median/p90 was
2.848/3.603s HTTP and 2.117/2.512s WS. Both WAIT probes passed. Across the broader WS
sequences, two of 59 requests failed protocol. Prompt changes and small samples limit
attribution of improvements.

HTTP previously stopped at terminal events before EOF, losing pool reuse. Draining to
EOF yielded reuse in 29/30 requests, as did WS. Six earlier fresh TCP/TLS probes took
roughly 35–75ms, a minority of total useful-answer time. A synthetic browser notification
acknowledgment of 13.4ms bounded receipt latency; it did not measure paint or model speed.

Luna-none failures were investigated separately from answer quality. Seven bounded
diagnostics produced two WAITs and three actionable answers, one malformed/duplicated
NDJSON answer, and one 45.043s timeout before headers/events/text/usage. Quarantine
stopped remaining work. This timeout preceded parsing/UI; provider queueing, inference
and network response delay were not distinguishable. Cancellation/remote idle was not
confirmed. Earlier 0.1.2 had a 120.102s no-header timeout and missing raw failure bytes;
later reproduction does not establish every historical cause.

Raw delivered failure bytes contained a complete answer, stray text and another answer;
parser replay reproduced rejection. Low-reasoning HTTP and WS also exhibited this
pattern. It is a provider-delivered protocol violation, not proof of a none-only model
quality defect or a UI-buffering fault. Generation versus provider assembly remains
unknown. Content after done must not be silently stripped or counted as success.

Real account expiry renewal advanced expiry and allowed authenticated inference without
new consent. Independent token-byte rotation and real revocation were not checked.
Signed fixtures and simulated transport cover renewal/reconnect, the 55-minute rotation
before the documented 60-minute limit, previous-response loss and safe handshake
fallback. Short real reconnect sequences are not a live hour-long connection-limit test.

## Local model comparison

**October 14, 2026, 0.1.2:** broader primary Flash Next low-reasoning versus native
non-thinking Coder Next, temperature zero, respective 4,096/1,024 output caps and
120-second deadlines. No new weights or infrastructure settings were introduced.
Each short/long profile had 32 actionable attempts (16 questions repeated), plus
incomplete/repeat probes; 152 local requests included eight warmups. Longer context
also changed system prefixes, so context and prefix effects were confounded.

| Context/profile | Delivered / attempts | Full / partial / wrong | Protocol / missing | Useful median / p90 (s) | Complete median / p90 (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Short / primary low | 32 / 32 | 15 / 15 / 2 | 0 / 0 | 1.757 / 2.371 | 2.641 / 3.181 |
| Short / coder | 28 / 32 | 8 / 13 / 7 | 2 / 2 | 2.516 / 2.893 | 4.284 / 5.102 |
| Longer / primary low | 32 / 32 | 16 / 11 / 5 | 0 / 0 | 2.382 / 3.520 | 3.091 / 4.206 |
| Longer / coder | 30 / 32 | 11 / 12 / 7 | 0 / 2 | 3.271 / 3.448 | 4.900 / 5.750 |

Coder errors included nonexistent smart-pointer conversion, UUID collision guarantees,
idempotency-body changes and invalid inter-process suggestions. Primary errors included
nonexistent queue timeouts, cancellation inheritance and inter-process portability.
Useful partial answers omitted identity, eviction cleanup or failure handling. Two
screening questions were insufficient for model selection. All direct-model repeat
probes produced NEW; app suppression remains a separately tested safeguard.

Neither model gave sub-second useful text here. Earlier 0.1.1 faster/no-thinking tests
traded away longer-context quality and fragment handling; two-host racing had draining
losers and uncontrolled cache/order. No measurable prefix-cache advantage was established.
Unproven disconnect cancellation remained disabled. These historical local results do
not establish current gateway inventory, whole-host throughput or target GPU capacity.

## Microphone and audio evidence

**October 29, 2026, 0.1.17:** 228 offline tests plus isolated PipeWire 1.4.2 WebRTC AEC
with manually linked virtual devices. A 65-second synthetic speech/linear-echo sequence
used gain/delay 0.35/80ms, then 0.65/120ms. Remote-only intervals showed 81.5/79.9dB
raw-to-clean reduction and no CPU-ASR text; local-only correlation was 0.936/0.937,
gain 0.897/0.900. Overlap correlation fell to 0.692, with later words garbled despite
retained opening content. Alignment varied; attenuation is not an intelligibility
or real-room guarantee. There was no physical microphone/GPU endurance claim.

**November 4, 2026, 0.1.18:** 251 offline tests and isolated real PipeWire null-graph
checks accepted delayed clean links, rejected unsafe/raw links and verified owned-only
cleanup after backend EOF. This does not prove session-manager autolinking in a real
meeting. Both-theme synthetic browser checks at 1920×1080, 3840×2160 and 390×844 covered
scrolling, consent persistence and cache behavior without observed horizontal overflow.

Playback regressions include sanitized pactl 17/PipeWire 1.4.2 outputs with missing
JSON module indices and multiline short records, both playback monitors, exclusion of
both physical inputs, strict identity validation and forwarding deduplication. Isolated
real PulseAudio capture/hotplug/dedup checks passed historically. Fixtures and isolated
servers do not prove the actual desktop's routing or acoustic behavior.

## Duration and upgrades

The 0.1.5 inexpensive wall-clock synthetic soak ran 10,803 seconds, saved and recovered
all 2,157 events through 126 simulated provider failures. It was not a meeting, GPU,
ASR or real-provider endurance test. Sessions have no automatic duration or IH spending
cutoff; disk journals grow while model context/live history stay bounded. Provider
quotas, request timeouts, quarantine and storage errors still apply. Normal sessions
do not read the evaluation ledger.

The 0.1.16 upgrade checks reproduced stale timestamp bytecode with same-sized changed
source and matching timestamps, then verified fresh imports through supported startup,
unchanged-launch no-op and runtime-lock protection. Content fingerprints changed asset
URLs only when bytes changed; uncached HTML and a confirmed warm browser context loaded
matching bytes on normal reload. Configuration-preserving extracted upgrades were
checked through later versions, including licenses/package resources. They did not
clear settings, keys, models or sessions. A controlled cache reproduction cannot identify
the exact header collision in an incident whose headers were not inspected.

## Remaining acceptance

Real desktop GPU memory/lag, actual browser zoom, physical hotplug, room echo/overlap,
meeting applications, multi-hour recognition and provider reliability require explicit
target acceptance. Startup alone establishes none of these. Microphone deferral is not
guaranteed zero-cost; a blocked native library may require backend termination. AI
answers can remain incomplete or wrong even when protocol validation passes. Use the
[desktop and microphone checklist](INSTALLATION.md#desktop-smoke-test), and distinguish
user-reported observations from independently measured tests.
