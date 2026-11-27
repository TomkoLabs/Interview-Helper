# Changelog

Current behavior is described in [the specification](PROJECT_SPEC.md). Historical
measurements and their limits are consolidated in [validation](docs/VALIDATION.md).
Documentation-only maintenance does not change the application version.

## 0.1.20 — glanceable live hints, 2026-11-24

- Lead with Solution in brief; show one Latest follow-up above the retained solution.
- Ask for one lean, complete implementation and direct answers to concrete examples.
- Highlight code safely in both themes, copy plain text, and mark/jump to uniquely
  quoted expressions without changing syntax colors.
- Preserve unchanged code DOM, reading position and selection through hint updates;
  restore a uniquely retained selection across code replacement where possible.
- Reject follow-up records on initial answers; keep strict terminal-record validation.

## 0.1.19 — stable answers and concise follow-ups, 2026-11-12

- Preserve main answers/code for microphone follow-ups while allowing explicit corrections
  and meaningful playback constraints through the same validated inference lane.
- Replace supporting notes together; keep one concise Latest follow-up in live/saved cards.
- Preserve manual tail scrolling and trim finalized mic PCM before the six-second guard.

## 0.1.18 — recovery and follow-ups, 2026-11-04

- Bound reader settling, verify cleaned links and debounce/back off device recovery.
- Keep capture during brief ASR deferral; report timestamped outages and actual loss.
- Separate default-off mic sharing from recording; bound context and clear it across
  consent changes. Replay and summary remain playback-only.
- Add a replaceable Latest follow-up, concise foundations and compact Session pulse.

## 0.1.17 — optional microphone transcript, 2026-10-29

- Add default-off persisted microphone recording, stable physical input selection and
  native PipeWire/WebRTC monitor AEC without routing changes or raw fallback.
- Share one ASR model with playback priority, bounded mic state and visible gaps.
- Save chronological source-labelled transcripts; add a collapsible transcript panel.
  Model sharing was not yet supported in this version.

## 0.1.16 — upgrade freshness, 2026-10-26

- Invalidate only application bytecode on source-content changes before imports under
  the runtime lock, covering install/start/direct run and archive-update instructions.
- Fingerprint frontend assets, leave HTML/private APIs uncached, and preserve preferences.

## 0.1.15 — notebook polish, 2026-10-26

- Remove repeated retained-code/language captions while preserving conflict/failure notices.
- Make block code more compact without changing prose defaults or paused reading.

## 0.1.14 — readable coding references, 2026-10-26

- Prefer clear Java references with explicit assumptions and accurately labelled scaffolds.
- Give initial substantial implementation requests coding capacity; preserve profile settings.
- Resolve historical failure notices after successful review and anchor unchanged code.

## 0.1.13 — retained coding tasks

- Keep a stable parent, source-linked requirements and separate validated reference code.
- Add preserve/replace/invalidate/clear semantics; never assume access to candidate code.
- Use a bounded 2,048-token coding allowance with the standard 1,024 brief cap; preserve
  custom caps and subscription restrictions. Keep older journals readable.

## 0.1.12 — documentation correction

Restore an acceptance link and correct portable update instructions. Runtime, prompts,
defaults and dependencies are unchanged from 0.1.11.

## 0.1.11 — one-command startup and solution selection

- Reuse a pinned environment, privately configure missing API keys, prepare local ASR
  and preserve existing selections/data through one-command startup.
- Align fresh defaults on ordinary API; include all notices in wheels and pin setuptools.
- Prefer the simplest suitable readable implementation, actual complexity and edge cases;
  explicit bounds/optimization requirements override an inadequate baseline.

## 0.1.10 — structured live review

Consolidate the senior Java role, stable segment provenance, related follow-ups,
TL;DR-first code answers and optional Review now. Preserve validated code while new
guidance streams, bound final inference grace and record unreviewed shutdown tails.

## 0.1.9 — continuous review

Review verbatim committed speech with revision coverage and retained scenario context.
Remove local filler/dangling/repeated-word filters and IGNORE deletion. Add bounded
pause/initial/maximum-delay triggers and up to three answers per validated batch.

## 0.1.8 — question assembly and saved transcripts

Require concise model headings instead of raw fragment fallbacks. Keep the notebook
within the viewport with independent scrolling. Default storage to Transcribed, add
verified legacy migration and deterministic readable transcripts alongside exact journals.

## 0.1.7 — portable update procedure

Use the declared isolated build backend for updates, including fresh Python 3.13
environments without setuptools. Keep the 0.1.6 playback repair and runtime dependencies.

## 0.1.6 — PipeWire playback discovery

Reconcile JSON module names/arguments with indexed multiline short output. Validate
identities, monitor relationships and deduplication without admitting microphones or
conflating PipeWire object IDs with Pulse indices. Surface the failed discovery stage.

## 0.1.5 — persistent deployment settings

Add a portable key-free Sol low / Ultrafast / HTTP profile with a 1,024 output cap.
Persist credential-free provider choices and separate requested/effective tier metadata.
Keep evaluation budgeting independent of sessions and reject paid profiles in legacy tools.

## 0.1.4 — broader paid comparison

Recommend Sol low / Ultrafast / HTTP from matched quality/latency results. Validate
ordinary-API WebSocket reuse/reconnect and retain wrong answers separately from protocol
success. Fix first-answer telemetry for coalesced header/text deltas.

## 0.1.3 — cloud transport and recovery

Instrument response events, validated content, usage, tiers and UI acknowledgment.
Drain HTTP for reuse; add bounded persistent WebSocket continuation, rotation and safe
recovery. Compact cloud headers, push hint notifications and retain timeout quarantine.
Add backend-only API key setup, processing tiers and a cumulative evaluation ledger.

## 0.1.2 — compact workspace and optional cloud

Remove the decorative intro; retain controls/themes/history. Broaden quality rubrics,
separating incomplete/wrong answers from failures. Add app-owned ChatGPT registration,
backend credentials, account catalog and Responses streaming with explicit disclosure.
Enforce preview restrictions and keep ordinary API billing separate.

## 0.1.1 — themes and latency validation

Add persistent dark/light themes and compact branding. Skip busy race peers and obsolete
pending work; retain quarantine and queue timing. Add frozen technical rubrics and longer
context comparisons without trading away correctness for a sub-second target.

## 0.1.0 — initial release

Playback-monitor discovery/deduplication, LocalAgreement streaming, durable journals,
interrupted-session recovery, semantic hint control, bounded scheduling, localhost
notebook/history, isolated setup, diagnostics and offline/isolated acceptance tooling.
