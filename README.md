# Interview Helper

IH captures Linux desktop **playback**, transcribes it locally and streams concise
software engineering hints into a browser notebook. Use it for permitted assistance
or mock interviews. Microphones are excluded; transcripts represent captured playback,
not a complete two-sided conversation. Local ASR and continuous saving continue when
hint generation fails or the browser closes.

## Install and run

From a source checkout or extracted source release:

```bash
./start.sh
```

Requirements: Linux x86-64, Python **3.11–3.13** with venv/pip, `flock`, `pactl`,
`parec`, a working PulseAudio server or PipeWire PulseAudio compatibility service,
and an existing NVIDIA driver compatible with CUDA 12/cuDNN 9. Run as your desktop
user. IH never installs drivers or changes audio routing, firewall rules or system
Python. CPU development is explicit: `./start.sh --cpu` on a fresh configuration;
large-v3-turbo was slower than realtime on the development CPU.

The launcher checks prerequisites, reuses or creates `.venv`, installs pinned packages
only when needed, and prepares missing configuration. It privately prompts for a
missing API key in an interactive terminal, initializes the selected local ASR model
(missing weights download to `Models/`), then starts the backend and opens the local
UI. Subsequent runs reuse credentials, packages and model cache. Existing settings
and saved provider selections take precedence. Headless use: `./start.sh --no-browser`.
Missing credentials in noninteractive use fail with instructions instead of prompting.

The default local URL is **http://127.0.0.1:8787**. Press **Start session**, wait for
ASR readiness, then play permitted speech. **End session** flushes speech and saves
results; then Ctrl+C stops the backend. Closing the tab does not stop the session.
Keep the desktop awake and the terminal running. [Setup, key entry and upgrades](docs/INSTALLATION.md).

## Models, privacy and cost

Fresh configuration uses **ordinary OpenAI API · GPT-6.1 Sol · low reasoning ·
Ultrafast · HTTP · 1,024 output tokens including reasoning**, with local CUDA/float16
large-v3-turbo ASR. **Transcript context sent for hints leaves this computer for
OpenAI. API billing is separate from a ChatGPT subscription.** An existing authorized
key can be reused; IH never creates billing accounts or enables auto-reload.

Credentials stay backend-only in ignored private files. Inline endpoint key, configured
environment variable, then key file is the unchanged precedence. Never put keys in
browser storage, source, release assets or support logs. Model/processing tier access
depends on the account; the returned terminal tier is recorded separately from the
requested tier. No automatic provider, model or paid-tier fallback is introduced.

The recommended profile comes from the historical matched comparison: 26 full/one
useful-but-incomplete answer across 27 actionable cases; useful median/p90 1.015/1.516s.
These are dated results, **not latency or correctness guarantees for current prompts**.
[Evidence](docs/QUALITY_0.1.4.md). WebSocket transport remains experimental.

Optional OpenAI-compatible/LiteLLM text generation and app-owned ChatGPT subscription
sign-in remain available with their existing restrictions. Both have live historical
evidence; neither is selected automatically. Local GPU transcription remains essential
regardless of hint backend. [Configuration, optional routes and limits](docs/CLOUD.md).

Normal sessions have **no IH dollar cap or elapsed-time cutoff**. Provider spending,
credit and rate controls still apply. The separate cumulative US$5 development benchmark
ledger applies only to evaluation tooling; consuming it does not stop normal sessions.
This documentation preparation ran no paid inference. Three-hour synthetic operation
was validated earlier;
real GPU/meeting/provider endurance remains a separate acceptance task.

## Notebook and saved sessions

Hints progress **TL;DR → one clear implementation when useful → complexity and edge
cases → at most one short optional optimization**. Prefer the simplest correct approach
suited to actual requirements and bounds; explicit performance constraints take priority.
Follow-ups refine the same card and explain necessary changes of approach.
[Policy checks](docs/SOLUTION_SELECTION_0.1.11.md) are offline, not model certification.

Text streams as complete validated records; code appears only after complete response
validation. Malformed or stale output rolls back. **Review now** reconsiders accumulated
speech through the same request path. Dark/light themes, text size, paused following,
**Return to latest**, saved history and safe literal rendering remain available.

Finalized segments continuously save in `Transcribed/<session-id>/`: readable
`transcript.txt`, authoritative `transcript.jsonl`, separate `hints.jsonl` and metadata.
Custom paths are preserved. Live history retains 200 entries; full journals stay on disk.
Model context is bounded; overflow pauses hints visibly while transcript saving continues.
Storage errors pause capture and retain unsaved events for **Retry saving**. Do not exit
with unsaved data. Back up private configuration and complete session directories.

```bash
./run.sh recover SESSION_ID
./run.sh recover SESSION_ID --write-view  # New view; originals remain
```

## Troubleshooting and validation

- `./diagnose.sh` checks audio/compute and the selected model catalog; it makes no
  inference request. `./diagnose.sh --asr` explicitly loads/warms local ASR.
- Playback discovery errors identify the failed stage. Custom PipeWire mirroring may
  need explicit include/exclude patterns; physical microphones stay excluded.
- Model/authentication errors remain visible while transcription/saving continue.
  After an uncertain timeout, verify the server is idle before restarting; do not
  blindly retry or disable quarantine.
- Stop the backend before updating/installing. Existing `install.sh`, `run.sh` and
  `diagnose.sh` remain supported. [Checksum-verified update](docs/INSTALLATION.md#updating).

[Operations/recovery](docs/OPERATIONS.md), [architecture and cleanup decisions](docs/MAINTENANCE_0.1.11.md),
[validation history](docs/VALIDATION.md), [desktop smoke test](docs/INSTALLATION.md#desktop-smoke-test)
and [third-party attribution](THIRD_PARTY.md) describe the supported scope.
Offline checks use `.venv/bin/pytest -q`; development scripts are retained separately
under `scripts/`. Replay and summary commands can incur normal API charges; they are
not offline tests. Paid evaluation requires its separate ledger and authorization.

Source archives come from reviewed commits or release tags and exclude configuration,
credentials, models, environments, sessions and private validation artifacts. Wheels
include runtime resources and all bundled licensing notices. See
[licensing and provenance](THIRD_PARTY.md) and [source distribution](docs/DISTRIBUTION.md).
This preparation does not publish a repository, package or new application release.
