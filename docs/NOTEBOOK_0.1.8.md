# 0.1.8 question, notebook and transcript acceptance

The user reports a successful seven-minute Kraken playback/ASR/hint run on 0.1.7
with Sol low / Ultrafast / HTTP / 1024. It produced 29 cards, including isolated
ASR fragments, and ended with `Invalid question`. This iteration uses offline
regressions and a synthetic browser fixture. No paid calls, model/ASR retuning,
audio configuration change or new three-hour soak was performed.

## Diagnosis and correction

The compact cloud prompt previously forbade a question heading. On NEW, the parser
substituted `PENDING_REQUEST_WORDING`; on UPDATE it concatenated the old heading
and new text. Replaying `of a memory allocation` through that parser reproduces a
fragment heading. A one-character residual reproduces `Invalid question`. These
are confirmed application paths; the original Kraken model responses/journals were
not supplied, so they cannot establish the exact cause of every observed card or
of that final error. A NEW decision still originated in the model, not the fallback.

Both protocols now require a concise faithful model-authored heading, with existing
strict action/heading/developing validation. Raw fragments are never substituted.
Bad model headings still fail visibly; they are not truncated or silently accepted.
Review journals record decision and heading origin. The cloud model, reasoning,
tier, HTTP transport and 1024 output ceiling remain unchanged. The additional short
heading costs output tokens; no new latency or quality measurements are claimed.

The single existing model review sees accumulated pending wording, retained scenario,
recent conversation and the active heading. Prompts explicitly recognize mixed
playback (both interviewer and candidate), candidate explanations, acknowledgments,
material continuations and a distinct contextual `Why?`. Microphone speech remains
unavailable. UPDATE replaces the same card's heading and answer using retained
constraints; WAIT/IGNORE publish nothing. After UPDATE the incomplete-wording prefix
is cleared; ignored commentary is removed from retained requirements but stays in
the recent conversation and journal. New topics replace the active scenario.

Only unambiguous filler/punctuation is suppressed locally. Narrow dangling phrases
such as `Explain the` or `Compare a list and` await more committed text. There is no
minimum word count, question-mark requirement, extra classifier or speculative call.
Semantic classification still depends on the model; scripted decisions do not prove
Sol will classify every real interview correctly. Existing request admission,
one pending snapshot, freshness, correction epochs, timeouts and context-limit
pause remain. Early complete answer records stream; prior useful answers remain
visible while updates validate. Beginning/constraints survive rolling-context eviction.

## Storage and readable text

New configurations default to `Transcribed/<session-id>/`, beside the config:
`transcript.txt`, `transcript.jsonl`, `hints.jsonl`, `metadata.json`. Custom `data_dir`
continues to win. Credentials and connection preferences stay in `.local` or their
existing explicit backend configuration. Both Transcribed and legacy private data
are ignored and excluded from source releases. Directories/files use 0700/0600.

Every committed transcript event still fsyncs to the authoritative journal with
exact timing, source identity, revision and commit metadata. A bounded incremental
readable writer joins fragments with spaces (without adding punctuation or words),
uses paragraph timestamps, and splits on source changes, pauses and longer completed
paragraphs. Gaps remain visible in order. Device names and generated hints are absent
from readable text. End session rebuilds the readable view from latest journal
revisions; downloads and Saved sessions use the same deterministic rendering.

A derived-view write failure does not duplicate a journal record or stop capture:
it surfaces a specific warning while journaling continues. End session retries the
view. Finalization failure remains visible with a download/recovery path; journal
failures retain the existing capture-pause/retry safeguards. An interrupted partial
last record is reported and excluded on recovery, never silently repaired in place.

Existing Kraken config is preserved by installation, so the update includes an
explicit [copy/verify migration](KRAKEN_ACCEPTANCE.md#updating-to-018-and-migrating-sessions).
Stop recording and the launcher first. The helper holds the runtime lock, validates
all sessions, refuses symlinks/conflicts, copies and verifies original files, retains
the old readable bytes as `transcript.pre-0.1.8.txt` in the copy, and builds clean text.
It verifies the complete destination before atomically switching only a legacy
`data_dir` to Transcribed. A timestamped mode-0600 config backup remains in `.local`.
Original session files are never deleted. Identical repeats are safe; differing
destinations fail without overwrite. A custom directory is reported and unchanged.

## Validation

- Full final offline suite: **130 passed**. Existing audio,
  cloud transport/reconnect, saving, summaries and protocol regressions remain.
- Scripted mixed-playback sequence: supplied fragments publish no cards; developing
  cloud reader, offline/identity, scale and deletion requirements revise one ID and
  answer; candidate explanation leaves it unchanged; `Why?` and a Python comparison
  create distinct cards. Long scenario keeps its beginning after recent-context eviction.
- Stale correction responses cannot publish over newer revisions. Strict malformed
  heading tests include the original fallback path. These are simulated decisions,
  not a new live-model quality benchmark.
- Transcript joining, revisions, gap order, exact journal retention, final flush,
  partial recovery, derived-view failure and finalization failure pass. Migration
  copies/permissions, repeat execution, collisions, copy failure, lock, symlink and
  custom-directory checks pass; migrated sessions load through Saved sessions/download.
- Browser synthetic 40→41 card checks: document height remains 1080 at 1920×1080 and
  2160 at 3840×2160; notebook and side panel scroll internally. Both themes, reload,
  paused following/new count/Return to latest and smaller 390×844 layout inspected.
  1280×720 logical viewport and enlarged answer text cover zoom-like layout pressure;
  the in-app shortcuts did not establish an actual browser zoom percentage. Check
  real 125–200% zoom on Kraken. No horizontal overflow observed on mobile.
- End session shows the readable path and download; an actual browser download
  contained the joined sample wording without device names. Saved sessions showed
  readable speech and generated hints separately.

Real Kraken playback with the revised prompt, speaker-role ambiguity, actual browser
zoom and sustained meeting/GPU/provider behavior remain target acceptance checks.
Prior audio and endurance evidence is preserved with its original scope.
