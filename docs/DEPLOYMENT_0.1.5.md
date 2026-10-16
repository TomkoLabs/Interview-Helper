# 0.1.5 deployment verification

October 14, 2026. Focused pre-Kraken configuration and endurance work; **no paid
inference or benchmarking**. The 0.1.4 quality/latency measurements remain historical,
not rerun. Real Kraken hardware, meeting and provider endurance are not certified.

## Verified configuration and spending boundary

`config.kraken.toml` is the portable, credential-free first-install profile:
ordinary OpenAI API, `gpt-6.1-sol`, low reasoning, requested `ultrafast`, HTTP,
`max_output_tokens=1024` (including reasoning), compact protocol, `store=false`,
120-second request deadline, no assumed cancellation. ASR is explicitly CUDA/float16
with the pinned large-v3-turbo revision. Existing installations/config files are
preserved by the installer; adopting the profile is an explicit deployment step.

The UI API selector now uses the same 1,024-token ceiling. Session pulse shows the
requested model/reasoning/tier/transport/ceiling. Completed-response diagnostics show
the returned model and tier. A creation-event echo is stored separately and cannot
masquerade as an effective terminal tier when that field is missing. Preserved 0.1.4
raw completed Sol results confirm `gpt-6.1-sol` / `ultrafast`; offline tests verify
serialization and deliberately different/missing terminal tiers. No new account
access or Kraken inference claim follows from these offline checks.

The only production consumer of `Budget` is `scripts/cloud_evaluation.py`. Session,
controller, gateway and summary code do not import/read its ledger. An offline
regression dispatches a normal request with an exhausted fixture ledger and forbids
any `Budget` construction; the request succeeds and the ledger is byte-identical.
Legacy benchmark, latency, scenario, race and audio-acceptance scripts now reject
ordinary API profiles before side effects, so a persisted paid default cannot
silently send unbudgeted evaluation requests. Subscription/local paths are retained;
authorized paid evaluation must use the cost-capped runner and original ledger.
The original cumulative US$5 evaluation authorization remains intact. Its historical
145 attempts remain $1.081281825 usage-priced cost plus $0.27608925 reservations.

There is **no app-enforced dollar cap for normal sessions**. Existing provider
credit, rate, project/account and subscription limits remain external controls;
IH does not change them or create billing settings. A displayed monthly budget
must not be assumed to be enforced. The tested output ceiling, bounded context,
serial requests, per-request deadline and no paid keepalive constrain work but are
not a session spending cap. Provider errors remain visible while transcription and
saving continue. Explicit summaries also use ordinary inference, outside the
benchmark ledger. The summary path now keeps its dedicated playback-only prompt
instead of letting the compact interview serializer replace it; selected provider,
tier, output ceiling and timeout remain intact. An offline request-level regression
covers this cloud-default deployment path without changing live-session behavior.

## Selection and credentials

Idle-only selections persist atomically in the ignored mode-0600
`.local/config.local-connection.json` beside the normal configuration. Alternate
config files use their own filename stem. Stored fields are only provider, account
registration identifier, model, reasoning, requested tier and transport. Credentials
are never serialized into this preference. Saved selection takes precedence over
TOML startup endpoints; explicit local selection survives a restart even if TOML
selects paid cloud. Invalid preferences stop startup with an error instead of silently
returning to a paid default. Rename the preference aside explicitly while stopped
to restore the TOML default.

Existing local endpoint configurations remain available. A cloud-first TOML can
retain up to two `[[local_endpoints]]` fallback tables, with `local_strategy` set to
`single` or `race`; no automatic fallback or credential substitution occurs. With
no local endpoints, choosing local is transcription-only. The original private
Kraken profile retains both existing local routes separately from the cloud default.

