# Operations and security

The launcher binds only IPv4 loopback. Allowed HTTP Host/Origin values match the
configured loopback port. API access requires an HttpOnly SameSite=Strict cookie;
mutations additionally require the exact origin and a per-process CSRF token.
Cross-site Fetch Metadata requests are rejected. No CORS is enabled. A restrictive
CSP blocks external scripts, framing, inline script and remote connections.
Model/transcript text is rendered through text nodes with a small inline-code
renderer, not HTML or an unsafe Markdown engine. Keys remain in the backend.

These controls defend against ordinary cross-site access/DNS rebinding. They do
not isolate other programs running as your Linux account. Use the normal private
logged-in desktop session. The default HTTP loopback connection is local; gateway
transport security depends on the configured endpoint and its network policy.

A playback source can queue 300 × 100ms PCM blocks, then stops and reports a gap. Independent
ASR state has a 30-second maximum retained audio window. Decoder inference is
serialized on one shared model. Silence uses a 300ms pre-roll plus one-second
hangover and decoder VAD. ASR/model work runs independently of browser polling.

The controller keeps one active snapshot plus one replaceable latest pending
snapshot. Each explicit host has one inference lock, shared with idle warmup.
Normal new words do not cancel an answer. Explicit correction/new-request cues
invalidate stale results. Stable instructions precede changing context. Recent
text, active scenario, output records and in-memory card history have explicit
bounds; the append-only journal may grow for the full session.

