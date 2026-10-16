# Validation

## Current 0.1.2 iteration

See [the expanded quality, cloud and UI report](QUALITY_0.1.2.md). This iteration
removes the intro banner, evaluates existing coder/primary profiles on fresh and
longer-context cases, and adds optional app-owned ChatGPT Responses integration.
The user completed consent; live account models are verified. Existing local
defaults remain. 65 CPU regressions pass, including cloud terminal failures,
preview rejection, state/PKCE/signed identity, refresh serialization/rotation, terminal
credential clearing, revocation failure, quota pause and cross-site API guards.
Luna low/Sol low completed short-context tests; Luna none hit protocol failures and
a 120-second timeout, leaving two short cases and all cloud long-context runs unrun.
Real renewal/revocation and API-key inference remain unverified. Prior audio/GPU/
endurance limits are unchanged.

## Preserved 0.1.1 iteration

See [the balanced latency/quality and UI report](LATENCY_0.1.1.md). The existing
low-reasoning single-host default is retained; 44 CPU checks pass. IH branding,
dark-first persistent themes and the reproduced draining backlog correction are
validated separately from the preserved initial-release evidence below.

# Preserved 0.1.0 acceptance

Development acceptance was performed on ai-vm (Linux, Python 3.11, CPU),
October 14, 2026. This is not Kraken/GPU acceptance. Raw request/session evidence,
private aliases, host mappings and credentials are excluded from the repository.

## Local checks

- 41 CPU regressions pass: LocalAgreement/revisions; fsync journals, partial-tail
  recovery and disk failures; semantic scheduling, retained scenario bounds,
  exact repetition versus revisits, stale results and latest-pending bounds;
  strict protocol/truncation; race WAIT/actionable handling, no stream splicing,
  draining/host locks and supported mock cancellation; monitor topology and
  overflow; localhost API guards and backend lifecycle; bounded multipart summary.
- Ruff lint/format, Python compilation, shell/JavaScript syntax and `pip check`
  pass. A clean source installation and repeated install pass in a separate venv;
  configuration bytes and mode 0600 are preserved. An active launcher lock blocks
  installation. Built wheel includes UI, prompts and the reused Apache license.
- Browser runtime inspected at 3840×2160 and 390×844: at least five question
  headings visible in the populated 4K history, latest two answers expanded,
  scroll position/new count/Return to latest, refresh and archive access pass.
  No horizontal overflow or browser console errors were observed. Populated
  layout evidence uses an explicitly labelled synthetic fixture, not fake ASR.

## Real audio and gateway integration

An isolated PulseAudio 17/D-Bus instance passed real PCM monitor capture, device
addition/removal and loopback deduplication. Existing desktop routing and volume
were not changed. Combine/remap graphs and failure paths have synthetic coverage;
physical headset and target PipeWire graphs still need acceptance.

Real pinned `large-v3-turbo` CPU/int8 recognized the official Whisper 11-second
JFK test fixture correctly: 6.75 seconds load/encoder warmup, 61.40 seconds total.
This was slower than realtime. A separately synthesized 2.88-second engineering
question passed real playback → capture → streaming CPU ASR → authenticated model
→ durable session. It ended in 32.98 seconds with the complete punctuation-free
question, one saved card, no notices and all work flushed. The first attempt had
saved transcription but remained WAIT; fragment reconstruction and model settings
were corrected before the passing rerun. An actual post-session summary also
correctly described only stored playback and the missing candidate answer.
A separate real playback/CPU test with an intentionally unreachable endpoint
ended in 33.79 seconds, saved the complete question, showed `ConnectError`, and
flushed cleanly with no hint; model failure did not interrupt transcription.

The authenticated gateway exposed 18 aliases. Four existing models were examined
as a small shortlist; no exhaustive inventory benchmark or global routing change
was performed. Final paired comparison: six synthetic cases, two repetitions each
for primary, secondary and race, using identical prompts/cases. Every final
strategy passed 12/12 action/protocol decisions (36/36 total).

| Strategy | Median first useful answer | Median complete answer | Slowest observed request |
| --- | ---: | ---: | ---: |
| Primary, supported low reasoning | 1.332 s | 1.891 s | 21.892 s initial WAIT |
| Secondary coding model | 2.214 s | 3.608 s | 24.032 s initial WAIT |
| Two-host race | 1.153 s | 1.698 s | 3.667 s |

Latency medians include actionable cases only; WAIT has no useful answer. Metrics
measure HTTP submission through a validated complete sentence/bullet, not ASR or
end-to-end spoken latency. Runs were sequential with reused prefixes; cache/order
and model-loading state confound small differences. Native throughput and full
context capacity were not measured. **Single primary** is selected: race's modest
apparent gain does not justify routinely doubling work. A larger primary-host
alternative took 3.83–18.66 seconds for first useful scenario answers without a
clear correctness advantage. Hidden reasoning is omitted from display/storage.

Actual race observation selected the primary at 1.154 seconds first text / 1.771
seconds complete. The losing secondary remained locked/draining until 26.018
seconds total, then both locks released; only the winner's text was displayed.
Upstream termination on HTTP disconnect was not proven. Both real profiles keep
`cancel_supported=false`; the app drains, and timeout quarantines uncertain hosts.
Supported cancellation is verified only with the controlled transport fixture.

## Semantic and quality findings

Final real controller cases observed WAIT/WAIT/NEW for three fragments, NEW/UPDATE
for a material Java constraint, an explicit missing-spoken-answer acknowledgment,
a Perl compound answer, and IGNORE for quoted prompt injection. Immediate exact
repetition initially produced duplicate cards; the focused application check now
produces NEW/IGNORE/NEW/NEW across repeat, new topic and revisit (three cards).
A missing-answer follow-up sometimes classifies UPDATE instead of NEW; the useful
answer remains on the current card. Semantic classification is not infallible.

Action/protocol success is **not technical-correctness certification**. Early
runs omitted protocol fields, hallucinated candidate speech, recommended file
locks despite “without locks,” and overstated tuple hashability. The revised
prompt/context and low-reasoning profile improved these cases; source failures
remain in private evidence. Residual answers can still overstate Java shared-memory
capabilities, under-specify external side-effect atomicity, or make unsupported
Python performance claims. Hints require the candidate's technical judgment.

## Endurance and release

The actual wall-clock synthetic transcript/backend soak passed **3,603.99 seconds
(60.07 minutes)**, with **720 committed and recovered events**, 720 test-double
model calls, no partial journal tail, clean shutdown and **48,176 KiB peak RSS**.
Pending work sampled every five seconds was zero; separate regressions verify
active/pending bounds. It used a clearly labelled model test double, not live
GPU/audio/model endurance. It began before later context/card-limit/duplicate fixes;
final-source regressions qualify those changes separately rather than relabelling
the earlier running process. A separate
final-runtime check passed 300.26 seconds / 60 saved and recovered events, ending
cleanly with 48,316 KiB peak RSS. It is an additional five-minute check, not an hour.

GitLab CPU CI is configured but has not executed: project and instance runner
inventories were empty and pipelines remain pending. Local results above are not
hosted CI success. No runner or required merge gate was changed.

See [target acceptance](KRAKEN_ACCEPTANCE.md) for GPU execution, physical audio
switching, real meeting/window sharing, sustained lag/VRAM and network checks.
