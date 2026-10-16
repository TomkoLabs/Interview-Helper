# Licensing and provenance

## Application and retained project notices

IH has declared MIT licensing since its initial source commit
`309c8d712ba4d505fbb00126f83f67c96857332b`, in both `LICENSE` and package metadata.
The root [LICENSE](LICENSE) is byte-identical to the license used by gx10-status,
including its gx10-status and m5-status contributor notices. It predates IH's first
installer implementation. This establishes the origin of the notice/template, not
ownership of IH or proof that its application code came from either project.
The existing MIT grant and both notices are retained without assigning copyright
to a new owner or removing potentially applicable attribution. No new license is chosen.

IH-specific application, UI, prompts and scripts remain under that existing MIT
license. The bundled source below has additional upstream obligations; package
metadata therefore declares **MIT AND Apache-2.0**. This describes the distributed
package, not a relicensing of upstream code or installed/downloaded assets.

## Bundled LocalAgreement code

`src/interview_helper/vendor/local_agreement.py` and `vendor/timed.py` are adapted
from [WhisperLiveKit revision 363e4f6](https://github.com/QuentinFuxa/WhisperLiveKit/tree/363e4f6d029694d9c81ae548beddd9d3c88a3637)
(0.2.26), Copyright 2025 Quentin Fuxa, Apache-2.0. Its
[full license and upstream credits](src/interview_helper/vendor/LICENSE-WhisperLiveKit)
are retained. Comparison with the pinned upstream license found only one removed
trailing space, with no lost text. The upstream tree contains no separate NOTICE file.

The adapted files already identify their origin. Changes are the package import,
minimal timed types, bounded committed prompt history, removal of transcript debug
logging, and an explicit failure instead of silently resetting uncommitted speech.
The original hypothesis/segment processing is retained. No vendored source was
modified during this distribution review.

WhisperLiveKit credits **whisper_streaming by ÚFAL**; its LocalAgreement
`HypothesisBuffer` and `OnlineASRProcessor` ancestry is also evident in the source.
The inherited **Copyright (c) 2023 ÚFAL** and full MIT permission notice are included
in [LICENSE-WhisperStreaming](LICENSE-WhisperStreaming), obtained from
[upstream revision 6da90b4](https://github.com/ufal/whisper_streaming/blob/6da90b44b7e50d79695e68166d2a2c7609c75abb/LICENSE).
That revision pins the notice inspected on October 16, 2026; it is not asserted to
be the exact historical ancestor of WhisperLiveKit's adaptation.
[LocalAgreement background](https://aclanthology.org/2023.ijcnlp-demo.3/).

WhisperLiveKit's broader credits are preserved as upstream attribution, not a claim
that IH bundles every listed project. No SimulStreaming implementation or model
weights are bundled. Source exports include all notices; wheels include them in
license metadata along with the original vendor license resource.

## Installed dependencies and separate downloads

faster-whisper and CTranslate2 are MIT-licensed installed dependencies. FastAPI
(MIT), Starlette, Uvicorn, HTTPX and NumPy (BSD-3-Clause) likewise retain their own
licenses; the lock files define the full dependency inventory, not this short list.
Dependencies are installed by the existing setup, not copied into the source export.
If redistributing an environment, audit and retain each distribution's notices.

Whisper weights download separately from their named model repositories. Review the
selected model card/license before redistributing weights. Optional CUDA/cuDNN
packages have NVIDIA's own terms; drivers, GPU libraries and model weights are not
bundled. The project license grants no rights over those separate assets.
