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

A source can queue 300 × 100ms PCM blocks, then stops and reports a gap. Independent
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
mirrors cannot be inferred perfectly. No microphone, screen, browser or remote
meeting automation is present.

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

## Deployment and session duration (0.1.5)

Use the [installation guide](INSTALLATION.md) for the key-free cloud profile,
private key-helper procedure, persistent connection preferences and three-hour
acceptance. Normal sessions have no elapsed-time cutoff or IH dollar cap; the
US$5 evaluation ledger is separate. Preserve provider controls, request timeouts
and uncertain-request quarantine. Provider errors do not end transcription/saving;
storage failure intentionally pauses capture. Full journals grow on disk while
live history/model context remains bounded. See the measured/simulated distinction
in [deployment verification](DEPLOYMENT_0.1.5.md).
