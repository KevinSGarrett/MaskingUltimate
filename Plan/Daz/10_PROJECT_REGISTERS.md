# Project Registers

## 1. Decision register

| ID | Decision | Rationale | Revisit trigger |
|---|---|---|---|
| D-001 | `F:\DAZ` is canonical bulk root | isolates proprietary/bulk data and preserves C drive | drive migration or capacity expansion |
| D-002 | Asset source records contain only technical lineage | preserves replay, dependency resolution, and version control | registry architecture changes |
| D-003 | No automatic asset purchasing | spending and account authority belong to Kevin | never without explicit new mandate |
| D-004 | Genesis 9 is the first mapping family | minimizes initial topology/mapping duplication | G9 fails the technical pilot |
| D-005 | G8/8.1 is a separate later family | topology/rig/asset compatibility differs | after G9 production evidence |
| D-006 | DAZ labels use `weighted_pseudo_label` | preserves current four-tier truth contract | explicit truth-contract amendment |
| D-007 | Synthetic geometry exactness is an orthogonal source attribute | distinguishes pixel construction from real gold authority | schema redesign |
| D-008 | Synthetic share remains ≤30% | current MaskFactory training constitution | approved amendment plus real ablation |
| D-009 | Synthetic data is train-only | prevents synthetic evaluation authority | never for final promotion truth |
| D-010 | Active v1 and inactive v2 are generated separately | prevents ontology drift/mixed packages | v2 activation does not remove versioning |
| D-011 | Character scope is adult male and adult female DAZ figures | matches the requested training-scene scope | explicit blueprint amendment |
| D-012 | Anatomy configuration and presentation are separate | avoids identity inference and invalid applicability | ontology redesign |
| D-013 | Python controls planning; DAZ Script executes scenes | testability and a clean API boundary | plugin architecture proves necessary |
| D-014 | File protocol is authoritative | no fragile routine UI automation | future supported remote API |
| D-015 | One GPU lease serializes heavy work | 8 GiB VRAM and reliability | new GPU capacity and proven scheduler |
| D-016 | Visible and amodal channels are physically separate | protects visible truth constitution | never merge |
| D-017 | Clothing pixels receive body territory in PART and clothing in MATERIAL | matches MaskFactory's orthogonal map model | ontology/material redesign |
| D-018 | Exact label passes are separate from beauty features | blur/DOF/denoise cannot corrupt IDs | never combine |
| D-019 | Asset/recipe dominance caps are mandatory | avoids learning DAZ product fingerprints | corpus policy benchmark |
| D-020 | Real human-anchor holdouts decide promotion | synthetic-to-real gap | never replaced by synthetic |

## 2. Assumption register

| ID | Assumption | Confidence | Validation | Owner |
|---|---|---:|---|---|
| A-001 | Official DAZ APIs expose enough asset/scene/render control | high | primitive and content pilot | developer |
| A-002 | Dedicated DIM content path on F is practical | high | installation pilot | Kevin/developer |
| A-003 | G9 base topology supports stable facet mapping | medium-high | topology/morph fixtures | mapping owner |
| A-004 | Most wardrobe can inherit body territory via projection/weights | medium | garment benchmark | mapping owner |
| A-005 | Representative hair can produce reliable alpha masks | medium | hair fixture suite | render owner |
| A-006 | Initial F capacity supports development/pilot | high | measured package sizes | operations |
| A-007 | Large-scale production will require more storage | high | capacity model after pilot | Kevin/operations |
| A-008 | DAZ rendering can operate unattended with quarantined exceptions | medium-high | seven-day soak | operations |
| A-009 | DAZ data will improve at least some real hard buckets | medium | matched ablations | training owner |
| A-010 | DAZ alone cannot close all real-world domain gaps | high | external holdout evidence | training owner |

## 3. Risk register

