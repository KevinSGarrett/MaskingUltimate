# ULTIMATE MASKING SYSTEM — TECHNOLOGY CURRENCY AND MODEL CHALLENGE SPEC
## Document 22: Registry Governance, Certification Metrics, and Promotion Control

**Status:** Approved amendment
**Date:** 2026-07-14
**Owner:** Kevin
**Precedence:** This document governs where older documents conflate catalog presence, installation,
benchmarking, promotion, zero-touch throughput, statistical confidence, or truth authority.

---

## 1. Operating Profile

MaskFactory is private, personal, local, noncommercial, and not distributed. `production` means the
active local MaskFactory path. The only content-compatibility lanes governed here are:

- `adult_nonexplicit`
- `consensual_explicit_adult`

Both lanes are permitted by the project profile. Every provider and registered model must still carry
its own explicit `allowed | prohibited | unclear` decision. A registry-wide decision never substitutes
for an artifact-specific decision.

## 2. Active Registry Contract

1. Active registries use exact schema version `2.0.0`. A missing, downgraded, or unknown version fails
   closed.
2. Historical version-1 registries may be opened only through an explicitly requested offline legacy
   reader. They are never accepted by an active loader, writer, benchmark, trainer, or serving path.
3. Runtime loading performs JSON-Schema validation and governance validation through one entry point.
4. Duplicate YAML keys are forbidden and tested. Multi-capability providers use arrays such as
   `capabilities`, `roles`, and `authority_constraints`; repeated scalar keys are not permitted.
5. Registry mutation is transactional. The complete post-mutation document is validated before atomic
   replacement.

## 3. Provider and Artifact Lifecycle

Catalog presence is not evidence of installation or promotion. Provider lifecycle values are:

| State | Meaning | May run active work? |
|---|---|---|
| `planned` | Cataloged challenger without an installed governed artifact | No |
| `installed` | Exact artifact/runtime present and smoke-verified | Shadow or fallback only |
| `benchmarked` | Installed artifact has a current frozen benchmark certificate | Shadow or approved fallback |
| `promoted` | Current role owner with rollback evidence | Yes |
| `reference_only` | Discovery or compatibility reference, not executable authority | No |
| `retired` | Retained only for historical reproducibility | No |

The installed model registry contains no `planned` entries. Promotion changes lifecycle state
transactionally: the winner becomes `promoted`; the displaced incumbent becomes `benchmarked` and
remains a rollback provider. Rollback restores both role and lifecycle state.

## 4. License and Content Activation Gate

Before activation in either content lane, all of the following must pass:

1. The provider is `installed`, `benchmarked`, or `promoted`.
2. Its lane-specific compatibility is exactly `allowed`; missing, `unclear`, and `prohibited` block.
3. `verify_license` is false. `verify_license: true` is an operational blocker, not a reminder.
4. Before a new benchmark or promotion, the exact license source/version, an immutable evidence hash,
   reviewed terms, compatibility decision, and review timestamp are recorded.
5. A checkpoint-specific restriction overrides a repository-level license.

The external probe reports activation eligibility and blockers independently from file availability.
An available file is not necessarily an eligible provider.

## 5. Truth Tiers and Non-Collapsing Metrics

Truth authority remains explicit:

| Tier | Training use | Gold/volume gate use |
|---|---|---|
| `human_anchor_gold` | Weight 1.0 only when partitioned for training | Yes, training partition only |
| `autonomous_certified_gold` | Configured weight 0.5–0.75 | Yes while certificate is valid |
| `weighted_pseudo_label` | Configured weight 0.1–0.25 | Never |
| `machine_candidate` | No | Never |

Human anchors carry an explicit partition: `train`, `calibration`, or `holdout`. The image-disjoint
final holdout is excluded from training, pseudo-label generation, model selection, threshold tuning,
and certificate fitting.

The following metrics are separate and must never be presented as one gold count:

```text
human_anchor_train_count
human_anchor_calibration_count
human_anchor_holdout_count
autonomous_certified_gold_count
weighted_pseudo_label_count
machine_candidate_count

certified_training_package_count =
    human_anchor_train_count + autonomous_certified_gold_count

effective_training_weight_units =
    human_anchor_train_count
    + sum(active autonomous-certified training weights)
    + sum(pseudo-label training weights)
```

