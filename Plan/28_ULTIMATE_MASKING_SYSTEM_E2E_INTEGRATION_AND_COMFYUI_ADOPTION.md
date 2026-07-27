# 28 — Ultimate Masking System E2E Integration and ComfyUI Adoption

## 1. Purpose

This specification prevents a partial subsystem, branch, test wave, model
campaign, or evidence receipt from being mistaken for completion of the
Ultimate Masking System.

Plan 24 defines the required autonomous core and cross-project bridge. Plan 27
defines continuous self-hosted operations and throughput. This document binds
those capabilities to the full MaskFactory product tree, full test surface,
reconstructable evidence, safety semantics, and the final adoption by ComfyUI
session `019f9200-4805-7632-83d3-ee9ae614c603`.

The authoritative MaskFactory builder session is
`019f91d1-ea20-7d81-83ff-03d393eaa1f5`. The ComfyUI masking lane remains
deferred until the immutable MaskFactory release candidate defined here is
accepted.

Frozen authority and campaign evidence contracts:

- `configs/self_hosted_autonomy_contract_freeze_v1.json`;
- `configs/self_hosted_autonomy_campaign_telemetry_v1.schema.json`; and
- `configs/self_hosted_autonomy_acceptance_v1.schema.json`.

## 2. Problem statement

The project currently has two materially different bodies of work:

- a full product source line with hundreds of source and test files, packaging,
  serving, model, mask, and QA functionality; and
- an active autonomy/runtime line with accepted campaign control, recovery,
  routing, steward, and evidence functionality.

Focused autonomy tests prove important control-plane behavior. They do not
prove that the entire product builds, installs, or works end to end. Likewise,
the full product source does not receive autonomy credit unless it contains and
executes the accepted runtime.

The audited full product test surface collected 4,446 tests and did not pass.
Observed failures included unavailable external model/assets and a stale
completion-policy source binding. Those failures are product blockers until
they are repaired or governed with honest, reproducible prerequisites.

The project also lacks a compact committed locator for some accepted runtime
evidence, and the provider-disagreement hard-QA path can record `PASS` when the
pairwise result is `DISAGREE`. Both defects must be corrected before production
mask acceptance.

## 3. Required outcome

The integrated product SHALL have:

1. one canonical source commit/tree containing the full product and accepted
   autonomy/runtime implementation;
2. one reproducible install, runtime, dependency, and model/config contract;
3. focused, integration, clean-environment, and full-product test evidence;
4. exact handling of required external assets without hidden local-state
   dependence;
5. a committed evidence locator for every completion-critical accepted
   milestone;
6. fail-closed disagreement, abstention, and hard-QA semantics;
7. accepted Plan-27 real campaign evidence without duplicate rerun;
8. one immutable MaskFactory release candidate;
9. one pinned cross-session ComfyUI adoption packet; and
10. live ComfyUI masking, restart, invalidation, and rollback proof.

## 4. Canonical source integration

### 4.1 Inventory

Record exact commits, trees, branch ancestry, tracked differences, staged
differences, untracked ownership, and path classifications for the full
product and autonomy source lines.

Every path must be classified as:

- identical;
- full-product-only and required;
- autonomy-only and required;
- superseded with evidence;
- generated and reproducible;
- runtime evidence, not source;
- user-owned/unrelated and preserved; or
- unresolved conflict.

No reset, mass checkout, mass stage, replacement clone, or replacement
worktree may be used to hide unresolved ownership.

### 4.2 Integrated tree

The canonical tree must include:

- package/install metadata such as `pyproject.toml`;
- all required `src/maskfactory` product and steward modules;
- CLI and service entry points;
- configs, schemas, policy files, and exact defaults;
- focused, integration, negative, fault, and full-product tests;
- model/runtime manifests without embedding secrets or large model bytes;
- Plan/Items/Instructions/Tracker authority; and
- startup, health, submission, shutdown, reconstruction, invalidation, and
  rollback procedures.

### 4.3 Conflict resolution

Conflicts are resolved by behavior and evidence, not by taking whichever file
is newer. Accepted runtime semantics and full-product functionality must both
survive. Any deliberate removal requires a supersession receipt and test.

## 5. Build and test proof

### 5.1 Test tiers

The integrated tree must pass:

1. static syntax, schema, formatting, and secret scans;
2. focused unit tests for changed paths;
3. steward/routing/recovery/campaign suites;
4. mask/provider/ontology/hard-QA suites;
5. service/CLI/bridge integration suites;
6. clean-clone or clean-export install and import tests;
7. the complete collected product suite; and
8. live bounded end-to-end tests required by the tracker.

Passing a lower tier never substitutes for a higher tier.

### 5.2 External assets

Tests requiring model checkpoints, Civitai artifacts, datasets, GPUs, or
services must declare:

- exact source/provenance and expected hash;
- governed local or runtime path;
- whether the test is hermetic, provisioned integration, or live acceptance;
- an explicit skip/fail contract;
- the authority needed to acquire or use the asset; and
- the evidence required before the result receives product credit.

