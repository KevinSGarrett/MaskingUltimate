# Global Acceptance Standard

## One active acceptance unit

Only one numbered section may be in `ACCEPTANCE_PENDING` at a time. Work can be prepared elsewhere only when it cannot mutate the active section's source, tracker, or evidence roots.

## Required status ladder

1. `NOT_STARTED`
2. `IMPLEMENTATION_COMPLETE` — code/config/docs exist; no acceptance claim.
3. `STATIC_PASS` — lint/schema/unit/focused tests pass; live claims remain open.
4. `INTEGRATION_PASS` — neighboring components and negative/fault paths pass.
5. `LIVE_PASS` — required real GPU/service/CVAT/ComfyUI/DAZ/human evidence passes.
6. `ACCEPTED` — independent receipt, rollback, evidence index, and tracker update pass.

A lower status never substitutes for a higher one.

## Test ladder required in every section

- **T0 — Integrity:** exact source/tree, secret scan, schema/meta-schema, generated-file drift, import ownership.
- **T1 — Focused:** unit and changed-path tests with deterministic fixtures.
- **T2 — Integration:** real neighboring modules, APIs, files, state machines, and cross-process behavior.
- **T3 — Negative/fault:** malformed, missing, stale, contradictory, timeout, crash, retry, duplicate, rollback, and resource-release cases.
- **T4 — Clean reconstruction:** new export/environment, bytecode disabled, user site disabled, exact commands and hashes.
- **T5 — Live acceptance:** governed real inputs and required GPU/service/human/external-project operation.

## Universal definition of done

A section is done only when:

- every mapped tracker item meets its own stated verification clause;
- all section acceptance criteria pass without weakening thresholds;
- all tests are tied to the canonical source/tree and exact environment;
- live-required rows have real evidence, not fixtures or static receipts;
- every input has one terminal outcome and all totals reconcile;
- no secret, untracked required source, leaked process, port, lease, reservation, or GPU workload remains;
- rollback/invalidation is tested, not merely documented;
- known limitations and claims not made are explicit;
- an independent reviewer can reconstruct the result from committed locators and governed artifact storage;
- tracker changes are made through `tracker.py`, reports are regenerated, and no checkbox is hand-edited.

## Branch and PR rule

- Base every section branch on the accepted commit from the prior section.
- One PR per section; no unrelated paths.
- Do not merge a section with unresolved acceptance evidence.
- Do not target stale `main` until Sections 1–3 define the canonical target and migration strategy.
- Never use a replacement clone/worktree, reset, or mass checkout to hide ownership conflicts.

## Completion-claim firewall

- Code, schemas, prompts, tests, manifests, and receipts are supporting evidence—not live runtime evidence.
- A green subset cannot close the full-suite gate.
- Synthetic, pseudo, reference, or operationally certified artifacts cannot impersonate human-anchor or autonomous-certified truth.
- Provider/critic disagreement, missing authority, stale evidence, or incomplete accounting fails closed.
- `MF-P6-19.01` and `MF-P6-19.02` are accepted historical campaigns and must be reconstructed, not rerun.
- Optional `independent_real_accuracy` and `scale_daz_maturity` claims remain separate from `core_autonomous_runtime`.
