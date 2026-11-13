# Installation and desktop acceptance

From a source checkout or extracted release, run **`./start.sh`** in your own terminal.
See [README prerequisites](../README.md#requirements). The default is local CUDA ASR
and ordinary OpenAI API hints with separate billing. `--cpu` is for a fresh CPU
configuration; it never changes an existing ASR choice. `--no-browser` prints/serves the
local URL without opening a tab. No OS packages, drivers or audio settings are changed.

The launcher uses the existing installer, exclusive installation lock and shared
runtime lock. Before any IH import, the standalone bytecode helper fingerprints the
application source. Changed content invalidates only IH bytecode under the exclusive
runtime lock, including changes with identical file sizes/timestamps. Unchanged launches
keep their caches and do not trigger a reinstall. The direct `run.sh` path checks this
too, acquiring an exclusive lock only if invalidation is needed. Exact pinned dependency
checks avoid repeat installs. Package metadata
is refreshed only when its version or editable source differs. Existing config bytes,
credentials, connection preference, Models, .venv and Transcribed remain. Missing
configuration is copied from `config.example.toml`.

ASR preparation records successful warmup for the selected model/revision/cache/device/
compute configuration. It skips repeated warmup while that selection and cached weights
remain; session startup still loads the model and surfaces errors. Download failure or
unsupported compute stops preparation. The API key is not tested by making a paid call.
Use the catalog diagnostic and inspect the terminal effective tier of a permitted
ordinary-use response. The requested tier is not proof of provider acceptance.

## Secure key setup

`./start.sh` prompts privately only for a missing key on the selected ordinary API
profile. To prepare it separately after installation:

```bash
.venv/bin/python scripts/configure_openai.py
```

Enter an existing authorized API key at the hidden prompt. It writes ignored
`.local/openai-api-key` as mode 0600, refuses overwrite and makes no network or billing
call. Noninteractive entry is refused. Do not place secrets in shell arguments, source,
browser storage, deployment profiles, logs or release assets. Reuse an existing file.
Explicit endpoint key → its environment variable → key file is unchanged precedence.
`env -u OPENAI_API_KEY ./start.sh` deliberately avoids an inherited environment key.

Saved `.local/config.local-connection.json` takes precedence over TOML. A local or
ChatGPT selection never silently switches to the paid API. Missing saved subscription
credentials stop setup with instructions to use `./run.sh` and complete app-owned
sign-in. No configured local endpoints means transcription only. Unsupported or corrupt
configuration is reported; no migration removes integrations or discards user choices.

## Updating

End the session, wait for saving, then Ctrl+C the backend. Obtain the reviewed source
archive and its `.sha256` companion. Preserve earlier archives and any custom source
edits. A documentation-only snapshot of the same version does not require a runtime
update. For an application update, from the existing installation directory, substitute
the actual archive filename below:

```bash
(
  set -eu
  umask 077
  archive="$HOME/Downloads/interview-helper-<version>-<source-id>.tar.gz"
  expected_version="0.1.19"  # Set to the application version of the chosen release.
  test -f config.local.toml
  test -x .venv/bin/python
  test -f "$archive"
  mkdir -p .local
  exec 9>.local/runtime.lock
  flock -n 9 || { echo 'Stop the running IH launcher first.' >&2; exit 1; }
  (cd "$(dirname "$archive")" && sha256sum -c "$(basename "$archive").sha256")
  tar -xzf "$archive" --strip-components=1
  .venv/bin/python scripts/refresh_bytecode.py
  .venv/bin/python -m pip install --no-deps -e .
  .venv/bin/python -c 'import interview_helper, importlib.metadata, sys; assert interview_helper.__version__ == importlib.metadata.version("interview-helper") == sys.argv[1]; print(interview_helper.__version__)' "$expected_version"
  exec 9>&-
  exec ./start.sh
)
```

Check the printed version against the chosen release. The subshell must be a standalone
command: do not append `&& ./start.sh`, which can suppress Bash errexit inside it.
Close the update-lock descriptor only after checks pass; `start.sh` acquires its own
runtime lock. Keep the bytecode helper immediately after extraction while the lock is
held, before editable installation or any application import/version check. `python -B`
is not a substitute: it prevents cache writes, not stale-cache reads.

Build isolation may fetch the declared pinned build backend. The archive excludes
private config, keys, preferences, environments, model cache and saved sessions. The
launcher reuses them; it warms ASR once when its readiness marker is absent or the
selection changes. `./run.sh` remains the supported direct launch path.

No data/config migration is required for an existing Transcribed installation. If
an older installation still uses `.local/sessions`, stop IH and run:

```bash
.venv/bin/python scripts/migrate_sessions.py --config config.local.toml
```

It copies and verifies data, preserves originals and a private config backup, stops
on conflicting files and leaves custom paths unchanged. Resolve failures before
restarting. [Migration safeguards](OPERATIONS.md#session-migration).

## Browser upgrade behavior

After updating/restarting the backend, open or normally reload the page. HTML and all
private API/session data use `Cache-Control: no-store`. The HTML references content-
fingerprinted URLs for app.js, app.css and the early theme script. Matching assets may
be cached long term; changed bytes produce new URLs. The saved-session dialog shares
these same assets, with no separate archive HTML. No browser preferences are cleared
and an active page is never forcibly reloaded.

Controlled upgrade checks reproduced stale timestamp-based bytecode with same-size
source and matching timestamps, and verified warm-cache browser upgrades through a
normal reload. These controlled reproductions do not establish the cause of every historical
cache incident. See [upgrade validation](VALIDATION.md#duration-and-upgrades).

## Desktop smoke test

1. Start with `./start.sh`; confirm 0.1.19 and the intended provider/model/low reasoning/
   requested Ultrafast/HTTP, with 1024 brief / 2048 coding tokens by default. Existing alternate choices must remain selected.
2. Play permitted speech through both normal playback outputs. Confirm monitors only,
   local CUDA readiness, committed/provisional text, continuous saving and visible errors.
3. Exercise one coding problem: clarify update versus deletion, concurrency,
   duplicate names and index consistency, with a long pause. Expect one stable parent
   card, source-linked requirements, preserved code for prose follow-ups and explicit
   known-conflict/failure notices, without repeated freshness/language labels. Feedback about the candidate’s map must not invent unseen
   code or falsely replace a correct reference. End that task explicitly, then ask an
   independent diagnosis question; the prior code must remain accessible in history.
   With microphone sharing explicitly ON, ask “Should I use recursion?” during a
   subsequence task: main approach/code remain, only Latest follow-up answers the doubt.
   Add a real playback performance constraint and verify the main solution can update.
   Check short, nonduplicated notes, saving and visible microphone recovery status.
4. Check streamed TL;DR, validated code, Review now, both themes, paused following,
   browser refresh and saved-session downloads. End the session and inspect transcript.txt;
   restart and confirm saved provider, key and history remain.

This short test does not establish full GPU/meeting/provider endurance. Earlier
three-hour synthetic checks used simulated model I/O. Real desktop switching, driver
behavior, meeting applications, actual browser zoom and long-session behavior require
separate acceptance. [Validation](VALIDATION.md) distinguishes those scopes.

## Optional microphone acceptance

Recording and model sharing are separate idle-only choices, both OFF on fresh setup.
An upgraded recording preference is preserved with sharing OFF until explicitly enabled.
Live hints and Review now can share bounded support; replay and summaries stay playback-only.
No OS dependency is automatically installed for this feature. Existing native PipeWire
and WebRTC modules, `pw-cli`, `pw-dump`, `pw-cat` and session-manager linking permissions
are required. Microphone OFF does not invoke them. [Topology, recovery and troubleshooting](OPERATIONS.md#microphone-topology-and-diagnostics).

1. With microphone OFF, verify the existing playback transcript, hints, saving and lag.
2. End, enable **Include microphone transcript** with sharing OFF, start again. Confirm the selected input,
   speaker reference and listening state. Use brief permitted remote-only speech, local-only
   speech, overlap, then change speaker volume. Check for duplicated remote speech in the
   microphone text and lost/distorted local words. Source labels are not speaker identity.
3. Watch playback lag and GPU memory against the disabled baseline. Check explicit mic gaps
   on overload/unplug/reference loss; playback, hints and finalized saving must continue.
   With sharing OFF, mic speech must not revise hint cards. With sharing ON, a useful
   candidate question may update the active card on the existing lane, never create an
   unrelated task or replace interviewer constraints.
4. Collapse the initially expanded transcript while updates arrive; it must stay collapsed.
   Reload normally: expanded again, theme retained; size buttons continue to work. End, inspect combined
   transcript/download, stop/restart and confirm the microphone choice persists.
5. End, explicitly enable **Use microphone context for hints**, start a new session and
   establish a playback task. Ask a candidate question about it; expect focused supporting
   help without invented editor access. Ask a dry-run, then complexity: the latest follow-up
   replaces the previous one and preserves code. Waive exact separators: code should simplify.
6. During a brief supported input/reference interruption, expect one timestamped outage
   start and recovery (or unresolved end), not repeated transcript warnings. Inspect compact
   status and details, continuous saving and shutdown. Confirm meeting mic/default routes
   remain unchanged. If unsatisfactory, end and disable sharing/recording; playback-only
   behavior must return.

This short acoustic/GPU/desktop test is still required on the target. Development tests
used synthetic signals and CPU ASR historically; .18 adds an isolated real PipeWire
link/cleanup check and offline recovery/context/browser regressions. It does not repeat
acoustic/GPU/provider endurance or paid testing. If reader failures recur, collect the
[read-only scoped graph](OPERATIONS.md#microphone-topology-and-diagnostics) during the failure.
