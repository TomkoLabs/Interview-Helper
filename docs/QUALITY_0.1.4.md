# 0.1.4 — funded paid comparison and timing correction

Validated October 14, 2026. This completes the bounded paid comparison left pending
in [0.1.3](QUALITY_0.1.3.md). Recommend **ordinary API GPT-6.1 Sol, low reasoning,
Ultrafast, HTTP** for the paid cloud option. It combined the strongest demonstrated
quality with useful median/p90 **1.015/1.516s**. Local startup/capture/ASR/saving remain
unchanged. Cloud selection is explicit and sends transcript context to OpenAI.
No reliable sub-second, unrestricted quality or hour-long reliability claim follows.

## Funding recovery and accounting

The earlier provider credit error was followed by one bounded Standard-tier recovery
probe before resuming the comparison. Private account/funding correspondence is
preserved outside the source tree. No billing setting was changed by IH.

One Luna low Standard probe ran after closing the catalog connection and creating a
fresh HTTP client. At 14:06 EDT it completed with returned tier `default`, 807 input,
166 output (107 reasoning included), cost $0.0001637 and useful text at 4.073s. The
trace confirms fresh TCP/TLS. Account-credit pause was process-local; the documented
new evaluator/session mechanism recovered it. No timeout quarantine was cleared or
bypassed, no ledger was reset, and no uncertain request was blindly replayed.

No new credit, authentication, transport or protocol failure occurred in the 122
new requests. The previous provider errors remain preserved. The successful probe
and subsequent requests establish current recovery, not the cause of earlier errors.
API headers did not expose an organization/project identifier; this run does not
establish the cause of the earlier provider credit errors.

Cumulative original ledger: **145 attempts, 138 with usage, seven without, zero
warmups**. This comprises seven historical missing-usage failures, 120 matched HTTP
cases, one recovery probe, 12 WebSocket cases and five continuation/reconnect cases.

- Reported-usage cost: **$1.081281825**; unknown-usage reservations: **$0.27608925**.
- Total accounted/reserved: **$1.357371075**, below the original hard **US$5** cap.
- Reported input/output: **130,746 / 23,376 tokens**; output includes **5,082 reasoning**.
- Cache-read/write and effective tier rates are included. Reasoning is not charged twice.
- These are usage-priced amounts, not an independently verified final invoice. The
  user's earlier $0.10/16-request Platform observation corroborates the initial run.

