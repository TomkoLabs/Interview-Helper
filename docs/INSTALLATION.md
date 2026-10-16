# Installation and desktop acceptance

From a source checkout or extracted release, run **`./start.sh`** in your own terminal.
See [README prerequisites](../README.md#install-and-run). The default is local CUDA ASR
and ordinary OpenAI API hints with separate billing. `--cpu` is for a fresh CPU
configuration; it never changes an existing ASR choice. `--no-browser` prints/serves the
local URL without opening a tab. No OS packages, drivers or audio settings are changed.

The launcher uses the existing installer, exclusive installation lock and shared
runtime lock. Exact pinned dependency checks avoid repeat installs. Package metadata
is refreshed only when its version or editable source differs. Existing config bytes,
credentials, connection preference, Models, .venv and Transcribed remain. Missing
configuration is copied from `config.example.toml`; `config.kraken.toml` is retained
as a compatibility filename with identical settings, not a separate implementation.

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

End the session, wait for saving, then Ctrl+C the backend. Obtain the private release
archive and checksum in `~/Downloads`. Preserve any custom source edits. From your
existing installation directory:

```bash
(
  set -eu
  umask 077
  test -f config.local.toml
  test -x .venv/bin/python
  mkdir -p .local
  exec 9>.local/runtime.lock
  flock -n 9 || { echo 'Stop the running IH launcher first.' >&2; exit 1; }
  (cd "$HOME/Downloads" && sha256sum -c interview-helper-0.1.12.tar.gz.sha256)
  tar -xzf "$HOME/Downloads/interview-helper-0.1.12.tar.gz" --strip-components=1
  .venv/bin/python -m pip install --no-deps -e .
  .venv/bin/python -c 'import interview_helper; print(interview_helper.__version__)'
)
./start.sh
```

The block must succeed and print **0.1.12**. Build isolation may fetch the pinned
build backend. Runtime dependencies are unchanged. Nothing overwrites private config,
key, preferences, environment, model cache or saved sessions. On first use of the new
launcher, local ASR warmup runs once to establish its readiness marker, using cached
weights. `./run.sh` remains available for the established direct launch path.

No data/config migration is required for an existing Transcribed installation. If
an older installation still uses `.local/sessions`, stop IH and run:

```bash
.venv/bin/python scripts/migrate_sessions.py --config config.local.toml
```

It copies and verifies data, preserves originals and a private config backup, stops
on conflicting files and leaves custom paths unchanged. Resolve failures before
restarting. [Migration evidence](NOTEBOOK_0.1.8.md).

## Desktop smoke test

1. Start with `./start.sh`; confirm 0.1.12 and the intended provider/model/low reasoning/
   requested Ultrafast/HTTP/1024. Existing alternate choices must remain selected.
2. Play permitted speech through both normal playback outputs. Confirm monitors only,
   local CUDA readiness, committed/provisional text, continuous saving and visible errors.
3. Ask an unconstrained subsequence-counting question, then request fixed-string/no-rescan
   optimization. Expect simple two-pointer reasoning first and justified refinement of
   the same card. Large restrictive bounds should require a suitable optimized answer
   immediately. These remain real model acceptance checks.
4. Check streamed TL;DR, validated code, Review now, both themes, paused following,
   browser refresh and saved-session downloads. End the session and inspect transcript.txt;
   restart and confirm saved provider, key and history remain.

This short test does not establish full GPU/meeting/provider endurance. Earlier three-hour
synthetic checks used simulated model I/O; real desktop source switching, driver behavior,
meeting applications, model quality, actual zoom and long-session behavior remain separate
acceptance. No new paid benchmarking or endurance run is part of this release.