Every two seconds capture reconciles the current monitors. Known module graphs
avoid upstream/downstream duplicate capture where topology permits. Arbitrary
mirrors cannot be inferred perfectly. Optional microphone AEC independently reconciles
input/reference topology every 0.5s, two stable observations for name changes, and
2/4/8/16/30s retry backoff after failures. It does not
control screen/browser/meeting applications. [Microphone setup and acceptance](INSTALLATION.md#optional-microphone-acceptance).

Saving is synchronous and fsync'd per event so ASR cannot acknowledge unsaved
speech. Disk errors are visible and pause capture; failed records remain in RAM
for Retry saving. If a process is killed before a record commits, that last text
may be lost. If a write ends in a partial final JSON record, inspection ignores
only that incomplete tail. A corrupt complete record raises an error. A readable
recovery view deduplicates segment revisions and leaves all original bytes intact.

Unexpected termination leaves metadata `recording`; archive inspection labels it
interrupted when it is not the currently active session. It never silently resumes
microphone/playback recording on restart. Start a new session after inspection.
Back up the whole session directory, not only transcript.txt. Hint and summary
files contain generated content and must never be treated as spoken evidence.

Optional local chat-completions warmup uses a minimal real request through each selected explicit profile and the
same per-host lock. During an active session, idle maintenance runs approximately
every 75 seconds when there is no recent application work. It does not pin models,
change server TTL or override the host's coordinator. Other clients can still
cause unloading or contention. A disconnected client does not universally cancel
inference; default profiles drain unused results. Enable cancellation only after
verifying the actual backend. A timed-out noncancellable host is quarantined in
that app process until the operator verifies idle state and restarts the app.

Private data locations (`.local`, config.local.toml, Models, sessions, recordings,
logs, venvs and common credential/audio extensions) are ignored. Release archives
use Git's committed tree, never a filesystem-wide tar. Run privacy/history checks
before pushing new examples or validation evidence. Do not copy private benchmark
responses or real transcripts into generic source documentation.

## Session duration and cost

Use the [installation guide](INSTALLATION.md) for the key-free cloud profile,
private key-helper procedure, persistent connection preferences and desktop
acceptance. Normal sessions have no elapsed-time cutoff or IH dollar cap; the
US$5 evaluation ledger is separate. Preserve provider controls, request timeouts
and uncertain-request quarantine. Provider errors do not end transcription/saving;
storage failure intentionally pauses capture. Full journals grow on disk while
live history/model context remains bounded. See the measured/simulated distinction
in [validation](VALIDATION.md#duration-and-upgrades).

## Optional microphone operations

The two idle checkboxes persist recording and model-sharing booleans in ignored `.local/<config-stem>-capture.json`
(mode 0600, parent 0700), overriding `[capture] microphone = false` and `microphone_context = false`.
Old one-field preferences keep recording but default sharing OFF. Live hints/Review now
may use labelled mic support only with both choices ON. Replay and summaries remain
playback-only. Ending before a change ensures the next session has fresh cards/context
and a new transport; no shared mic material continues after disabling. To disable, end the
session, uncheck it, then start again. Preserve this file during upgrades. Backend-only
configuration may set the initial TOML value; no credential or provider selection changes.

Mic capture uses 20 × 100ms blocks and an independent LocalAgreement processor, sharing
the existing model. Playback waiters precede mic work. A busy lane defers mic recognition with a 0.5s
retry cooldown while verified capture continues. At 1.5s, a slow native operation changes
status to quarantined and retains the lock; there is no concurrent retry. Actual completion
permits recovery. A new session cannot load a second model while it drains. Capture has
a 2s queue; independent uncommitted recognition audio is bounded to 6s, plus 300ms pre-roll.
Before the six-second check, IH reclaims only already-finalized PCM using the existing
LocalAgreement boundary trim; committed speech no longer falsely counts as uncommitted.
Silence/unstable speech or starvation can still hit the limit. [Evidence and limits](VALIDATION.md#current-answer-and-microphone-checks).
Overflow explicitly discards audio, resets generation/history and opens a recognition gap;
results spanning the missing audio are discarded. No silence-based failure heuristic is used. Playback waits behind such a call are bounded to 3s and
report a capture gap if exceeded. This is a safety limit, not a zero-overhead guarantee.

Mic shutdown allows 2s for final text, then omits the tail with a gap. Owned reader/AEC
processes terminate with a 1s grace then kill; no unrelated nodes are removed. A small
standard-library owner watches backend-pipe EOF and reaps only its native AEC child
(with a 0.5s child termination grace), including unexpected backend exit. Source loss
invalidates mic output and buffers before reconfiguration. Ordinary playback flushing is
retained. A stuck native library may still require stopping the backend process; IH
does not promise native-call cancellation or GPU endurance.

A continuous outage has one journaled timestamped start, verified capture/recognition
recovery, or unresolved end. Brief scheduling deferral is not a capture gap. Last finalized
mic segment time is separate from link availability. Twenty recent diagnostic changes
are retained in memory, with at most one diagnostic journal record per minute and visible
retry counts. Old repeated un-timestamped mic warnings are deduplicated only in derived
readable views; authoritative historical journals are never rewritten.

The durable journal uses source_kind, sequence and UUID identity. Legacy records without
source_kind mean playback. Combined readable views rebuild on out-of-order finalization
and on close/recovery; the append-only journal stays authoritative. A view-write failure
leaves the journal saved and surfaces an error. Live history is bounded to 200 combined
events; full journal/recovery work is proportional to saved session size. Raw mic audio
exists only in bounded capture/recognition buffers, never saved by the application.

## Microphone topology and diagnostics

Supported input selection excludes monitors, virtual and remapped sources; physical
ALSA/Bluetooth inputs are eligible. IH retains a healthy selected input. The echo
reference is a sole eligible physical output with active uncorked playback, otherwise
the eligible desktop default. RUNNING alone does not prove active playback. Multiple
outputs, indirect/virtual routing or absent WebRTC support fail closed with a reason;
playback capture and hints continue. Plain PulseAudio supports playback only.

IH verifies cleaned-reader links before publishing PCM. Links may settle for three
seconds, with 100ms checks; name changes need two stable observations 0.5s apart.
Object ID and serial distinguish replacement from reuse. PCM before verification is
discarded. Retry backoff avoids rapid restart loops; loss invalidates the previous
source generation. Capture recovery does not prove recognized speech or acoustic quality.

During a visible reader failure, run from the installation:

```bash
umask 077
.venv/bin/python scripts/microphone_diagnostics.py > "$HOME/Downloads/ih-microphone-diagnostics.json"
```

This helper makes one read-only `pw-dump` call with a five-second timeout. It exports
IH nodes, immediate connected/target nodes, link states and selected identity/port
fields. It does not import IH, change routing, capture audio, read credentials/config
or export arbitrary client properties. Hardware names are local diagnostic data;
review before sharing. A snapshot without IH nodes may fall between retry instances;
one additional snapshot during the failure can help. It cannot establish acoustic
quality, native inference latency or the cause of meeting audio loss.

## Session migration

For older default storage, stop the session and backend before using
`scripts/migrate_sessions.py --config config.local.toml` with the project Python.
The helper holds the runtime lock, validates sessions and refuses symlinks/conflicts.
It copies and verifies files, retains the old readable bytes as
`transcript.pre-0.1.8.txt` in the copy and rebuilds the readable view. Only after
verification does it atomically change a legacy data directory to `Transcribed`.
A timestamped mode-0600 config backup remains in `.local`; originals are never deleted.
Identical repeat migration is safe, differing destinations fail without overwrite,
and custom storage paths remain unchanged. See [updating](INSTALLATION.md#updating).
