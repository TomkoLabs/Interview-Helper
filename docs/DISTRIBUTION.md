# Source distribution

The October 16, 2026 review prepares the **current 0.1.12 source tree** for future
public source distribution without changing the application. Nothing has been
published publicly. No new version, application release or permanent public-only
implementation branch is needed for these documentation changes.

## Attribution outcome

[THIRD_PARTY.md](../THIRD_PARTY.md) records the retained MIT grant and other-project
notices, pinned WhisperLiveKit origin/modifications, inherited ÚFAL MIT attribution,
and the distinction between bundled source, installed dependencies and downloaded
assets. All applicable notices are included; combined package metadata is
`MIT AND Apache-2.0`. No copyright owner is invented, upstream source relicensed or
personal attribution erased. The root license is intentionally unchanged.

The current source review found no unresolved attribution or exposed-credential
blocker. This is a bounded source/distribution review, not a warranty of ownership
or a license audit of environments or model weights redistributed separately.

## Current source versus private history

Use a **clean snapshot of the reviewed main commit** for the first future public
repository commit. Historical development/account correspondence remains in private
history and old source assets. It is unnecessary for public operation and should not
be mirrored. Ordinary Git authors, legitimate copyright names and incidental hardware
labels are not secrets and were not used as reasons to erase attribution.

The private review checked tracked content, reachable commits/blobs/tags, retained
source archives and available built wheels against known private values and credential
patterns, then inspected private-material findings. No credential match was found.
This does not prove the absence of every possible sensitive string. Old tags,
releases and history remain unchanged and private; do not push them to a public remote.

## Reproducible candidate

On the reviewed main checkout, record `git rev-parse HEAD`, require a clean tracked
worktree, then run:

```bash
set -euo pipefail
reviewed_commit=$(git rev-parse HEAD)
test -z "$(git status --porcelain --untracked-files=no)"
mkdir -p dist
candidate="interview-helper-0.1.12-source-${reviewed_commit}.tar.gz"
git archive --format=tar --prefix=interview-helper/ "$reviewed_commit" |
  gzip -n > "dist/$candidate"
(cd dist && sha256sum "$candidate" > "$candidate.sha256")
```

The manifest/checksum belongs to the exact commit, not a new release tag. Inspect
archive members and extract to a new private directory for review. Verify executable
modes, all licenses, prompts/static resources and source files. No `.git`, remote
configuration, local config, keys, transcripts, models, environment or private evidence
may be present. A wheel built from this export must contain all three license files,
THIRD_PARTY attribution and unchanged runtime resources/dependencies.

Only after explicit public-publication authorization: initialize a **new** Git
repository in that reviewed export, make its first commit and add the intended public
remote. Do not copy the private `.git`, fetch private history into it, or use mirror
push. This review does not authorize those actions. Future updates come from the same
maintained main source through reviewed snapshots; do not maintain divergent code.

## Existing installations

There is no runtime upgrade, key re-entry, provider reset or data migration associated
with this preparation. Existing users continue with `./start.sh` and their saved
configuration. The [0.1.12 release update](INSTALLATION.md#updating) remains valid and
unchanged. A source snapshot is identified by its commit/checksum; do not mistake it
for a newly measured application release. Desktop/GPU/provider acceptance limits
remain those in [validation](VALIDATION.md).