[Official prices](https://developers.openai.com/api/docs/pricing) were rechecked before
execution. Each dispatch reserves conservatively and settles from terminal usage;
missing usage retains its reservation. Remaining authorization is not increased by
credit purchases. Paid work is now stopped because this bounded comparison is complete.

## Same workloads and useful-hint definition

Each HTTP profile received the same 24 short cases: 18 frozen held-out questions plus
four fresh engineering rubrics and two fragments. The six longer-context cases match
the earlier subscription run: linked-list intersection, ownership, follow-up,
idempotency, cancellation and Java interprocess constraints. Alternating profile
order is retained. The first four short cases per profile are the preserved earlier
run; 80 short and 24 long requests completed after funding confirmation. No warmups,
replacement of failed observations or prompt/rubric changes. The earlier account
failure on a subsequent case stays in the ledger, outside the matched completed set.

All paid requests use low reasoning, compact protocol, store=false and a 1024-token
output ceiling including reasoning (probe: 256). Every matched request has terminal
usage, completion and the requested effective tier; HTTP 200/response.created alone
is insufficient. UI API selection currently uses a 2048-token ceiling, so live cost
can differ. Input was identical across profiles: 28,684 reported tokens each.

A single manual review separates full/partial/wrong technical answers, decisions and
protocol failures. Useful timing is dispatch to the first complete validated record
containing engineering guidance, excluding acknowledgment-only lines, metadata,
unfinished fragments and failed decisions. Complete code records qualify. Timing
retains complete qualifiers; no extra classifier or speculative generation was added.
P90 is nearest rank. ASR and UI latency are outside these model timings. Runs were
sequential in one environment; provider load/cache state was uncontrolled.

| HTTP profile, low reasoning | Full / partial / wrong (27 actionable) | Decision failures (3 probes) | Useful median / p90 | Actionable completion median / p90 | Matched cost |
| --- | ---: | ---: | ---: | ---: | ---: |
| Luna Standard (`default`) | 25 / 2 / 0 | 1 | 2.054 / 3.143s | 2.760 / 4.120s | $0.006463175 |
| Luna Fast (`fast`) | 25 / 2 / 0 | 2 | 1.528 / 2.150s | 2.142 / 3.093s | $0.013113350 |
| Sol Fast (`fast`) | 25 / 2 / 0 | 2 | 1.529 / 1.953s | 2.749 / 3.146s | $0.198627000 |
| Sol Ultrafast (`ultrafast`) | 26 / 1 / 0 | 1 | 1.015 / 1.516s | 1.363 / 1.752s | $0.588921000 |

All 120 completed with **zero transport/protocol failures**. All four omit an explicit
UDP-datagram distinction in the comparison answer: useful but incomplete. Both Luna
pagination answers need stronger qualifications on their immutable-high-water-mark
alternative: it does not itself freeze updates/deletes. Sol Fast's long cancellation
answer adds an unqualified O(1) semaphore-bookkeeping claim; the runtime's
`asyncio.Semaphore._wake_up_next` scans waiters. The main cleanup advice is useful,
but that extra complexity claim needs qualification.

All profiles fail the direct unchanged-repeat probe by returning NEW; application
consecutive-repeat suppression remains separately tested. Luna Fast and Sol Fast
also prematurely answer the unfinished lease fragment. Both Standard Luna and Sol
Ultrafast wait correctly. None of these decision failures is counted as a fast useful
hint or silently relabelled a protocol failure. Corrections preserve UPDATE.

| Profile | Short useful median / p90 (21) | Longer useful median / p90 (6) | Output / reasoning tokens |
| --- | ---: | ---: | ---: |
| Luna Standard | 2.042 / 2.839s | 2.333 / 3.596s | 6,788 / 2,248 |
| Luna Fast | 1.528 / 1.782s | 1.536 / 2.150s | 6,975 / 2,525 |
| Sol Fast | 1.529 / 1.950s | 1.593 / 1.953s | 3,793 / 101 |
| Sol Ultrafast | 1.015 / 1.516s | 0.954 / 1.285s | 3,677 / 64 |

## WebSocket and recovery checks

A separate Sol low Ultrafast WebSocket check repeated 12 cases from the HTTP set:
correction, thread counter, idempotency, cache race, all six fresh/fragment cases, and
two longer-context follow-ups. All 12 completed at `ultrafast`, reusing the connection
11 times, with no protocol/transport failure; cost $0.1923666.

Ten actionable answers were fully correct and WAIT passed. One correction was graded
wrong: its Bellman–Ford instructions say to skip unreachable **endpoints**. Skipping
an unreachable destination prevents the relaxations needed to discover paths; only
an unreachable tail should be skipped. This is a technical-answer issue, not a
transport failure. One sample cannot establish that WebSockets cause such mistakes.

Across all 11 validated actionable records, median/p90 arrival was 0.721/1.214s;
this includes the wrong answer and is not a successful-quality latency claim. Across
the ten correct answers, useful median/p90 was 0.707/0.841s, with a 2.173s maximum.
The corresponding 11 HTTP cases had useful median/p90 1.015/1.128s and all were fully
correct. Different execution times/load and the smaller sample prevent a causal
transport ranking. HTTP remains recommended on the broader quality evidence; the
faster observed WS subset is an explicit experimental option, not a guarantee.

Five more ordinary-API WebSocket requests cost $0.081627: WAIT, NEW, UPDATE, UPDATE,
NEW. Three actual connection-local deltas and a deliberate clean close/reconnect
passed. Full state restored after reconnect; Java 8, multiple JVMs and prohibited
file-lock/external-service constraints survived. Four actionable answers were correct.
The final follow-up's NEW versus UPDATE is separate from a correction's required UPDATE.
This verifies short sustained API sequences, not an hour-long soak or forced revocation.

## Timing correction and remaining limits

The measured source was 0.1.3; prompts, parsing rules and publication are unchanged
in 0.1.4. Raw timing reconciliation exposed a telemetry bug: if the provider coalesces
header and answer into one delta, the pre-feed header check can miss first answer
content and record a later delta instead. Thus **the old first-answer-content-delta
field is not reliable for bottleneck attribution**. Validated complete-record callback
timings and completion/usage are independent and remain the basis of the tables.
Historical values were preserved, not silently repaired.

0.1.4 checks the retained candidate buffer after header validation and before marking
complete records. Three offline chunk-boundary regressions cover combined, split-header
and split-answer delivery; two fail on the old code, all pass with the fix. The change
also applies to WS through its shared parser path. First response-event medians were
0.424–0.456s across paid profiles; generation/validated-record completion still accounts
for most useful delay. Exposed reasoning events are incomplete evidence of internal
reasoning time. No paid rerun was needed to test the instrumentation correction.

81 CPU regressions pass. Local capture, ASR, saving, timeout isolation and account
pause safeguards are preserved. UI and prompt assets are unchanged from the prior
both-theme acceptance. Real revocation, the live 60-minute WS limit, Kraken GPU/audio/
hotplug/meeting/network checks and hosted CI remain unverified. No infrastructure or
model download was performed. Prior tags/releases and raw evidence remain preserved.
