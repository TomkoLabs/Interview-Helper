# 0.1.11 focused maintenance review

October 15, 2026. Ordinary OpenAI API remains the primary supported hint route:
Sol / low / Ultrafast / HTTP / 1024. Local playback capture, GPU ASR, continuous
saving, protocol, context and model settings are preserved. The companion
[solution-selection change](SOLUTION_SELECTION_0.1.11.md) favors clear, suitable
baselines while respecting explicit performance bounds. No new paid evaluation.

## Architecture and retention decisions

Inspected entrypoints, configuration/preference resolution, UI controls, controller,
protocol, audio/ASR/storage, inference/authentication/transports, scripts, tests,
dependency metadata and historical reports before choosing changes.

| Component | Decision and evidence |
| --- | --- |
| PulseAudio/PipeWire capture, local faster-whisper/LocalAgreement, journals/recovery | Essential; preserve. Playback-only topology and source identity regressions remain. |
| Ordinary Responses HTTP | Primary; shared strict protocol/controller. 120 matched historical API cases in 0.1.4; not a new-prompt quality guarantee. |
| OpenAI-compatible/LiteLLM text generation | Retain optional: actual playback→CPU ASR→gateway→saved hint plus 152 broader requests in 0.1.2. Small shared serializer/stream path, explicit endpoint use case. |
| App-owned ChatGPT subscription | Retain optional: real account/auth/catalog, 90 matched 0.1.3 requests, subsequent bridge/reconnect/normal renewal evidence. Auth machinery is necessary for its separate contract. Real revocation remains unverified. |
| Two-host racing | Retain advanced compatibility, not recommended: actual 0.1.0/0.1.1 tests exposed draining losers; corrected idle-host admission/quarantine has regressions. It is not speculative unused code; removing it would disrupt existing explicit local choices without simplifying the main path. |
| Responses WebSocket | Retain experimental: live continuation/reconnect evidence and offline rotation/recovery checks; smaller paid set included a wrong qualifier. HTTP stays default. |
| Evaluation/diagnostic/replay/migration/recovery scripts | Retain useful development/operational tools separately from normal setup. Paid guards/ledger remain. No redundant untested provider was identified for deletion. |

No runtime integration or configuration field was removed. Therefore no provider
migration, private-config rewrite or automatic paid substitution is needed. No extra
machine was accessed to justify retention. Historical measurements remain in their
versioned reports with their original limitations.

## Simplification

- One recommended `./start.sh` delegates to existing install/run scripts and locks.
  Read-only platform/Python/audio/GPU prerequisites, exact installed-pin checks,
  missing config/key handling and cached local ASR initialization replace manual
  first-run orchestration. Old commands remain.
- One portable API default template; old target-profile filename remains a compatible
  copy. Saved preferences and credentials keep their precedence.
- Concise README plus portable installation and connection guides. Target-machine
  operational notes are preserved privately; old acceptance filename/anchors remain
  as links. Historical evidence is not relabelled current validation.
- Wheel metadata now carries existing project/vendor license and attribution notices.
  Existing license text is preserved pending provenance review.
- Fresh bootstrap exposed CTranslate2's previously unpinned `setuptools` dependency.
  Pin it to **79.0.1**, the existing development runtime version; build isolation still
  uses the already pinned **80.9.0**. No other dependency version changes.

## Validation and limits

162 offline regressions pass, including policy routing/refinement, saved connection
selection, key precedence, noninteractive failure, cache invalidation, shell startup,
installer locking and private-state preservation. Full style/format/dependency,
compile and shell syntax checks pass. Isolated bootstrap created a real Python 3.13
venv, installed declared dependencies and served the real local UI; audio server and
ASR initialization were explicitly simulated. The discovered transitive pin was then
corrected and verified. Repeat launch skipped installs and warmup; source upgrade preserved seven private
state/cache/environment sentinels and the saved local selection. Both-theme browser
checks verified early TL;DR, safe code, Review now, final save and archived recovery.
A held synthetic response hit timeout and left saving active; safeguards were retained.
The scripted provider repeats its NEW response on manual review, so this fixture is
not a semantic grouping test. Release receipts are retained in the private handoff. These are not GPU, actual audio, provider or meeting endurance
checks. No new paid calls, model weights or three-hour soak were run.

## Future public distribution

The following records the unresolved state at 0.1.11. The October 16
[distribution review](DISTRIBUTION.md) and [provenance record](../THIRD_PARTY.md)
supersede those publication findings without changing the historical validation.

Keep the repository/releases private. Exact known-secret and credential-pattern
scans found no matches in tracked/reachable blobs at review time; this is bounded
scanning, not a guarantee that every possible sensitive string is absent. Historical
machine labels, author identities and detailed internal evaluation records still need
publication review. No history rewrite, credential rotation or old release deletion
was performed. The existing LICENSE names other project contributors/installer
portions; ownership/provenance and package licensing metadata require owner review.
Bundled Apache-2.0 notices are retained. Installed dependencies/model weights need
separate review if redistributed; do not infer blanket compatibility from this audit.
