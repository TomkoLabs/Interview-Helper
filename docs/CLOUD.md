# Inference connections

Integration evidence dated October 14, 2026; setup revised October 15. Local playback capture, ASR and saving remain local;
**cloud hints send bounded transcript context to OpenAI**. Fresh setup selects the ordinary API. Existing configuration is preserved. Selection is explicit, idle-session-only and persists across
restarts in a credential-free backend preference. A saved local choice overrides
a cloud TOML default. No automatic fallback between subscription and paid credentials occurs.

The recommended paid cloud profile is **GPT-6.1 Sol / low / Ultrafast / HTTP**.
The completed bounded comparison supports this choice; WebSocket remains experimental
because its smaller faster set included a wrong technical qualifier. The optional
subscription trial remains GPT-6 Luna / low / WebSocket. These are recommendations,
not speed guarantees; only a fresh configuration selects paid cloud by default. Read [0.1.4 results](QUALITY_0.1.4.md).

## App-owned ChatGPT sign-in

Official [overview](https://developers.openai.com/siwc/token-sharing-open-source) and
[private-client sessions](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions)
support this private locally hosted app without repository publication. Eligibility
is decided for the actual account/workspace. Development-account consent, JWT identity/scope, model catalog and inference were
verified for Luna and Sol. This does not establish access for another account.

1. Run IH and open **Model connection** while no session is active. Choose a saved
   account or **New account / workspace**, then **Continue with ChatGPT**.
2. Complete sign-in/consent yourself. The app uses its own dynamically issued client
   ID, PKCE, state, nonce and persistent opaque host ID; no other application's client,
   browser cookies or Codex credentials are used.
3. Return through `http://127.0.0.1:<port>/auth/callback`. The backend validates issuer,
   audience, signature, expiry, nonce, returning-account identity and granted scope.
   The ten-minute flow must complete in a browser on the backend host; this iteration
   does not create tunnels or transfer credentials to another machine.
4. Load account models, choose model/reasoning/transport, then **Use cloud · send
   transcript context**. Sign-in alone does not switch models. The catalog is checked
   again before selection; model/reasoning support is ultimately checked in inference.
5. **Use configured local models** restores local selection. End/save a session before
   changing connection. **Sign out selected account** attempts remote revocation and
   clears local tokens; remote failure is reported. Manage permissions/usage in
   [ChatGPT Usage](https://chatgpt.com/settings/usage).

`.local/chatgpt/` beside the configuration owns account files (0700 directory, 0600
atomic files). Refresh is serialized across processes with a file lock and preserves
the app-issued client ID. Normal expiry renewal was observed in 0.1.3: expiry
advanced without new consent and authenticated inference continued. Token-byte
rotation and real revocation were not independently tested; signed-fixture regressions
cover those paths. Terminal renewal errors require sign-in; temporary errors retain
credentials. Tokens stay backend-only and outside Git/shared backups.

## Ordinary API key and processing tiers

API billing is separate from ChatGPT plan usage. Use an existing authorized key;
IH does not create accounts, buy credits or enable automatic billing. Hidden entry:

```bash
.venv/bin/python scripts/configure_openai.py
```

The [installation guide](INSTALLATION.md) gives exact setup and precedence checks.
The user enters the key in their own terminal; it is saved only in ignored
`.local/openai-api-key`, mode 0600. An existing file is not overwritten. Alternatively,
set `OPENAI_API_KEY` in the backend environment. An explicit endpoint `api_key` takes
precedence, then the configured environment variable, then `api_key_file`. Do not
mix credential sources accidentally. No browser key-entry/storage mechanism exists.

Choose **OpenAI API key · separate API billing**, load models, then choose Standard,
Fast or Ultrafast. Only supported Sol models accept Ultrafast here. The app sends the
requested tier and records the **effective terminal response tier**; the Session
pulse labels the selection as requested, while completed cards show effective tier.
A 200 response or response.created echo is not proof of successful processing.
The API UI profile now uses the tested 1,024-token output ceiling, including reasoning.
Creation-event metadata is kept separately from effective terminal metadata.

[Fast](https://developers.openai.com/api/docs/guides/fast-mode) accepts `fast` (with
`priority` an equivalent provider alias). [Ultrafast](https://developers.openai.com/api/docs/guides/ultrafast-mode)
supports GPT-6.1 Sol through the ordinary API. Account access/rates can change; verify
current model catalog, completed response and [prices](https://developers.openai.com/api/docs/pricing).
The historical four-profile comparison and its accounting are recorded in
[0.1.4 results](QUALITY_0.1.4.md). Historical success does not establish current access
for every account or general correctness.

## Preview restrictions and transport

[SIWC preview](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)
uses store=false, an input array, instructions rather than a system-role input item,
and HTTP streaming. The subscription allowlist accepts only reasoning_effort; it
rejects incompatible caps, temperature, metadata and tier overrides explicitly.
Ordinary API permits reasoning, max_output_tokens and service_tier. No unsupported
field is silently dropped. Sol-none is rejected; explicit none/low is otherwise
account/model-dependent. Luna-none is not recommended after repeated failures.

[Responses WebSocket](https://developers.openai.com/api/docs/guides/websocket-mode)
uses an authenticated persistent connection, response.create without HTTP-only
stream/background fields, and store=false. One request runs per lane. Connection-local
previous_response_id is used only on that authenticated socket; HTTP always gets a
full bounded snapshot. Exact append-only inputs or verified growing application
transcript state can use deltas. Replaced/truncated context, four chained turns, or
24,000 serialized input characters reset continuation. Full application state is
retained for recovery; previous generated answers never become candidate speech.

Credentials are checked/renewed before each request. A changed token or connection
age of 55 minutes reconnects before the documented 60-minute maximum. Explicit
previous_response_not_found rejection rebuilds from app-owned context once. A
pre-generation connection-limit rejection reconnects once. A failed handshake can
fall back to HTTP because generation has not begun. A post-dispatch disconnect or
timeout is uncertain: close/discard the lane and quarantine that cloud profile;
**do not blindly replay it over HTTP**. Local host-wide timeout quarantine is unchanged.
Healthy cloud models/reasoning/tier profiles retain separate failure state. Account
quota/authentication failures pause the account across its profiles until resolved.

HTTP now drains terminal streams to EOF so the persistent pool reuses connections.
Strict NDJSON validates complete records before publication; generated question
metadata is replaced with app-owned question state in compact cloud mode. Failed,
truncated or stale answers roll back drafts; corrections retain old complete answers
until the validated replacement completes. Raw HTML/reasoning is never rendered.
Output after done remains an error, including duplicated provider answers. Usage is
retained after parser failure where the terminal response supplies it.

## Reproducible cost-capped comparison

`scripts/cloud_evaluation.py` uses the frozen rubrics and production serializer.
Without `--execute` it performs only catalog access and prints a cost plan. It keeps
a shared durable ledger, reserves conservative input/output cost **before** dispatch,
settles only from actual usage/effective tier, and retains full reservations when
usage is missing. Reasoning is already included in output tokens. Cache read/write
rates are accounted for. The hard cap is US$5 across the ledger, not $5 per run.
Legacy benchmark/latency/scenario/race/audio-acceptance scripts reject ordinary API
profiles rather than inheriting a paid deployment selection without accounting.
**This is evaluation-only.** Normal sessions and explicit summaries do not read that
ledger and have no app-enforced dollar cap. Provider credit/rate/project/subscription
controls remain applicable and unchanged. Output/context/request bounds are not a
session spending limit. See [deployment verification](DEPLOYMENT_0.1.5.md).
Do not delete or replace the existing ledger to continue this authorized comparison.

**No new paid evaluation is authorized by this cleanup.** Historical cumulative
receipts are retained privately; later authorized 0.1.9/0.1.10 work is recorded in
[LIVE_REVIEW_0.1.10.md](LIVE_REVIEW_0.1.10.md). Preserve the original ledger and cap;
normal user sessions are separate. Do not reset the ledger to obtain a fresh budget.

If a future account-credit error occurs, retain the sanitized provider error,
request ID and UTC timestamp. Check the matching Platform organization/project and
usage. Account pauses are held in the gateway/session; after the account issue is
resolved, end/restart the session (a CLI evaluator starts a new gateway). Do not
clear uncertain timeout quarantine without the separate idle/cancellation checks.
Only with authorization, make one small Standard probe using `--probe --execute`,
a new output filename and the same ledger. Close the catalog HTTP client and create
a fresh client first when verifying fresh-connection recovery. If the provider still
reports exhausted credit despite confirmed funds, stop and preserve evidence for
support rather than repeatedly retrying or requesting more funding.

`--transport websocket` selects the live-verified ordinary API WS path. Keep HTTP
available; never replay an uncertain post-dispatch request automatically. Additional
benchmarks require explicit scope and remaining-budget checks. Raw synthetic evidence
belongs in ignored `.local`, not Git; real interview content remains private.

## Optional OpenAI-compatible text generation

Local GPU transcription is independent of this optional hint backend. To deliberately
configure it, retain/replace `[[endpoints]]` in your private TOML, or add it as
`[[local_endpoints]]` to make it selectable alongside the API default:

```toml
[[local_endpoints]]
name = "Local gateway"
host_id = "host-a"
base_url = "https://gateway.example.invalid/v1"
model = "your-exact-catalog-alias"
api_key_env = "INTERVIEW_API_KEY"
timeout = 120
cancel_supported = false
[local_endpoints.parameters]
max_tokens = 4096
temperature = 0.0
```

Set the backend environment privately or use a protected endpoint `api_key_file`.
Do not paste credentials into commands or browser storage. Supported optional
parameters are `temperature`, `top_p`, `max_tokens`, `reasoning_effort` and
`chat_template_kwargs`; model-specific controls need independent validation.
Select **Use configured local models** while idle. With no local endpoints this
means transcription only. A selected gateway need not be physically local; review
its URL and data handling. There is no automatic fallback to paid OpenAI.

Two distinct host profiles can explicitly use `strategy="race"` (or
`local_strategy="race"` for local choices). This is a retained advanced feature,
not the recommendation: actual initial races showed draining losers and cache/order
confounding. Busy hosts are skipped; uncertain timeout quarantine remains. See
[LATENCY_0.1.1.md](LATENCY_0.1.1.md). Never enable it speculatively to chase latency.
