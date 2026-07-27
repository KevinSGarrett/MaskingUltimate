# ITEMS — P6 Ultimate Masking System E2E Integration and ComfyUI Adoption

Goal: integrate the accepted autonomous runtime with the complete MaskFactory
product, prove it in a clean full-product environment, preserve reconstructable
evidence, and adopt one immutable masking release into the pinned ComfyUI
session.

Frozen authority and evidence contracts:
`configs/self_hosted_autonomy_contract_freeze_v1.json`,
`configs/self_hosted_autonomy_campaign_telemetry_v1.schema.json`, and
`configs/self_hosted_autonomy_acceptance_v1.schema.json`.

## MF-P6-20 — Canonical product/autonomy source integration (spec: 28 §§2–5)
- [ ] MF-P6-20.01 Inventory and reconcile the full-product and accepted autonomy source lines by exact commit/tree/path ownership, preserving unrelated staged, dirty, and untracked work · Verify: a complete path classification has no unexplained deletion, overwrite, reset, replacement worktree, or unresolved conflict · Blocked by: MF-P6-19.01, MF-P6-19.02 · HARD BLOCKER
- [ ] MF-P6-20.02 Produce one canonical integrated source tree containing product code, autonomy/runtime code, package metadata, configs, schemas, CLIs, services, tests, and operating procedures · Verify: clean diff/secret/schema/import/package checks prove both source lines' required behavior survives · Blocked by: MF-P6-20.01 · HARD BLOCKER
- [ ] MF-P6-20.03 Classify and repair the complete product test baseline, including completion-policy drift and every external-asset dependency · Verify: each collected test is passing or has a governed explicit environment prerequisite that cannot be misreported as pass; no unexplained collection/runtime failure remains · Blocked by: MF-P6-20.02 · HARD BLOCKER
- [ ] MF-P6-20.04 Prove clean-export installation, exact-byte runtime closure, focused/integration/full-suite execution, bounded service health, and owned shutdown · Verify: an independent reconstruction receipt binds source, environment, commands, results, processes, ports, and zero leaked resources · Blocked by: MF-P6-20.03 · HARD BLOCKER

## MF-P6-21 — Evidence reconstruction and integrated mask safety (spec: 28 §§6–8)
- [ ] MF-P6-21.01 Publish a compact committed evidence locator for every completion-critical accepted runtime, routing, campaign, visual, release, and adoption milestone · Verify: every entry binds tracker item, parent, source, input/runtime/output/terminal/release hashes, locations, replay command, limitations, and supersession without secrets or large artifacts · Blocked by: MF-P6-20.02 · HARD BLOCKER
- [ ] MF-P6-21.02 Make provider and critic disagreement fail closed as abstain/adjudicate/reject/quarantine, never an implicit pass; preserve hard-QA veto authority · Verify: focused and integrated tests prove disagreement blocks promotion, unqualified/unavailable critics abstain, and unrelated records continue with exact accounting · Blocked by: MF-P6-17.02, MF-P6-20.02 · HARD BLOCKER
- [ ] MF-P6-21.03 Bind the current source-qualified 66-class visual gate, exact critic qualifications, and mask-campaign prerequisites into the canonical runtime without duplicating historical campaigns · Verify: missing/stale/historical-only visual evidence blocks promotion and accepted P4/P6 evidence reconstructs from the locator · Blocked by: MF-P4-11.23, MF-P6-17.03, MF-P6-21.01, MF-P6-21.02 · HARD BLOCKER
- [ ] MF-P6-21.04 Reconstruct the accepted 25-mission/recovery evidence and the eventual 100-mask/three-mixed-campaign evidence from the canonical integrated tree · Verify: independent replay matches exact counts, decisions, source/runtime identities, terminal reconciliation, and release without rerunning immutable accepted work · Blocked by: MF-P6-19.04, MF-P6-20.04, MF-P6-21.01 · HARD BLOCKER

## MF-P6-22 — Immutable MaskFactory release and ComfyUI adoption (spec: 28 §§9–12)
- [ ] MF-P6-22.01 Assemble one immutable MaskFactory release candidate with exact commit/tree, package/deployment, ontology/API, runtime/model/config, test, campaign, visual, evidence-index, limitation, startup/shutdown, invalidation, and rollback bindings · Verify: release validator rejects mutable, missing, stale, contradictory, or overclaiming inputs · Blocked by: MF-P6-11.01 through MF-P6-12.06, MF-P6-19.04, MF-P6-20.04, MF-P6-21.04 · HARD BLOCKER
- [ ] MF-P6-22.02 Deliver the pinned cross-session adoption packet from MaskFactory session `019f91d1-ea20-7d81-83ff-03d393eaa1f5` to ComfyUI session `019f9200-4805-7632-83d3-ee9ae614c603`; keep ComfyUI masking deferred before this gate · Verify: both sessions bind the same release, package/runtime, integration input, expected output, limitation, and rollback identities · Blocked by: MF-P6-22.01 · HARD BLOCKER
- [ ] MF-P6-22.03 Run live bounded ComfyUI masking E2E against the pinned release for every required serving mode, including accept, provider/deterministic failure, abstain/quarantine, restart/replay, invalidation refusal, and rollback · Verify: exact workflow/request/mask/error/state hashes and zero duplicate or leaked-resource evidence receive independent ADOPT/PARTIALLY_ADOPT/REJECT disposition · Blocked by: MF-P6-22.02 · HARD BLOCKER
- [ ] MF-P6-22.04 Publish the final Ultimate Masking System acceptance/reconstruction packet and close only the claims whose exact gates passed · Verify: tracker dependency closure, generated reports, clean full suite, real campaigns, visual authority, release, ComfyUI adoption, reconstruction, rollback, and both session states agree byte-for-byte; optional accuracy/scale claims remain separate · Blocked by: MF-P6-22.03 · HARD BLOCKER
