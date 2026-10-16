# 0.1.1 latency and quality evaluation

October 14, 2026, development machine only. **Retain the existing single-host,
low-reasoning default and unchanged production prompt.** Non-thinking Flash Next
was faster, but failed a fragmented question and repeated an invalid inter-process
counter recommendation. No tested configuration established reliable sub-second
useful answers. Exact authenticated aliases, live mappings, raw responses and
per-response manual grades are in the private operational evidence, not this tree.

## Method and effective controls

The authenticated inventory contained 18 routes. Five installed checkpoints were
screened in nine configurations; no model download, runtime upgrade, cache setting,
global gateway routing or model-host configuration changed. Read-only live mapping
inspection linked the primary Flash Next/27B profiles to oMLX 0.7.0 physical MLX
checkpoints and the secondary 27B/coder/35B routes to managed native Ollama 0.33.1
GGUF tags. This is deployed-system comparison, not parameter-count or hardware ranking.

The technical facts/rejections in [the cases](../tests/fixtures/latency_cases.json)
were frozen before inference. Two screening questions were separate from ten
held-out cases: eight actionable engineering scenarios, an incomplete WAIT and
an unchanged repetition. The production prompt and snapshot serializer were used,
including active question, accumulated requirements, missing candidate speech and
recent playback. Each configuration ran forward then reverse profile blocks with
an explicit warmup per block. Held-out cases ran twice with a shared system prefix
and twice with a unique first-system prefix. A separate longer
[playback context](../tests/fixtures/latency_context.txt) repeated four existing
rubrics for the baseline and non-thinking finalist, again in opposite orders.

- Screening: 54 requests, including 18 warmups; four actionable samples/profile.
- Held-out: 132 requests including 12 warmups; 40 assessed requests/profile,
  of which 32 are actionable (eight unique questions, four repetitions).
- Longer context: 20 requests including four warmups; eight actionable/profile.
- Rendered prompt telemetry: approximately 1,358–1,600 tokens in the first passes;
  1,859–1,988 in the longer-context pass. Recent playback was about 1.5K versus
  4K characters. This does not test the maximum retained-scenario/context capacity.
- Every request had a unique snapshot ID and prompt hash (206/206 distinct).
  Gateway response caching was not enabled in the inspected configuration;
  no cache-hit header was observed. Generation usage and streamed deltas were
  present. Deterministic identical text is not treated as evidence of response caching.
- Primary runtime prefix caching was configured, but every returned primary
  `cached_tokens` counter was **zero**. Secondary responses did not expose a useful
  prefix-hit counter. Shared versus changing prefixes therefore establish no
  measured prefix-cache benefit; no cache setting or prefix-reordering change was made.
- All profiles used temperature 0. Low reasoning used 4,096 output tokens;
  non-thinking and native coder/35B/27B trials used 1,024. The concise variant
  appended a generic request for a short opening and two compact bullets without
  removing any question requirements. Every scored stream finished with `stop`,
  with at most 342 completion tokens observed; no reasoning-budget truncation was hidden.
- Primary thinking was controlled with `chat_template_kwargs.enable_thinking` and
  supported `reasoning_effort=low`. Emitted reasoning character counts were zero
  for off profiles and nonzero for low profiles. Installed policy/template merging
  was inspected. Critically, `reasoning_effort=none` returned HTTP 200 but the gateway
  treats it as unspecified and restores its configured default; it does **not**
  disable thinking. `minimal` returned the expected HTTP 400 rejection. Both probes
  are preserved outside the scored latency samples. Native secondary routes already
  forwarded `think=false`; unsupported template flags were not added to them.

Timing starts at client model-request dispatch and ends at the first validated
complete useful sentence/bullet. Headers, WAIT, reasoning and missing-answer
acknowledgments are excluded. For missing-speech follow-ups, the first actual
engineering bullet is timed using per-line arrival records. Completion is reported
separately. Local host-slot waiting is recorded separately as `queue_seconds`.
There is **no speech-to-hint claim**: capture, ASR, scheduling and browser polling
are outside these metrics.

Manual technical review used the frozen expected facts/rejections, with three
categories: full coverage/no identified material issue, useful but incomplete or
qualified, and technically wrong. These are one reviewer's judgments, not an
independent certification. Repeated answers are not independent new questions.

## Screening

All 36 actionable screening streams passed protocol/action checks. No answer was
under one second. P90 is nearest-rank; with n=4 it is simply the observed maximum.
Quality counts are full / partial / wrong, distinct from protocol validity.

| Configuration | n | First median / p90 (s) | Complete median / p90 (s) | Quality |
| --- | ---: | ---: | ---: | ---: |
| Primary Flash Next low, baseline | 4 | 1.985 / 2.068 | 2.553 / 2.886 | 2 / 1 / 1 |
| Primary Flash Next off | 4 | 1.100 / 1.179 | 1.598 / 1.663 | 2 / 2 / 0 |
| Primary Flash Next off, concise | 4 | 1.053 / 1.171 | 1.536 / 1.612 | 2 / 0 / 2 |
| Primary Flash Next low, concise | 4 | 1.568 / 1.854 | 2.119 / 2.488 | 2 / 2 / 0 |
| Primary 27B off | 4 | 3.297 / 3.617 | 5.954 / 6.327 | 2 / 2 / 0 |
| Primary 27B low | 4 | 7.552 / 8.026 | 10.316 / 11.334 | 1 / 3 / 0 |
| Secondary 27B, native off | 4 | 4.675 / 4.978 | 9.937 / 10.026 | 2 / 2 / 0 |
| Secondary coder, native off | 4 | 2.634 / 2.941 | 4.037 / 4.740 | 4 / 0 / 0 |
| Secondary sparse 35B, native off | 4 | 1.969 / 2.100 | 3.202 / 3.241 | 2 / 2 / 0 |

