# Section 20 — Immutable Release, Pinned ComfyUI Adoption, Final E2E Proof, Rollback, and Tracker Closure

**Acceptance order:** 20 of 20  
**Mapped unresolved tracker items:** 6  
**Current states:** open=5, partially_complete=1  
**Hard blockers in scope:** 4  
**Rows with explicit Kevin authority/input:** 0  
**Depends on:** Section 01, Section 02, Section 03, Section 04, Section 05, Section 06, Section 07, Section 08, Section 09, Section 10, Section 11, Section 12, Section 13, Section 14, Section 15, Section 16, Section 17, Section 18, Section 19  
**Enables:** Final closure

## Goal

Assemble one immutable MaskFactory release, pin it into the external ComfyUI project, run live accept/failure/abstain/restart/invalidation/rollback scenarios, independently reconstruct the whole system, and close only claims whose exact gates passed.

## Why this section exists

No branch name, chat claim, focused test wave, static receipt, or dirty worktree can complete the project. Final acceptance requires one exact release identity, clean full suite, real campaigns, current visual authority, cross-project adoption, rollback, and tracker dependency closure.

## Scope

- Assemble the immutable release candidate with source/tree, package, deployment, runtime/model/config, ontology/API, tests, campaigns, visual evidence, limitations, startup/shutdown, invalidation, and rollback bindings.
- Deliver the pinned builder-session-to-ComfyUI-session adoption packet.
- Run live bounded external ComfyUI E2E for accept, deterministic/provider failure, abstain/quarantine, restart/replay, invalidated release refusal, and rollback.
- Rerun clean reconstruction and all required test tiers against release bytes.
- Publish final acceptance/reconstruction packet and close tracker items/profile claims through the CLI only.
- Keep optional independent-real-accuracy and scale/DAZ maturity claims separate when their gates are not met.

## Work packages

1. Create a unique immutable release ID and exact release manifest.
2. Build and verify source/package/deployment archives.
3. Pin exact MaskFactory and ComfyUI commits, workflows, nodes, configs, models, and expected behavior.
4. Execute the full external adoption matrix and independent disposition.
5. Run final clean full-suite, campaign reconstruction, visual qualification, resource-leak, invalidation, and rollback checks.
6. Regenerate tracker/dashboard/profile reports and compare all accepted hashes byte-for-byte.

## Section-level testing

- Release validator rejects mutable branches, dirty/unclassified bytes, missing/stale/contradictory evidence, incompatible API/ontology/model, or overclaiming.
- Clean install and complete test suite from release archives.
- Live ComfyUI accept, provider failure, deterministic failure, abstain, quarantine, restart/replay, invalidation refusal, and rollback.
- Independent evidence-locator reconstruction of campaigns and qualifications.
- Zero duplicate request/promotion, leaked process/port/lease/reservation/GPU state.
- Tracker dependency/profile closure and generated report drift tests.

## Integration tests with the rest of the project

- Both projects bind the exact same release and adoption identities.
- Rollback restores the prior accepted release without mutating historical packages/evidence.
- Final acceptance can be reproduced by a reviewer without either original chat session.

## Definition of done and acceptance criteria

- [ ] One immutable release candidate is independently validated.
- [ ] The external ComfyUI project records ADOPT or an honest PARTIALLY_ADOPT/REJECT disposition against exact bytes.
- [ ] All required live scenarios, clean tests, campaign reconstruction, visual authority, and rollback pass.
- [ ] The `core_autonomous_runtime` claim closes only if every required gate is complete.
- [ ] Optional portfolio claims are closed only when their own evidence passes; a core-only release checkpoint must be labeled core-only, and the entire project is not declared complete until Sections 18–19 are accepted.
- [ ] MF-P6-22.01–.04 and final tracker/profile reports are accepted.

## Required proof artifacts

- `maskfactory_release_manifest.json`
- `release_archives_sha256.tsv`
- `cross_session_adoption_packet.json`
- `comfyui_live_adoption_matrix.json`
- `final_clean_suite_junit.xml`
- `final_reconstruction_receipt.json`
- `final_rollback_receipt.json`
- `tracker_profile_closure_report.json`
- `ultimate_masking_system_acceptance_packet.json`
- `section_acceptance_receipt.json`

## Exit procedure

1. Run T0–T5 tests applicable to this section and preserve commands, exits, counts, environment, and hashes.
2. Verify every mapped tracker row against its own exact `Verify:` clause.
3. Produce and independently validate `section_acceptance_receipt.json`.
4. Exercise rollback/invalidation and verify zero leaked resources.
5. Update tracker rows through `Plan/Tracker/tracker.py`; regenerate dashboard/phase/profile reports.
6. Commit only section-scoped source/evidence locators and open the section PR.
7. Begin the next section only from the accepted commit.

## Mapped tracker items

