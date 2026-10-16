# 0.1.3 cloud responsiveness and reliability

October 14, 2026. Local capture, ASR, continuous saving and the local startup default
remain. No local weights, model hosts, routing or infrastructure were changed.
Paid benchmarking is **paused at the user's request**, pending their matching
organization credit/usage check. Release completion does not mean that comparison
is complete.

## Evidence and method

Read the original 0.1.2 raw failures before implementation. They lacked failed
output bytes and detailed transport stages, so their exact cause cannot be recovered.
New private synthetic evidence preserves output deltas, parser state, usage and
sanitized provider errors. Production does not save raw error bodies/reasoning text.

Retain all 18 frozen 0.1.2 held-out cases. Add four fresh rubrics (lease fencing,
keyset pagination, retry budgets, Unicode sliding windows) and two fragment probes
in [the frozen fixture](../tests/fixtures/cloud_cases_0.1.3.json). Use the same
workloads for legacy HTTP, compact HTTP and compact WebSocket, alternating profile
order by case: 24 short cases and six longer-context cases per profile, 90 requests.
There are 27 actionable attempts/profile plus incomplete, repeat and fragment-WAIT
probes. No warmups; first connections are included. One earlier harness request was
unscored after a fixture-field exception and is disclosed separately, not replaced
as a successful scored sample. Provider load/cache state is uncontrolled.

A single manual review applies full/partial/wrong rubrics separately from protocol,
transport and decision failures. First useful means a **complete validated record
with engineering guidance**, skipping acknowledgment-only lines. Metadata, fragments,
WAIT and failed/rolled-back responses are not successful timing samples. Completion
is separate. P90 is nearest rank. No independent certification or significance claim.
ASR and capture delays are outside these dispatch-based model measurements.

## Bottlenecks

Six initial subscription Luna-low requests reproduced a fresh HTTP connection each
time: the old loop stopped at response.completed before draining the response body.
TCP/TLS generally took about 35–75ms, too small to explain multi-second hints.
The corrected HTTP client reused one connection on 29/30 subsequent requests in
both matched HTTP profiles. WebSocket also reused its connection on 29/30 requests.
No inference warmup/idle generation is used to keep a connection alive.

Median first response event was 1.166s legacy HTTP, 1.097s compact HTTP, 0.159s
compact WebSocket. First provider output-text delta was 1.762s, 1.553s and 1.034s
respectively; these deltas include NDJSON headers and **are not useful hints**.
Removing generated question/header repetition and redundant request IDs reduced
input from 45,118 to 27,704 tokens over the matched workload. Most remaining delay
lies in provider response/generation and completing an answer record. Reasoning
usage was small (139/68/226 tokens); unexposed internal timing prevents attributing
all pre-text delay to reasoning. Transport comparison is observed, not a causal
isolation of provider routing/load.

The final instrumentation distinguishes first provider output delta from first
answer-content delta and first complete record. It records dispatch, credentials,
HTTP connect/TLS/send/headers, connection identity/reuse, exposed reasoning events,
terminal completion, backend publication and browser acknowledgment. The older
matched run's `first_answer_delta` field means provider output delta; it must not
be relabelled useful text. New runs use explicit field names.

The old UI waited for its 700ms poll. A protected long-poll notification now requests
state immediately when hints change, with periodic polling retained for recovery.
A visible synthetic streaming card acknowledged publication in **13.4ms** after
backend publication. This is server receipt after browser animation frames, an
upper bound including local transport; it is not model latency or an exact paint
clock. Offscreen/reloaded examples took 8–19s and are retained separately rather
than presented as rendering performance. Production journals store the same
acknowledgment and dispatch-relative upper bound when available.

## Matched subscription results

App-owned ChatGPT authentication, requested low reasoning, store=false. No paid tier
override or forbidden output cap. All terminal tier echoes were `default`.

| Profile | Full / partial / wrong | Protocol failures | Useful median / p90 | Completion median / p90 |
| --- | ---: | ---: | ---: | ---: |
| Luna low, legacy HTTP | 23 / 3 / 1 | 0 | 3.043 / 4.206s | 4.761 / 6.740s |
| Luna low, compact HTTP | 23 / 2 / 0 | 2 | 2.673 / 3.549s | 5.012 / 5.839s |
| Luna low, compact WebSocket | 25 / 2 / 0 | 0 | 2.173 / 3.248s | 4.249 / 5.327s |

