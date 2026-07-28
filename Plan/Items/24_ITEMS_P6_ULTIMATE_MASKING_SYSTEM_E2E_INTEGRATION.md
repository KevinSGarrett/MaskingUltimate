# ITEMS — P6 Ultimate Masking System E2E Integration and ComfyUI Adoption

Goal: integrate the accepted autonomous runtime with the complete MaskFactory
product, prove it in a clean full-product environment, preserve reconstructable
evidence, and adopt one immutable masking release into the pinned ComfyUI
session.

Frozen authority and evidence contracts:
`configs/self_hosted_autonomy_contract_freeze_v1.json`,
`configs/self_hosted_autonomy_campaign_telemetry_v1.schema.json`, and
`configs/self_hosted_autonomy_acceptance_v1.schema.json`.

## MF-P6-20 — Canonical product/autonomy source integration (spec: 28 §§2–5; 29)
- [x] MF-P6-20.01 Inventory and reconcile the full-product and accepted autonomy source lines plus every scattered local checkout, worktree, standalone repository, recovery/evidence root, and meaningful Plan/Item/Instruction/Tracker file by exact commit/tree/path ownership, preserving unrelated staged, dirty, untracked, recovery, runtime, dataset, VHDX, Consumer, and foreign-owned work · Verify: an exhaustive path-to-owner/hash/disposition/Plan/Item/tracker/test/canonical/rollback ledger has no unexplained deletion, overwrite, reset, replacement worktree, stale tracker replay, missing history, or unresolved conflict, and the physical canonical root is clean `main` · Blocked by: MF-P6-19.01, MF-P6-19.02 · HARD BLOCKER
  - 2026-07-28 reconciliation evidence: the 137-row meaningful-file matrix has
    zero unresolved rows; the 28-row opaque-directory receipt includes the
    Main-owned 45-file inspect clone with zero product-completion effect; the
    physical root is clean `main`; shared `C:\w` has zero direct children
    under the coordinated 5,654-file receipt. Terminal quality results are
    bound by the final convergence receipt.
  - The terminal inventory also includes `refs/stash`, stash index/untracked
    parents, reflog-only work, and generated hook caches. Five late-discovered
    stashes are bound by a verified incremental bundle and a 4,008-row
    per-path semantic matrix. Useful accidental-mass-deletion residuals are
    adopted only after focused tests; incomplete prototypes and stale runtime
    policy remain archive-only with zero product-completion credit.
  - Terminal authority: recovered executable source commit
    `bc4c36ff98ebc4cc9b706ba58a10ef559d0497ee`; 5,139 collected / 5,098
    passed / 41 governed skips / zero failures; exact clean wheel SHA-256
    `644f0aa34a466a11ff607d201d9d4344b994544dbf2b5588f5d82c9e7941c026`;
    zero stashes, cache residue, temporary recovery refs, and reported Git
    garbage. No successor completion credit is implied.
  - Every one of the 4,008 historical-stash rows is now independently bound
    to Plan, Item, tracker, evidence, stash/main blob hashes, canonical and
    rollback locations, limitations, and an explicit completion effect.
    Registry SHA-256:
    `a4436d4a17c7d37990e15c47623b3d51899e1ecba9f7db0b4f9507003dc54930`;
    committed receipt:
    `.codex-ops/HISTORICAL_STASH_AUTHORITY_BINDING_20260728T212749Z.json`.
    Functional attribution includes `MF-P0-04.02/.03`, `MF-P4-11.12/.23`,
    `MF-P4-12.11`, `MF-P5-06.03`, `MF-P5-07.02`, `MF-P6-02.01`,
    `MF-P6-17.04`, and `MF-P6-21.02`; no row silently changes their status.
- [ ] MF-P6-20.02 Produce one canonical integrated source tree containing product code, autonomy/runtime code, package metadata, configs, schemas, CLIs, services, tests, and operating procedures · Verify: clean diff/secret/schema/import/package checks prove both source lines' required behavior survives · Blocked by: MF-P6-20.01 · HARD BLOCKER
  - Accepted 2026-07-28 evidence: clean pushed source commit
    `ae6ce3d9561de3293403185f0969e9ff4c3cbe29`, tree
    `b280e334a80d459920c3fbb890b8857e3bdf996e`, and
    `qa/live_verification/canonical_source_integration_20260728T220939Z/section_acceptance_receipt.json`.
    All nine gates pass: one canonical tree, required historical-path
    reconciliation, zero required untracked source, zero generated Python
    caches, source and installed imports, 231 schema meta-validations,
    wheel/sdist/install/package-data plus the same-tree 153-file deployment
    config bundle, and secret/model/dataset hygiene. The accepted wheel
    SHA-256 is
    `087d09c89f26ed28349315815e33707185a71d8697ad18e7e3b59709991d601d`;
    the exact 4,008-row authority registry remains bound at SHA-256
    `a4436d4a17c7d37990e15c47623b3d51899e1ecba9f7db0b4f9507003dc54930`.
    This completes only `MF-P6-20.02`; it grants no lint-baseline, live
    runtime, campaign, visual, release, or ComfyUI-adoption credit.
- [ ] MF-P6-20.03 Classify and repair the complete product test baseline, including completion-policy drift and every external-asset dependency · Verify: each collected test is passing or has a governed explicit environment prerequisite that cannot be misreported as pass; no unexplained collection/runtime failure remains · Blocked by: MF-P6-20.02 · HARD BLOCKER
  - Accepted 2026-07-28: clean published source
    `ee306ebd8f0d13ac1d343c2dd18e459795512a5f` collected 5,154 tests:
    5,113 passed, 41 remained explicit `skip_not_pass` prerequisites, and
    zero failed or errored. Every test has a unique inventory row; every skip
    is bound to one of 15 versioned external-asset/platform contracts and an
    unknown skip fails closed. Repository-wide Ruff and Black checks pass.
    Five deployed exact-byte runtime/test surfaces are excluded from Black
    only through a versioned registry that revalidates each current SHA-256.
    Receipt:
    `qa/live_verification/environment_packaging_test_baseline_20260728T232959Z/section_03_test_baseline_receipt.json`
    (file SHA-256
    `0d7ce3b206dcafb8eb4cad4c9ea940092462b72b48a8bd7acd73404d3908cc71`);
    independent validation self SHA-256
    `30d8c80eb47f1509a53223a81281a8b319c0cb312ca7abd490b0c8a69b295d94`.
    This satisfies `MF-P6-20.03` only and grants no runtime-lifecycle credit
    to `MF-P6-20.04`.
- [ ] MF-P6-20.04 Prove clean-export installation, exact-byte runtime closure, focused/integration/full-suite execution, bounded service health, and owned shutdown · Verify: an independent reconstruction receipt binds source, environment, commands, results, processes, ports, and zero leaked resources · Blocked by: MF-P6-20.03 · HARD BLOCKER
  - Existing evidence eligible for partial credit: exact clean archive/wheel,
    isolated install/import, focused/full-suite execution, and 311 row-level
    runtime-closure bindings. Bounded authorized-runtime health, persistent
    restore, and owned shutdown/leak proof remain required.

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