Screening exposed unqualified expected-versus-worst-case hash complexity, an explicit
false worst-case claim, and misleading duplicate-value map guidance in the concise
off variant. The coder passed these two technical rubrics but was slower. Warmups
ranged 0.695–26.037 seconds and are preserved separately; initial model loading or
switching must not be confused with steady request latency.

## Held-out results and decision

All three finalists had 36/40 expected decisions and zero transport/protocol
failures. Each returned NEW for all four direct-model duplicate probes. Production
exact-repeat suppression was separately verified through the real controller.
All incomplete WAIT and material UPDATE probes passed this isolated snapshot pass.

| Configuration | Useful n | First median / p90 (s) | Complete median / p90 (s) | Full / partial / wrong | Under 1s |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline low, retained default | 32 | 1.822 / 2.407 | 2.599 / 2.960 | 20 / 10 / 2 | 0/32 |
| Off | 32 | 1.136 / 1.213 | 1.555 / 1.677 | 20 / 12 / 0 | 1/32 |
| Low, concise | 32 | 1.773 / 2.318 | 2.271 / 2.873 | 18 / 11 / 3 | 0/32 |

The single sub-second off answer was a partially qualified response, so **zero
fully satisfactory actionable responses met the target**. The off follow-up's
fast missing-answer acknowledgment was not counted as engineering help.

Shared-prefix versus changing-prefix first medians were 1.912/1.793 seconds for
baseline, 1.074/1.187 for off, and 1.855/1.683 for concise low (n=16 per cell).
Warmups in these passes ranged 0.704–1.216 seconds. Profile order
was balanced within each pass, but the shared-prefix pass preceded changing-prefix;
these small differences do not establish a causal caching effect.

Longer-context results: baseline first 2.354/p90 2.651, complete 2.956/p90 3.494
seconds; off first 1.167/p90 1.357, complete 1.730/p90 2.100 (n=8 each). No sub-second
answers or transport/protocol failures. Baseline quality was 6 full/2 partial/0
wrong; off was 2/4/2. Off invented a `Queue.join` timeout and incorrectly advised
requiring a nonempty queue before joining. Both shorter-context reasoning variants
also sometimes invented `Queue.join(timeout=...)`; the installed signature is
`(self)`. Other qualifications include blanket `unique_ptr` zero-overhead claims,
missing explicit node-identity wording and overstated coordination-free ID allocation.

Real controller sequences, using new synthetic playback wording, provided the
selection-critical difference:

- Baseline fragments: WAIT / WAIT / NEW. Off: WAIT / NEW / UPDATE, prematurely
  answering the unfinished “difference between TCP and” fragment.
- Both: NEW / UPDATE after negative-edge correction; NEW / application IGNORE /
  NEW / NEW for exact repeat, different topic and genuine revisit. Both acknowledged
  missing candidate speech in follow-up answers.
- The prior Java 8/multiple-process/without-locks regression again exposed off
  recommending file locks and treating `AtomicLong` as a mapped inter-process
  counter. Baseline also retained unsupported portability/lock-free assumptions
  around `Unsafe` and external atomic services; it is not certified correct.

Retain baseline settings and production prompt. Off is a documented optional trial,
not a quality-equivalent replacement. No new dual-host race was justified: screened
secondary candidates were slower, and racing would add work/draining without evidence
of reliable sub-second quality. The existing optional coder peer remains available.
Historical 0.1.0 medians (1.332/2.214/1.153 seconds primary/secondary/race) used other
questions and sequential reused prefixes, and are **not** comparable performance
regressions or current race measurements.

## Queue correction and validation limits

A controlled transport reproduced eight queued/draining loser tasks after eight
successive races. The fix admits idle hosts only, skips busy peers, and rechecks
snapshot freshness while all selected hosts are busy and immediately before
transport dispatch. The regression now observes one draining request and one peer
invocation. Superseded waiters never dispatch. Queue and generation timing are separate.
An already-running noncancellable request may still occupy its host up to its existing
120-second timeout; timeout quarantine is preserved. Upstream cancellation remains
unverified. This removes accumulated obsolete work, not the latency of one active job.

44 CPU regressions pass, including new backlog, freshness and timeout checks. Browser
checks cover dark-first appearance, light/dark reload and newly opened-page persistence,
IH title/header, keyboard toggle/focus, archive, transcript, staged fixture streaming,
new-question count and unchanged history position at 3840×2160 and 390×844. No horizontal
overflow or console errors were observed. A blocking external head script and dark
HTML/CSS defaults avoid a light first-use flash. Local storage contains only the theme
preference. A full desktop-browser process restart was not automated; persistence uses
standard durable local storage and was checked across reload/new page creation.

No new audio/GPU/endurance certification is claimed. The retained 0.1.0 evidence is in
[VALIDATION.md](VALIDATION.md); [Kraken acceptance](KRAKEN_ACCEPTANCE.md) still requires
CUDA/VRAM, actual audio routing/meetings, sustained live operation and network access.
