# Interview Helper specification

IH is an independent Python/Linux application for permitted
interview assistance. A localhost browser controls a backend that owns capture,
streaming recognition, question scheduling and durable session storage even when
the browser disconnects. Playback/remote conversation only; microphones excluded.

## Decisions

- PulseAudio protocol (`pactl` + `parec`), including PipeWire's compatibility server;
  discover all monitors, retain per-source identity, reconcile hotplug, suppress
  known forwarding duplicates without changing routing or volume.
- Evaluate WhisperLiveKit LocalAgreement with faster-whisper; pinned compatible
  CTranslate2 4.7.2; CUDA float16 large-v3-turbo for the target, explicit CPU int8
  mode for development. No automatic CPU fallback. Bounded buffers and visible gaps.
- One loaded ASR resource, separate streaming state per monitor, stable-prefix
  delivery plus provisional text. Saving does not depend on inference gateway.
- Explicit OpenAI-compatible endpoint profiles; one host or two-host race; at most
  one request per host and one replacement pending snapshot. WAIT/IGNORE cannot
  win over an actionable peer. Typed streamed records, stale revision protection.
- Bounded recent context plus retained active scenario. Hints never become speech.
- Append-only transcript and hint journals, readable transcript, metadata,
  recovery of interrupted sessions, no audio recording by default.
- Plain HTML/CSS/JavaScript UI, safe rendering, localhost origin/host protections.
  Inspectable prompts and isolated installation. No new service/container stack.

## Validation and maintenance

Tests cover persistence/recovery/disk failures, revisions, question protocol,
scheduling/races/stale output, bounded context, source discovery and forwarding
deduplication, UI reconnect/history/scroll and failure visibility. Dated evidence
and limits are in [validation](docs/VALIDATION.md) and its versioned reports.
GPU performance, actual desktop hotplug, meeting applications and provider endurance
require target-hardware checks; synthetic fixtures do not establish those results.

The existing launcher is `./start.sh`. Ordinary API hints are the default; optional
local-compatible, app-owned subscription and experimental WebSocket paths remain.
[Cloud configuration](docs/CLOUD.md) explains their different contracts and limits.
Model choice does not change local capture/transcription or ownership of saving.

Use temporary feature branches and reviewed merge requests. Keep examples portable
and credentials, transcripts, environments, models and operational evidence out of
Git. Preserve historical tags and releases. Publication preparation follows
[the distribution procedure](docs/DISTRIBUTION.md); there is one maintained source
implementation. Original version-specific delivery instructions are preserved in
private workspace documentation; [CHANGELOG](CHANGELOG.md) and technical reports
retain the useful public change history.
