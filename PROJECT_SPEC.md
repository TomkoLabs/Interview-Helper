# Interview Helper specification

IH is a Python/Linux application for permitted interview assistance. A localhost
browser controls a backend that owns capture, streaming recognition, question review
and durable storage even when the browser disconnects. Playback defines tasks.
Optional microphone recording and model sharing have separate default-off consent;
shared microphone text is subordinate supporting context.

## Capture and transcription

IH uses the PulseAudio protocol (`pactl` and `parec`), including PipeWire's compatibility
server. It discovers playback monitors, keeps per-source identity, reconciles hotplug
and suppresses known forwarding duplicates without changing routing or volume.
Module identity validation reconciles JSON with indexed short output, including
multiline native PipeWire arguments. PipeWire object IDs are not Pulse module indices.
Monitor relationships and properties are checked; physical inputs are not playback.
Malformed or conflicting topology remains a visible, stage-specific discovery error.

WhisperLiveKit LocalAgreement with faster-whisper supplies provisional and stable-prefix
text. The compatible CTranslate2 version is pinned; the fresh configuration uses CUDA
float16 large-v3-turbo. CPU int8 is an explicit development choice, never an automatic
fallback. One loaded model serves independent per-source recognition states. Queues
and retained audio are bounded; loss is reported, not hidden. Audio is not recorded.
[Operations](docs/OPERATIONS.md) describes scheduling, buffer and shutdown limits.

Optional microphone capture uses a separate native PipeWire/WebRTC monitor-mode AEC
client. One physical input and one directly routed physical output are required.
Only verified cleaned audio is published; there is no raw microphone fallback.
Capture continues during brief ASR deferral, with playback waiters prioritized on the
shared model. A slow native call retains its lane until actual completion; it is not
cancelled by a Python timeout. Only IH-owned processes/nodes are cleaned up.

## Review scheduling and context

The controller keeps one immutable active snapshot and one replaceable latest pending
snapshot. Live automatic hints and Review now share that lane and context builder.
Each explicit local host has one inference lock, including warmup. WAIT/IGNORE cannot
win a two-host race over an actionable peer. Normal incoming words do not cancel a
useful answer; correction epochs, request IDs and revisions reject stale output.
Timeout quarantine protects uncertain work. Cloud profile failures and account-wide
failures have separate scopes; see [connections](docs/CLOUD.md).

Finalized speech keeps verbatim segment identity, timing and revision provenance.
Global sequence/UUID identity coexists with playback and optional microphone review
coverage. Generated answers never become spoken evidence. Continuous review uses
pause, initial and maximum-delay triggers; it does not add a serial classifier.
Semantic decisions remain model-dependent. Successful acknowledgment-only review can
release reviewed segments, but cannot drop the first or requirement-linked segment.

Default recent context is 90 seconds / 6,000 characters. The active scenario can retain
16,000 characters / 512 segments independently of the recent window, with no silence
expiry. Overflow pauses hints visibly instead of discarding constraints. Shared mic
support is bounded to 12 segments, at most 1,500 characters (also at most one quarter
of configured recent context), within the recent window. Mic-only reviews cannot
create a task or replace interviewer requirements. Session boundaries clear derived
and connection-local context when consent changes. Replay and explicit summaries
remain playback-only.

## Answers, requirements and code

The default solution is the simplest correct, readable implementation suitable for
stated requirements and input bounds. Explicit performance constraints take priority.
Prefer Solution in brief, one complete readable implementation, actual complexity and
important edge cases, then at most a short useful optimization note. Java is the default unless another
language is requested. Optimization refines the same card when requirements change;
IH must not invent access to the candidate's editor or unseen implementation.

The typed streaming protocol accepts NEW, UPDATE, WAIT and IGNORE. A batch can contain
up to three separate tasks in chronological order, followed by one terminal record.
Required headers, action/revision/source references, complete qualifiers and record
bounds are validated. Complete useful text can stream before completion; code is
published only after full validation. Malformed, incomplete or stale responses roll
back drafts and retain prior complete guidance. Text is rendered safely, never as
raw HTML or hidden reasoning.

A coding task retains a stable parent, source-linked requirement changes and a separate
validated reference. Central requested operations must be implemented, not hidden behind
undefined helpers; code length follows the problem rather than a line-count target.
Bounds: 24 requirements including superseded entries, 280 characters per requirement, 8 patches per response and 8 source references per patch. Unknown
sources or supersession targets are rejected. Code is limited to 5,000 characters;
the protocol response is bounded to 12,000. Preserve/replace/invalidate/clear operations
make code changes explicit. Invalidating or clearing requires a reason; preserving
cannot repair an invalidated reference. Prose-only follow-ups keep valid reference code.

Main updates replace their supporting notes together. A follow-up-only update preserves
the main semantic state and has one replaceable follow-up of at most 360 characters with
1–8 source references. NEW does not inherit a previous follow-up. Mic uncertainty
normally updates only that follow-up; an independent correction needs an explicit reason.
New playback constraints can still change the main approach and code. Legacy one-line
notes retain complete qualifiers. Empty entries and duplicate presentation are filtered
without weakening response validation.

Brief ordinary-API requests use the configured 1,024-token default; substantive coding
requests can use 2,048. The heuristic considers active coding, explicit implementation
intent or substantial pending wording (40 words); it can over- or under-classify.
A transition request may still carry the prior coding allowance. Custom endpoint caps
are preserved and subscription restrictions are enforced. See [capacity configuration](docs/CLOUD.md#ordinary-api-key-and-processing-tiers).

## Storage and browser

Final transcript events synchronously fsync to an append-only journal. Hints and metadata
are separate, with a deterministic readable transcript and interrupted-session recovery.
Source labels identify capture channels, not guaranteed speakers. Legacy records without
a source kind mean playback. Journal failures pause capture for Retry saving; derived
readable-view failures preserve the journal and surface a separate error.

The plain HTML/CSS/JavaScript interface uses safe rendering and localhost Host/Origin,
cookie and CSRF protections. Live history is bounded; full journals grow on disk.
Live and archived cards share rendering and content-fingerprinted assets. A substantive
Latest follow-up precedes Solution in brief; initial answers have no follow-up section.
Code stays expanded, with safe lexical syntax colors and plain-text copying. Exact,
unique backtick expressions can mark lines and expose Show in code; ambiguous matches
are omitted. Unknown languages remain plain text. Unchanged answer regions retain DOM
nodes; a unique unchanged selection/reading line can survive code replacement.
HTML/private data are not cached; matching assets may be. Browser preferences, paused reading and
code anchors survive normal streaming/status updates. Loading a new page does not
force-reload another active page. See [installation](docs/INSTALLATION.md#browser-upgrade-behavior).

## Maintenance and validation

The one-command launcher is `./start.sh`. Ordinary API hints are the fresh default;
local-compatible, app-owned subscription and experimental WebSocket paths remain.
Model selection does not transfer capture, ASR or saving to the provider. GPU/physical
hotplug, meeting applications and provider endurance require target checks; fixtures
and simulated time do not establish those outcomes.

Run the existing offline suite and checks described in [validation](docs/VALIDATION.md).
Keep tests and scripts, prompt/resource files, licenses and executable modes in source
exports. Credentials, sessions, environments, models and operational evidence stay out
of Git. Preserve historical tags/releases. Use feature branches and reviewed merge
requests.