| Item | Phase | Status | % | Hard blocker | Explicit user authority | Work remaining |
|---|---|---|---:|:---:|:---:|---|
| `MF-P6-22.01` | P6 | open | 0 | Yes | No | Assemble one immutable MaskFactory release candidate with exact commit/tree, package/deployment, ontology/API, runtime/model/config, test, campaign, visual, evidence-index, limitation, startup/shutdown, invalidation, and rollback bindings |
| `MF-P6-22.02` | P6 | open | 0 | Yes | No | Deliver the pinned cross-session adoption packet from MaskFactory session `019f91d1-ea20-7d81-83ff-03d393eaa1f5` to ComfyUI session `019f9200-4805-7632-83d3-ee9ae614c603`; keep ComfyUI masking deferred before this gate |
| `MF-P6-22.03` | P6 | open | 0 | Yes | No | Run live bounded ComfyUI masking E2E against the pinned release for every required serving mode, including accept, provider/deterministic failure, abstain/quarantine, restart/replay, invalidation refusal, and rollback |
| `MF-P6-22.04` | P6 | open | 0 | Yes | No | Publish the final Ultimate Masking System acceptance/reconstruction packet and close only the claims whose exact gates passed |
| `MF-P7-07.09` | P7 | partially_complete | 75 | No | No | Run doctor, live provider smokes, frozen benchmarks, optional CVAT migration/rollback, statistical certificate/revocation, single-person headline, and tracker/report before declaring the legacy modernization/portfolio profile complete; this bundle has no core-completion authority |
| `MF-P9-EXIT` | P9 | open | 0 | No | No | Qualified external labels and DAZ improve untouched real human-anchor results; reference leakage is zero; selective autonomy meets the quality/labor targets; DAZ survives the seven-day soak and remains reversible |

## Tracker-item exact verification text

### `MF-P6-22.01` — Immutable MaskFactory release and ComfyUI adoption

- **Current:** `open` at 0%
- **Source:** `24_ITEMS_P6_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION.md` line 26
- **Requirement:** Assemble one immutable MaskFactory release candidate with exact commit/tree, package/deployment, ontology/API, runtime/model/config, test, campaign, visual, evidence-index, limitation, startup/shutdown, invalidation, and rollback bindings · Verify: release validator rejects mutable, missing, stale, contradictory, or overclaiming inputs · Blocked by: MF-P6-11.01 through MF-P6-12.06, MF-P6-19.04, MF-P6-20.04, MF-P6-21.04 · HARD BLOCKER

### `MF-P6-22.02` — Immutable MaskFactory release and ComfyUI adoption

- **Current:** `open` at 0%
- **Source:** `24_ITEMS_P6_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION.md` line 27
- **Requirement:** Deliver the pinned cross-session adoption packet from MaskFactory session `019f91d1-ea20-7d81-83ff-03d393eaa1f5` to ComfyUI session `019f9200-4805-7632-83d3-ee9ae614c603`; keep ComfyUI masking deferred before this gate · Verify: both sessions bind the same release, package/runtime, integration input, expected output, limitation, and rollback identities · Blocked by: MF-P6-22.01 · HARD BLOCKER

### `MF-P6-22.03` — Immutable MaskFactory release and ComfyUI adoption

- **Current:** `open` at 0%
- **Source:** `24_ITEMS_P6_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION.md` line 28
- **Requirement:** Run live bounded ComfyUI masking E2E against the pinned release for every required serving mode, including accept, provider/deterministic failure, abstain/quarantine, restart/replay, invalidation refusal, and rollback · Verify: exact workflow/request/mask/error/state hashes and zero duplicate or leaked-resource evidence receive independent ADOPT/PARTIALLY_ADOPT/REJECT disposition · Blocked by: MF-P6-22.02 · HARD BLOCKER

### `MF-P6-22.04` — Immutable MaskFactory release and ComfyUI adoption

- **Current:** `open` at 0%
- **Source:** `24_ITEMS_P6_ULTIMATE_MASKING_SYSTEM_E2E_INTEGRATION.md` line 29
- **Requirement:** Publish the final Ultimate Masking System acceptance/reconstruction packet and close only the claims whose exact gates passed · Verify: tracker dependency closure, generated reports, clean full suite, real campaigns, visual authority, release, ComfyUI adoption, reconstruction, rollback, and both session states agree byte-for-byte; optional accuracy/scale claims remain separate · Blocked by: MF-P6-22.03 · HARD BLOCKER

### `MF-P7-07.09` — Recurring currency, certificate operations, and autonomous headline evidence

- **Current:** `partially_complete` at 75%
- **Source:** `18_ITEMS_P7_CURRENCY_OPERATIONS.md` line 27
- **Requirement:** Run doctor, live provider smokes, frozen benchmarks, optional CVAT migration/rollback, statistical certificate/revocation, single-person headline, and tracker/report before declaring the legacy modernization/portfolio profile complete; this bundle has no core-completion authority · Verify: dated completion bundle links all exact evidence and names its optional profile scope · Blocked by: all upstream modernization gates
- **Existing evidence to preserve/revalidate:** qa/live_verification/modernization_completion_bundle_contract_20260715.json; 29 dedicated and 92 focused tests pass; Ruff and targeted Black pass

### `MF-P9-EXIT` — Phase Exit Gate

- **Current:** `open` at 0%
- **Source:** `20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md` line 188
- **Requirement:** Qualified external labels and DAZ improve untouched real human-anchor results; reference leakage is zero; selective autonomy meets the quality/labor targets; DAZ survives the seven-day soak and remains reversible · Verify: signed P9 evidence bundle plus full regression, real holdout ablations, rollback, and tracker validation pass · Blocked by: every MF-P9 item