P5 entry uses `certified_training_package_count >= 200`. D5 uses at least 300 certified packages plus
its required coverage. `effective_training_weight_units` is a training-load diagnostic only and cannot
satisfy P5, D5, a gold-volume gate, or a coverage count.

## 6. Certification and Audit Statistics

Zero-touch throughput, mask quality, and statistical confidence are three different measurements:

- `zero_touch_fraction` measures how often routine intervention was avoided.
- Quality metrics measure masks against blinded truth.
- Confidence bounds quantify uncertainty in measured failure rates.

The 0.95 zero-touch objective is never evidence of accuracy or certification.

Risk buckets are versioned, mutually auditable groupings defined before evaluation. At minimum they
separate large parts, small parts, hands/feet, hair/boundaries, clothing/material boundaries, sensitive
anatomy, occlusion/contact, multi-person overlap, and identified out-of-distribution contexts. Pooling
is allowed only when empirical evidence supports exchangeability; otherwise the bucket is split or
abstains.

Certification requires:

1. A frozen maximum false-accept rate and serious-failure rate for every bucket.
2. A documented power calculation and minimum audited sample floor for that bucket. There is no
   universal magic sample count.
3. A one-sided 95% upper confidence bound no greater than the frozen maximum. Use a conservative exact
   binomial bound for zero/rare serious failures and a predeclared Wilson or exact bound for aggregate
   false accepts.
4. Selective prediction: sparse, shifted, or non-exchangeable buckets abstain rather than borrowing
   unjustified confidence.
5. A mixed audit sample containing an unbiased random component plus deterministic risk oversampling.
   The nominal 1–2% rate is a workload target, not a substitute for the required sample floor.
6. Immediate certificate revocation for a serious false accept, evidence/hash mismatch, incompatible
   pipeline fingerprint, or material drift. Revocation removes serving and certified-training
   eligibility without rewriting historical evidence.

## 7. Challenger Promotion

Promotion is role-specific and requires all of the following:

1. A frozen, image-disjoint evaluation set, prompts, hardware profile, QA version, and measurement code.
2. A measured primary win or material labor reduction.
3. Predeclared non-inferiority margins for every hard label and high-risk bucket. An average improvement
   cannot hide a hard-bucket regression.
4. No regression in cross-person bleed, left/right correctness, protected-region handling, hard-QA
   failures, determinism, OOM/crash rate, or rollback reliability.
5. Complete source/checkpoint/runtime/license/content hashes and a current benchmark certificate.
6. A tested one-command rollback to the displaced incumbent.

Specialist margins are predeclared in
`qa/governance/benchmark_matrices/specialist_margins_v1.json`. The manifest is source-hash-bound to
the active ontologies, QA hard-class list, autonomy risk policy, and multi-person strata; its locked
SHA-256 is enforced in code and CI before any result reader runs. Benchmark result artifacts must bind
that exact manifest hash, contain every expanded label/context/zero-regression bucket with the exact
predeclared margin, and postdate the freeze. Recomputing a manifest self-hash does not authorize a
post-freeze threshold edit. A primary average or labor win cannot override one failed bucket.

Installed, benchmarked, and promoted states are recorded independently. A model card, catalog entry,
download, or smoke test alone cannot produce a promotion.

## 8. Currency Review

Review models, runtimes, dependencies, licenses, content compatibility, benchmark certificates, and
rollback evidence every 90 days and before dataset freeze, training, promotion, or a major release.
Newer models become challengers automatically, never replacements. CI fails closed on an active path
when required hashes, decisions, reviews, benchmark evidence, or rollback evidence are absent or stale.

## 9. Required Regression Evidence

- Live registry passes its bundled schema and governance validation.
- Missing/downgraded schema versions fail active loading; explicit offline legacy reads remain tested.
- Duplicate YAML keys fail tests.
- Every provider and model has its own content decision and lifecycle state.
- An unresolved license blocks activation even when the artifact file exists.
- Promotion and rollback restore both role and lifecycle state.
- Tracker reports every truth tier separately and uses certified package count for gates.
- Zero-touch dashboards never label throughput as accuracy or confidence.
- Certification fixtures cover pooling refusal, sample-floor failure, confidence-bound failure, random
  plus risk audit selection, serious-failure revocation, and fingerprint drift.
- Promotion fixtures prove both average improvement and hard-bucket non-inferiority.