Use the existing hidden-entry `scripts/configure_openai.py` on Kraken. It accepts an
existing authorized key, writes `.local/openai-api-key` as 0600, fsyncs it, and refuses
to overwrite an existing file. No network call or billing action occurs. The
[Kraken checklist](KRAKEN_ACCEPTANCE.md) gives exact fresh-install commands and key
source precedence. Do not transfer development credentials or include `.local`,
`config.local.toml`, environment files or tokens in the source archive.

## Duration and recovery inspection

No elapsed-duration stop exists in the session owner, capture loop, recognizer,
controller, server or browser. A session runs until End session/backend shutdown;
browser refresh/disconnection does not own it. Startup/ASR failure, storage failure,
process termination and OS sleep remain real operational exceptions. Disk failure
intentionally pauses capture and retains unsaved content rather than claiming a save.

Committed stable prefixes and final flushes are journaled and fsynced throughout.
Live transcript/cards are bounded to 200 each, notices to 20, timing/publication maps
to 256, connection diagnostics to 64. Full journals grow on disk; opening/exporting a
saved session reads its full journal on demand. Recent model context is 90 seconds /
6,000 transcript characters by default; active scenario is at most 16,000 characters.
Overflow visibly pauses hints until an explicit question-context reset; it does not
stop transcription/saving or silently discard engineering requirements. Answers do
not become transcript context. Audio queues/uncommitted ASR buffers have 30-second
bounds; committed decoder prompt history trims to 256 tokens. Those are backlog
safeguards, not meeting-duration limits.

HTTP uses a reusable client; idle pool expiry opens a fresh connection on demand.
The API-key route has no app-imposed one-hour token refresh. Optional ChatGPT OAuth
checks expiry before requests, refreshes near expiry under a process-shared lock and
atomically retains replacement credentials. Terminal renewal failures require
sign-in; they do not end recording. This iteration does not perform real renewal
or revocation; prior renewal evidence remains dated in 0.1.3.

Optional Responses WebSocket rotates before dispatch at 55 minutes, before the
[documented 60-minute connection limit](https://developers.openai.com/api/docs/guides/websocket-mode).
Age, credential change and closed sockets discard connection-local continuation,
then use the full bounded app-owned snapshot. Explicit pre-generation
`previous_response_not_found` and connection-limit rejection recover once. Uncertain
post-dispatch disconnect/timeout is quarantined without replay; HTTP fallback is safe
only after a failed handshake. Connection recovery does not reset the Session,
active card, scenario or transcript. Continuation resets after four turns or when
serialized input reaches 24,000 characters; replaced/truncated context uses full input.

## Validation scope

101 CPU regressions pass, including five simulated session-level WS recovery modes,
provider-error persistence, timeout quarantine, paid-ledger isolation, key helper,
profile/selection persistence and installer preservation with stubbed pip/GPU tools.
These installer stubs do not certify a real Kraken installation or driver.
Both themes and browser refresh were visually inspected in an isolated synthetic
UI runtime. Explicit local selection survived an actual fixture-backend restart;
cloud selection and its requested settings were verified with a mocked catalog.

The three-hour wall-clock synthetic soak passed: **10,803.22 seconds, 2,157
finalized transcript events saved and recovered, 126 simulated provider failures,
180 live-journal checks, clean explicit shutdown and no partial journal tail**.
It ran October 14 from 18:53:13 to 21:53:16 UTC, using the production
session/controller/gateway/parser/journals and an in-process HTTP MockTransport.
Committed events arrived every five seconds; every seventeenth provider response
failed. Live transcript/cards stayed at or below 200 and context remained bounded.
Peak process RSS was 100,920 KiB (98.55 MiB), including repeated full-journal reads
by the test harness; this is not a fixed memory ceiling for arbitrary archives.
The harness explicitly requested shutdown after three hours; the application did
not stop itself. Cost was $0, with no real provider calls or benchmark-ledger changes.
Source hashes for the exercised session path stayed unchanged throughout. Separate
summary/evaluation guards were covered by the final regression suite. Two earlier
interrupted preliminary invocations are excluded from this duration result.
No audio, GPU, real provider, network or OAuth endurance is represented by this soak.