Missing assets may classify a test as blocked or not runnable in a specific
environment. They may not be silently treated as pass.

### 5.3 Clean reconstruction

From a clean, authorized environment, a reviewer must be able to:

- install the project;
- validate authority and schemas;
- reconstruct accepted compact evidence indexes;
- run the required non-GPU suites;
- start and health-check the supported services;
- execute a bounded test route;
- stop owned processes; and
- verify no leaked lease, reservation, port, or child process.

## 6. Evidence locator and reconstruction

Maintain a committed compact evidence index. Each row binds:

- tracker item;
- parent campaign and route;
- source commit/tree;
- immutable input/request/runtime/model/config hashes;
- response/artifact/validation/acceptance/terminal/release hashes;
- evidence location and compact recovery location;
- replay or reconstruction command;
- adoption decision;
- limitations and claims explicitly not made; and
- supersession relation.

The index stores no secrets or large runtime/model assets. Large evidence
remains under governed runtime storage; the index makes it discoverable and
verifiable.

Historical Git objects may prove historical provenance but cannot substitute
for current source-bound qualification.

## 7. Mask safety and disagreement semantics

Provider disagreement must never be converted into a pass merely because one
candidate passed another gate. The integrated hard-QA outcome must be one of:

- pass only when every required deterministic and agreement condition passes;
- abstain when evidence or authority is insufficient;
- adjudicate under an explicitly governed rule;
- reject for candidate failure; or
- quarantine for contradictory or unsafe state.

Tests must assert:

- disagreement blocks promotion;
- hard-QA failure cannot be overridden by visual confidence;
- primary/juror disagreement cannot approve;
- unavailable or unqualified critics abstain;
- one failed record does not stall unrelated records; and
- complete campaign accounting remains exact.

## 8. Real campaign integration

Preserve the accepted `MF-P6-19.01` and `MF-P6-19.02` packets. Do not rerun
them.

The 100-mask and mixed campaigns must execute from the canonical integrated
tree or an exact source-bound deployment of it. Their evidence must be entered
into the compact locator and independently reconstructed before whole-product
release.

Real campaign acceptance requires exact input and terminal counts, no duplicate
submission/promotion, qualified visual authority, 100% route reconciliation,
100% local lease release, and one consolidated adoption packet.

## 9. MaskFactory release candidate

The release candidate must bind:

- Git commit/tree and clean/dirty ownership boundary;
- package and deployment archive hashes;
- runtime/model/tokenizer/quantization/engine/dependency/config manifests;
- ontology, provider, mode, label, and API compatibility;
- `/predict` and artifact schemas;
- focused/full/live test receipts;
- real campaign and visual-qualification evidence;
- evidence-index and reconstruction receipt;
- startup/health/shutdown/rollback/invalidation procedures;
- known limitations; and
- a unique release identity.

No mutable branch name or conversational reference is sufficient.

## 10. ComfyUI cross-session adoption

The ComfyUI session must consume only the exact release candidate. The
cross-session packet must state:

- MaskFactory builder session and ComfyUI adopter session;
- release identity and all source/package/runtime hashes;
- exact ComfyUI integration commit and workflow/node/config inputs;
- expected masks, metadata, errors, and abstention behavior;
- serving Mode A and Mode B applicability;
- health, retry, timeout, restart, rollback, and invalidation behavior;
- authority boundaries; and
- terminal `ADOPT`, `PARTIALLY_ADOPT`, or `REJECT`.

Before adoption, ComfyUI masking remains deferred. After adoption, ComfyUI must
prove live bounded end-to-end workflows using the pinned release, including:

1. accepted mask retrieval/use;
2. deterministic or provider failure;
3. abstention/quarantine propagation;
4. service restart and request replay safety;
5. invalidated release refusal; and
6. rollback to the prior accepted release.

## 11. Completion and claim firewall

`SELF_HOSTED_AUTONOMOUS_LLM_THROUGHPUT_INCOMPLETE` remains the Plan-27 claim
until its campaign gates pass.

`ULTIMATE_MASKING_SYSTEM_E2E_INCOMPLETE` remains the whole-product claim until:

- all required core item dependencies are complete;
- Plan 27 passes;
- every Item-24 integration/adoption row passes;
- the full product suite passes under its declared environment contract;
- the evidence locator and clean reconstruction pass;
- safety disagreement semantics pass;
- the release candidate is immutable; and
- the ComfyUI session independently adopts and proves the masking release.

Optional independent-real-accuracy and scale/DAZ profiles retain their separate
claim boundaries. Neither may be used to hide a required core failure or to
block core with an optional requirement.

## 12. Acceptance artifacts

Final acceptance produces one consolidated packet with:

- all required tracker rows and dependency closure;
- exact source/build/runtime/evidence identities;
- focused and full-suite summaries;
- live campaign summaries;
- visual authority qualifications;
- evidence-index validation;
- MaskFactory release and ComfyUI adoption receipts;
- rollback/reconstruction results;
- unresolved limitations;
- zero duplicate execution/promotion proof;
- zero leaked resource proof; and
- an independent final-quality decision.