| ID | Risk | Likelihood | Impact | Prevention / mitigation | Trigger and response |
|---|---|---:|---:|---|---|
| R-003 | Proprietary content enters Git/export | L | Critical | root isolation, ignore rules, pre-commit scanner | incident: stop, remove exposure safely, rotate/review, audit history |
| R-004 | Character preset is incompatible with its base figure or anatomy mapping | M | High | compatibility graph and scene preflight | reject scene; quarantine preset combination |
| R-005 | Semantic mapping is wrong despite clean IDs | M | Critical | golden fixtures, mapping versioning, real audits | revoke mapping and all dependent packages/models |
| R-006 | Clothing territory map invents anatomy | M | High | visible garment territory only; hidden channel separation | quarantine asset/method; retrain only after purge |
| R-007 | Hair alpha creates edge label noise | H | Medium | asset-specific alpha tests, threshold policy | restrict/quarantine hair class |
| R-008 | DAZ style overfits model | H | High | asset diversity, style randomization, ≤30%, real holdout | reject mixture or reduce targeted use |
| R-009 | One product dominates corpus | M | High | contribution caps and entropy report | block dataset freeze until rebalanced |
| R-010 | Multi-person cross-instance ownership error | M | Critical | exact instance pass and QC-035/036 analogues | reject scene; revoke if discovered after freeze |
| R-011 | Hidden popup stalls worker | H initially | Medium | no-prompt, watchdog, timeout, quarantine | kill tree, quarantine asset/combination |
| R-012 | DAZ crash/corrupt partial accepted | M | High | terminal-result-last and atomic promotion | quarantine partial; replay from recipe |
| R-013 | Disk exhaustion corrupts state | M | High | soft/hard floors, reservation, retention | drain queue, preserve metadata, recover storage |
| R-014 | 8 GiB GPU OOM/contention | M | High | global GPU lease and render profiles | lower profile/retry once; quarantine persistent asset |
| R-015 | Asset update invalidates reproducibility | H | High | exact hashes/snapshots and certificate revocation | pin old asset or rebuild affected corpus version |
| R-016 | Driver/renderer drift changes RGB | M | Medium | runtime snapshot and tolerance classification | benchmark; new runtime version, never silent |
| R-017 | Synthetic enters holdout/gold count | L | Critical | independent builder and launcher guards | invalidate dataset/run and audit |
| R-018 | v2 anatomy activation is accidentally bypassed | L | Critical | explicit ontology job and active-config checks | block/revert, run full v2 audit |
| R-019 | A scene is routed to a component that cannot process its configured channels | L | High | capability-based local routing | reroute locally or reject the task |
| R-020 | Backups capture assets but not registry/mappings | M | High | class-based backup and restore drills | stop generation until reproducibility authority is restored |
| R-021 | Mirrors/refraction create unowned person pixels | H | High | exclude from initial scope | quarantine scene/asset, later dedicated design |
| R-022 | Dynamic cloth/hair is nondeterministic | M | High | bake/cache and seed, restrict assets | mark non-replayable and reject |
| R-023 | Synthetic performance looks good only on synthetic tests | H | Critical | real human-anchor final authority | reject promotion |
| R-024 | Dataset scale creates unexpected cloud/storage cost | M | High | local default and explicit spending confirmation | pause before billable action, NEEDS KEVIN |

## 4. Dependency register

| ID | Dependency | Needed for | Status at blueprint time |
|---|---|---|---|
| DEP-001 | DAZ Studio pinned installation | worker/render implementation | to verify |
| DEP-002 | DAZ Install Manager and account | asset installation | Kevin-managed |
| DEP-003 | Installed Genesis 9 base content | mapping/pilot | not inventoried |
| DEP-004 | Representative installed asset pilot set | smoke/coverage | not inventoried |
| DEP-005 | MaskFactory manifest schema migration | package ingestion | not implemented |
| DEP-006 | MaskFactory real-image holdout | model promotion | required evaluation input |
| DEP-007 | Active ontology loader v1/v2 | map generation | exists |
| DEP-008 | GPU lease integration | stable rendering | design required |
| DEP-009 | F-drive capacity/backup | corpus scale | pilot capacity exists |

## 5. Open-question register

These are implementation-time questions, not invitations to improvise. Each has a default fail-closed
decision.

| ID | Question | Decision owner | Default until answered |
|---|---|---|---|
| Q-001 | Exact DAZ Studio build and executable location? | developer | worker disabled |
| Q-002 | Which Genesis 9 base/anatomy assets are installed? | registry scan | mapping pending |
| Q-003 | Which hair/cloth assets are deterministic enough? | qualification tests | quarantine |
| Q-004 | Exact measured bytes and seconds per scene profile? | pilot | use conservative capacity cap |
| Q-005 | Whether a local DVC remote under F is needed? | MaskFactory owner | no new remote |
| Q-006 | Which real hard buckets get the first ablation? | training/coverage owner | hands, hair, clothing, anatomy, multi-person |
| Q-007 | Whether v2 is active when DAZ implementation reaches training? | live tracker | generate v1 by default |
| Q-008 | Whether G8/8.1 adds enough diversity to justify mapping cost? | benchmark owner | defer |

## 6. RACI

| Activity | Kevin | DAZ subsystem | MaskFactory developer | QA/training evaluation |
|---|---|---|---|---|
| Asset purchase/download | A/R | I | I | I |
| Asset scan and smoke | I | R | A | C |
| Registry/product/source entry | I | R | A | C |
| Figure mapping | I | R | A | C |
| Scene generation/render | I | R/A | C | I |
| Scene QA/package | I | R | A | C |
| Schema/code integration | I | C | R/A | C |
| Training build | I | C | R | A |
| Human-anchor evaluation | A for data authority | I | R | A |
| Model promotion | A | I | R | A |
| Spending/storage expansion | A/R | I | C | C |
| Incident response | A if spending or hardware action is required | R | R | C |

`A` = accountable, `R` = responsible, `C` = consulted, `I` = informed.
