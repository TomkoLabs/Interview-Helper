# Interview Helper

**IH is a real-time technical interview assistant.** It transcribes Linux desktop
audio locally and uses LLMs to provide concise software engineering hints and code
examples in a browser notebook. Use it for mock interviews or conversations where
assistance is permitted.

## Install and run

Download and extract the source, or clone the repository. From the project directory:

```bash
./start.sh
```

On first launch, IH prepares its Python environment, downloads the transcription
model, prompts for an OpenAI API key if needed, and opens the browser. Later launches
reuse your settings, credentials and downloaded model.

**Requires:** Linux x86-64, Python 3.11–3.13 and a compatible NVIDIA GPU setup.
See [requirements](#requirements) below for system prerequisites.

The default interface is **http://127.0.0.1:8787**.

## Using IH

1. Click **Start session** and wait for transcription to become ready.
2. Join your call or play practice audio. IH captures desktop playback automatically.
3. Read the live transcript and notebook hints as the conversation develops.
4. Click **End session** to finish and save. Press **Ctrl+C** in the terminal to stop IH.

Closing the browser tab does **not** stop the session. Keep the computer awake and
the launcher running while recording.

## What you get

- **Concise answers:** a short explanation, key points and readable code when useful.
- **Ongoing problem context:** related questions refine the same card and preserve
  the reference solution. Independent questions get separate cards.
- **Latest follow-up:** brief help with the newest subquestion, without replacing
  the main answer unnecessarily.
- **Hands-free operation:** automatic reviews, plus an optional **Review now** button.
- **Readable workspace:** dark/light themes, adjustable text size and independently
  scrolling notebook and transcript panels.
- **Continuous saving:** finalized transcripts remain saved even if hint generation
  fails or the browser closes.

Java is the default language for coding examples; an explicit request for another
language takes precedence. AI-generated hints can be incorrect—review the reasoning
and code.

## Optional microphone

Playback-only is the default. While no session is running, enable:

- **Include microphone transcript** to record your side of the conversation locally.
- **Use microphone context for hints** to also send relevant microphone text to the
  selected model.

These are separate choices. Microphone comments normally guide the brief follow-up;
interviewer questions remain the focus of the main solution.

Microphone capture requires a supported PipeWire echo-cancellation setup with one
directly routed physical output. Plain PulseAudio supports playback capture only.
Unsupported microphone setups show a reason while playback and hints continue.
Overlapping speech may reduce transcription quality. Playback/Microphone labels
identify audio sources, not guaranteed speaker identities.

See [microphone setup and troubleshooting](docs/INSTALLATION.md).

## Privacy and cost

- **Audio is transcribed locally.** IH does not save raw audio recordings.
- **Hints use the selected model.** With the default OpenAI API connection, playback
  transcript context is sent to OpenAI. Microphone text is included in live hints
  only when its separate sharing option is enabled.
- **API billing is separate from ChatGPT subscriptions.** Normal sessions have no
  IH spending cap or automatic duration limit; provider quotas and charges apply.
- **Credentials stay on the backend.** Keep API keys and saved sessions out of Git
  repositories and public uploads.

Optional OpenAI-compatible/LiteLLM backends and ChatGPT sign-in are also supported,
subject to their documented requirements. See [model configuration](docs/CLOUD.md)
for defaults, processing tiers and alternative connections.

## Saved sessions

Open **Saved sessions** to review previous work or download a readable transcript.
By default, each session is saved under:

```text
Transcribed/<session-id>/
```

The directory includes `transcript.txt`, the detailed transcript journal, hints and
session metadata. Custom storage paths are supported.

If saving fails, resolve the problem and use **Retry saving** before exiting.
See [operations and recovery](docs/OPERATIONS.md) for recovery instructions.

## Requirements

- Linux x86-64 with Python **3.11–3.13**, `venv` and `pip`.
- `flock`, `pactl` and `parec`.
- PulseAudio, or PipeWire with PulseAudio compatibility.
- An existing NVIDIA driver compatible with **CUDA 12 / cuDNN 9**.
- For optional microphone capture: PipeWire native monitor-mode WebRTC echo
  cancellation, its SPA library, `pw-cli`, `pw-dump`, `pw-cat` and appropriate
  session-manager permissions.

Run IH as your normal desktop user. The launcher does not install GPU drivers or
change system audio routing.

CPU mode is available for development with `./start.sh --cpu` on a fresh
configuration, but may be too slow for live transcription. To launch without opening
a browser, use `./start.sh --no-browser`.

## Troubleshooting and documentation

```bash
./diagnose.sh        # Check audio, compute and the selected model catalog
./diagnose.sh --asr  # Also load and warm up local transcription
```

Stop IH before installing an update. Follow the
[update instructions](docs/INSTALLATION.md#updating) to preserve settings and sessions.

- [Installation and setup](docs/INSTALLATION.md)
- [Models and cloud connections](docs/CLOUD.md)
- [Operations and recovery](docs/OPERATIONS.md)
- [Validation and known limitations](docs/VALIDATION.md)

## License

IH is provided under the [MIT license](LICENSE), with bundled components carrying
their own notices. See [third-party attribution](THIRD_PARTY.md) for the full licensing
details.