Both incomplete probes passed in every profile. All three direct repeat probes
returned NEW; application consecutive-repeat suppression remains separately tested.
Partial answers omit the explicit stream/datagram distinction or overstate Java
atomic nonblocking guarantees. The legacy pagination answer incorrectly offers a
fixed upper-bound cursor as a snapshot substitute without the necessary assumptions;
legacy SQL/coordination answers also needed qualification. The
[Java 8 atomic specification](https://docs.oracle.com/javase/8/docs/api/java/util/concurrent/atomic/package-summary.html)
permits internal locking on some platforms. Correct main ideas do not excuse false
qualifications. Compact answers were longer (roughly 104-word median versus 73),
despite the 40–70-word target; lower first-useful delay does not imply shorter completion.

Input/output/reasoning tokens: legacy 45,118 / 4,580 / 139; compact HTTP
27,704 / 5,265 / 68; compact WebSocket 27,704 / 5,056 / 226. Reasoning is included
in output. All 90 terminal usage records were retained, including parser failures.
Subscription usage is not a monetary API bill or an allowance percentage.

The continuation instruction was added during transport development, so the broad
run is not presented as an identical-final-prompt benchmark. A subsequent **24-request
final-source bridge** freezes the prompt at gateway construction and repeats the same
12 cases on compact HTTP/WebSocket: corrections, constraints, payments, cache race,
all six fresh/fragment cases and two longer-context cases. HTTP delivered 11/11
actionable answers (10 full, one partial: an external-effect idempotency suggestion
needs stronger fencing qualification), with useful median/p90 2.848/3.603s and
completion 5.190/5.880s. WebSocket delivered 10/11 (10 full, one protocol failure),
with useful 2.117/2.512s and completion 4.392/5.148s. Both WAIT probes passed. The failed
correction omitted the required developing flag; strict validation rejected it.
Across broad, sustained, delta and bridge WS work, two of 59 requests failed protocol;
no blanket reliability claim follows from the first 30 successes.

## Ordinary paid API: verified but incomplete

An explicitly configured application key exposed both requested models. Initial
requests failed despite HTTP 200; later requests completed at all requested tiers
before another provider credit failure. Private account correspondence is archived
outside the source tree. Recovery and the completed comparison are in
[0.1.4](QUALITY_0.1.4.md); the table below remains the earlier, incomplete result.

| Low-reasoning profile | Matched completed cases | Full / partial / wrong | Useful median / p90 | Completion median / p90 | Reported-usage cost |
| --- | ---: | ---: | ---: | ---: | ---: |
| Luna Standard (`default`) | 4 | 3 / 1 / 0 | 2.606 / 2.792s | 4.002 / 4.071s | $0.0008074 |
| Luna Fast (`fast`) | 4 | 3 / 1 / 0 | 1.521 / 1.631s | 2.303 / 2.532s | $0.0015558 |
| Sol Fast (`fast`) | 4 | 3 / 1 / 0 | 1.518 / 1.950s | 2.520 / 2.857s | $0.0237560 |
| Sol Ultrafast (`ultrafast`) | 4 | 3 / 1 / 0 | 1.141 / 1.516s | 1.539 / 1.752s | $0.0713280 |

These are four identical short-context workloads/profile, compact HTTP, no warmups,
1024 maximum output tokens including reasoning. All 16 **completed** responses echo
the requested tier and low reasoning. HTTP 200/response.created alone was not treated
as tier execution. P90 with four observations is just the maximum. No fresh, fragment,
correction, follow-up or longer-context paid case completed; these remain pending.
The tiny sample does not establish a reliable model-quality ranking or speed SLA.

Each profile reported 3,444 input tokens; output/reasoning were Luna Standard 926/265,
Luna Fast 867/287, Sol Fast 499/0, Sol Ultrafast 500/0. Aggregate observed cost is
**$0.0974472**, calculated from actual usage and effective tier at the official
[pricing](https://developers.openai.com/api/docs/pricing). It is not a verified invoice.
Reasoning is not charged a second time. Cached/cache-write input is accounted for
when reported. [Fast](https://developers.openai.com/api/docs/guides/fast-mode) accepts
fast/priority aliases; [Ultrafast](https://developers.openai.com/api/docs/guides/ultrafast-mode)
supports Sol. The current model/tier guide controls over older API-reference snippets.

The initial plan estimated about $0.94; its pessimistic total including existing
reservations was $4.839, so the full workload was reduced before dispatch. The durable
ledger reconciles **23 attempts, 16 with usage, seven without, zero warmups**. Missing
usage retains **$0.27608925** in conservative reservations, giving **$0.37353645**
accounted/reserved against the hard $5 cap. Unknown charges are not called zero.
The latest failure in this run was HTTP 200 followed by raw error type
`insufficient_quota`, code `credit_balance_exhausted`. This was a provider event,
not application translation of a rate-limit error. Unknown-usage reservations and
failed attempts were retained. Exact sanitized errors/request IDs and the ledger
audit are private. No organization/project identity was exposed in catalog headers;
the response alone could not explain the billing discrepancy. See the subsequent
[recovery evidence](QUALITY_0.1.4.md#funding-recovery-and-accounting).

## Failure investigation and sustained operation

Seven bounded Luna-none diagnostics completed two WAIT probes and three actionable
answers; one idempotency response contained malformed/duplicated NDJSON, and a second
idempotency request timed out at 45.043s waiting for response headers after its body
was sent. No response event/text/usage arrived for the timeout. Quarantine stopped
the remaining diagnostic request. This isolates that timeout upstream of parsing/UI;
provider queueing versus inference versus network response delay remains unknown.
Cancellation and remote idle cannot be confirmed for that non-stored request.

Raw failed deltas contain a complete answer followed by stray marker-like text and
another answer. Replaying those bytes through the parser reproduces failure. The
same pattern occurred in two low-reasoning HTTP cases and one later WebSocket case;
it is not exclusive to none. Provider-delivered output violates the requested
protocol; client buffering alone cannot explain those bytes. Model generation versus
provider output assembly cannot be distinguished here. Do not silently strip a
second answer, accept content after done or grade a rolled-back answer as success.
Original 0.1.2 failures lack bytes, so this is new reproduction, not proof of every
historical cause.

Twelve further full-snapshot WebSocket requests had one protocol failure, eleven
successes and a real clean reconnect. Five additional fragment/correction requests
passed, including three connection-local continuations and a second clean reconnect;
Java 8/process/no-lock constraints survived recovery. These are short sustained
sequences, **not an hour-long cloud soak**. HTTP/WS per-request state remains bounded:
full snapshots reset replacement/truncated contexts; chains reset after four turns
or 24,000 input characters. Generated answers are never captured candidate speech.

Actual expiry renewal occurred without new consent: the app-owned credential expiry
advanced and catalog/inference continued, with mode 0600 retained. Independent token-
byte rotation and real revocation were not tested. Simulated tests cover renewed-token
connection rotation, the 55-minute proactive reconnect before the documented
60-minute maximum, explicit previous_response_not_found recovery, interrupted
responses, and HTTP fallback after a failed handshake. Those simulations are not
live 60-minute-limit or revocation tests. An uncertain post-dispatch disconnect is
quarantined rather than replayed or silently duplicated over HTTP.

## Selection and acceptance limits

Recommend **optional ChatGPT Luna low / compact WebSocket** as the current cloud trial:
broader quality evidence and about 29% lower useful median than matched legacy HTTP.
Keep reliable HTTP selectable and local fallback explicit; startup remains local.
Sol Ultrafast is promising in four paid cases, but paid quality/reliability comparison
remains pending. Do not select Luna none or imply reliable sub-second hints.

78 CPU regressions pass, including saving/stale-response/local behavior, recovery,
preview validation and budget reservations. Both themes, persistent theme reload,
streaming/history and narrow layout were visually inspected with a labelled synthetic
fixture. UI notification receipt was measured, not inferred from polling intervals.
Existing local models were not downloaded or rebenchmarked. Kraken GPU, desktop audio,
meeting/hotplug/network acceptance and hosted CI remain separate/unverified. See
[Kraken acceptance](KRAKEN_ACCEPTANCE.md). Previous releases and evidence are preserved.
