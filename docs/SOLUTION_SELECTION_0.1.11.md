# Solution selection — 0.1.11

Both local and compact-cloud prompts now explicitly recommend the simplest correct
implementation suitable for stated requirements and reasonable input constraints.
Prefer explainable steps, descriptive names, familiar Java operations, straightforward
control flow and little bookkeeping. Readability takes priority over clever compression.
Advanced structures, preprocessing and binary search remain available when warranted.
Explicit performance requirements and supplied bounds override the simplicity preference;
do not recommend an impractical baseline or invent restrictive bounds when none exist.

The unchanged structured answer order is TL;DR, optional coherent code, then key points.
Complexity must describe the implementation actually shown. At most one short optimization
bullet may follow; no automatic second implementation. A later optimization request or
material constraint updates the same card and briefly explains why the approach changes.

| Frozen check | Expected recommendation |
| --- | --- |
| Subsequence count without restrictive bounds | Check each word against s with two pointers; count empty words and duplicate entries; O(W × (n + 1)) worst-case time and O(1) auxiliary space |
| Same task, fixed million-character s, repeated batches, explicit no-rescan requirement | Refine the existing card; reusable position index or another justified approach, separate preprocessing and query costs |
| 100,000-character s and 50,000 words, explicit prohibition on per-word full scans | Choose a scalable approach immediately; do not recommend roughly five billion checks as adequate |

Fixtures include acceptance/rejection rubrics in
[solution_selection_0.1.11.json](../tests/fixtures/solution_selection_0.1.11.json).
Seven new offline checks exercise actual controller packets and effective gateway
payloads for both prompt paths, preserving source wording, performance bounds,
streaming/settings and same-card refinement with a scripted response. These are
request/pipeline regressions, **not model-quality evaluation**. The rubrics are ready
for a later authorized live comparison; none was performed for this patch.

At the initial prompt checkpoint, 156 offline tests passed. No paid calls, new latency figures, model comparisons or
endurance runs. Benchmark ledger bytes are unchanged. Prior 0.1.10 live measurements
remain historical and do not validate the revised solution preference. Prompt text
grew modestly; its live latency/output-budget effects remain unmeasured. The model,
reasoning, tier, HTTP transport and 1,024-token output ceiling are unchanged.

The initial checkpoint changed only two prompt resources and the application version.
The subsequent setup scope below adds startup helpers; controller/context handling,
parser, streaming, rendering, capture/ASR and storage remain unchanged. Existing
credentials/preferences/sessions remain outside the release. See the
[portable update](INSTALLATION.md#updating).

The narrow instruction/example approach is consistent with the
[official OpenAI prompt-engineering guidance](https://developers.openai.com/api/docs/guides/prompt-engineering),
consulted October 15, 2026; documentation guidance is not empirical model acceptance.

## Subsequent scope in the same release

The user added focused setup/portability cleanup after this prompt checkpoint.
See [maintenance review](MAINTENANCE_0.1.11.md) for final startup/documentation changes.
The prompt-specific runtime-preservation statements above describe the initial
checkpoint; inference, protocol, capture, storage and model settings still remain
unchanged in the combined release.
