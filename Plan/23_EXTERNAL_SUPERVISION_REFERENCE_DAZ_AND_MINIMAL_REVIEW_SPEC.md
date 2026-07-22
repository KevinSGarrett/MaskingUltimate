# ULTIMATE MASKING SYSTEM — EXTERNAL SUPERVISION, REFERENCE INTELLIGENCE, DAZ, AND MINIMAL REVIEW
## Document 23: Near-Perfect Selective-Autonomy Amendment

**Status:** Kevin-approved governed amendment
**Approved source:** `C:\Users\kevin\.codex\attachments\5b9dada6-68b0-44c7-96d1-07c701c0b2ca\pasted-text.txt`
**Source SHA-256:** `0679f23da58844605adbe86e79562b650072c0d4b52ac2ecc8f9fc43a4e2af31`
**DAZ design authority:** `Plan\Daz\00_PACKAGE_INDEX.md` through `32_F_DAZ_ASSET_PLACEMENT_AND_DIRECTORY_MANIFEST.md`
**Implementation tracker:** `Plan\Items\20_ITEMS_P9_REFERENCE_DAZ_AUTONOMY.md`

**Doc-24 profile scope:** this document governs optional `independent_real_accuracy` and post-core
`scale_daz_maturity` evidence. Its human anchors, real holdouts, reference-corpus scale, DAZ asset/
render work, ablations, package milestones, binary owner decisions, and seven-day soak do not block
`core_autonomous_runtime`. Core may consume any already-qualified capability, but it never waits for
the entire program described here.

---

## 1. Objective and acceptance posture

MaskFactory is not being built to transfer routine tracing work from one tool to another. Its product
target is to generate masks that are as close to pixel-perfect as measurable real-image evidence can
support, fully autonomously for the overwhelming majority of eligible images. Human work is reserved
for a small, preselected calibration/audit set, genuinely out-of-distribution residuals, and a simple
approve/reject decision over an already prepared evidence bundle.

The system must learn from every governed source that can improve real masks: sparse real human-anchor
truth, real autonomous-certified truth, qualified existing labelled datasets, exact synthetic DAZ
geometry, the governed reference corpus, and independent generators/critics/repairers. “Near-perfect”
is an acceptance target—not a claim made from architecture or data volume—and is proven only on
untouched real human-anchor holdouts. The system abstains when it cannot meet the gates.

| Dimension | Target | Authority |
|---|---:|---|
| zero-touch eligible packages | ≥0.95 | measured production report |
| routine human touch | ≤0.05 | measured production report |
| manually changed predicted pixels | ≤0.01 | pixel delta, not review time |
| ordinary visible PART mean IoU | ≥0.95 | untouched real human-anchor holdout |
| ordinary boundary F1 | ≥0.90 | untouched real human-anchor holdout |
| hard anatomy mean IoU | ≥0.85 | fingers, toes, hair, anatomy/clothing boundaries |
| format integrity | 100% | hard block |
| left/right swaps | 0 | hard block/revocation |
| cross-instance bleed | 0 | hard block/revocation |
| false-accept 95% upper bound | ≤0.01 | active certificate |
| serious false-accept 95% upper bound | ≤0.005 | active certificate |

Aggregate results cannot hide a failing label, multi-person stratum, clothing/nudity state, pose,
occlusion, or hard bucket. Coverage, abstention, quality, and labor are reported separately.

## 2. Authority model

The existing four truth tiers remain exhaustive: `human_anchor_gold`,
`autonomous_certified_gold`, `weighted_pseudo_label`, and `machine_candidate`. No fifth tier is
created. Source roles are orthogonal lineage attributes:

| Source role | Truth tier when supervised | Partition | Weight | Gold/count authority |
|---|---|---|---:|---|
| real human anchor | `human_anchor_gold` | train/calibration/holdout | 1.0 train | final real authority |
| real certificate-covered output | `autonomous_certified_gold` | train | 0.65 default | certified volume while valid |
| qualified external label | `weighted_pseudo_label` for training; `external_labeled_reference` source role for semantic-critic controls | train; leakage-disjoint semantic-critic calibration | 0.10–0.25 training | never operational gold/certified volume |
| `synthetic_geometry_exact` | `weighted_pseudo_label` | train | 0.10–0.25 | never gold/certified volume |
| unlabeled reference corpus | none | none | 0 | no truth from selection |
| unresolved machine output | `machine_candidate` | residual | 0 | no training/holdout authority |

DAZ geometry is exact to the rendered scene and synchronized passes. That does not make a synthetic
image real-photo gold, eliminate semantic mapping errors, or remove domain gap.

## 3. MaskedWarehouse external supervision

The use profile is locked to private/personal/noncommercial/non-distributed local execution. Official
upstream terms permit that use for CelebAMask-HQ, LaPa, and MHP. Legal eligibility is separate from
technical admission. The machine authority is `configs\maskedwarehouse_provenance.yaml`.

Every admitted source must have official license evidence, a tested deterministic remap, source/image/
mask hashes, representative alignment QA, instance identity validation where applicable, exact and
perceptual split dedup, and a bounded label scope.

- CelebAMask-HQ supplies declared face, hair, neck, and accessory supervision.
- LaPa supplies face/hair parsing and face-geometry supervision.
- LV-MHP v1 supplies multi-person coarse body, face/hair, clothing/material, accessory, occlusion, and
  identity supervision.

`split_required` labels are never fabricated into exact atomic PART labels. Until a geometry-assisted
conversion is qualified, they remain coarse auxiliary supervision or become ignore value 255. Face-only
data cannot be presented as a full-body sample.

The swimsuit preview remains blocked because recorded preview terms prohibit derivatives and full-data
rights are not established. The body archive remains blocked because its official source/license is
unknown. External masks never become human/autonomous gold, never enter model
calibration or certified holdout as gold, and never satisfy certified-volume
gates. After their exact qualification, however, they are required real labeled
references for leakage-disjoint semantic visual-critic calibration and seeded-
defect construction within the source label scope.

Qualified external labels use per-source weights 0.10–0.25 and a combined batch cap of 0.35 until real
holdout ablations justify a narrower policy. Real certified supervision remains dominant. Dataset cards
report source, label scope, counts, weighted units, exclusions, and ambiguous-pixel fraction. A source/
label remains active only if its matched real-holdout ablation improves or is non-inferior without hard-
bucket, identity, boundary, or calibration regressions.

Converters preserve all source hashes and emit `source_role: external_labeled_reference`,
`truth_tier: weighted_pseudo_label`, `truth_partition: train`, an explicit weight, upstream split,
source label, remap/version hashes, and conversion lineage. All instances and near duplicates stay in
one split group. Strict maps use MaskFactory writers and ambiguous pixels are 255.

## 4. Reference library

`F:\Reference_Images` currently contains 83,422 discovered images. The governed output is
`F:\Reference_Images\Ultimate_Masking_Reference_Images`; the working visual index is under
`C:\Temp\MaskFactory_Reference_Library`.

| Tier | Target | Use | Prohibited use |
|---|---:|---|---|
| `benchmark_reference` | 2,500 | frozen coverage/reference evaluation and acquisition targets | training, retrieval, truth authority |
| `retrieval_reference` | 18,000 | hard-case similarity, coverage deficits, semantic-calibration acquisition context | automatic truth/training admission |

Originals are immutable. The centralized source policy in doc 01 §7 applies without adding a
reference-library-specific admission system.
Selection alone never creates masks or gold; an image gains truth only through an independent normal
human-anchor or autonomous-certification workflow.

The pipeline performs strict decoding, metadata extraction, SHA-256 exact dedup, perceptual/embedding
near-dedup, body-part/difficulty classification, quality/diversity ranking, selection, materialization,
contact sheets, and hash verification. Required overlap is zero by path and SHA between tiers and zero
by exact/near-duplicate identity between the frozen benchmark and any training/calibration/holdout
source. A benchmark image promoted into supervision is retired from that benchmark version.

Completion requires every exact representative classified, failures resolved/reason-coded, exact tier
counts, all required body-part tags, every materialized hash verified, and an immutable benchmark
version. Status probes are read-only and do not walk 83k files.

## 5. Complete DAZ incorporation

`Plan\Daz\00–32` is incorporated by reference in full. Its 120 D0–D11 WBS entries are imported one-for-
one into P9. The DAZ pack is design/evidence authority; the live tracker remains status authority.

Foundation invariants:

- canonical bulk root `F:\DAZ` with stable root UUID and NTFS volume identity;
- Git contains code, schemas, small configs, tests, and redacted evidence only;
- local profile `private_personal_local_v1`;
- one hidden process-per-job generation worker initially;
- generation default-disabled until activation passes;
- no automatic purchase or account login;
- a machine-level GPU lease shared with MaskFactory;
- atomic recipe/result protocol, job-private partial output, heartbeat/watchdog/quarantine, and
  `worker_result.json` written last; and
- one-command stop/rollback with unchanged normal behavior while disabled.

The existing hidden Render-State acquisition workers are a separate asset-ingest plane. They may
discover/download/install/static-inspect, but cannot mark an asset qualified. DAZ runtime load/fit/pose/
render smoke, mapping compatibility, and validation remain required.

Accepted scenes produce synchronized pristine RGB, instance, PART, MATERIAL, protected, alpha, depth,
normal, relationship, and diagnostic passes from one frozen scene. Visible truth comes from visible
passes; hidden/amodal geometry stays diagnostic.

Every accepted DAZ sample has:

```yaml
source_origin: synthetic
source_role: synthetic_geometry_exact
truth_tier: weighted_pseudo_label
truth_partition: train
training_loss_weight: 0.20
holdout_eligible: false
calibration_eligible: false
dataset_volume_eligible: false
counts_as_human_anchor_gold: false
counts_as_autonomous_certified_gold: false
maximum_synthetic_image_fraction: 0.30
```

Weight may vary only 0.10–0.25. Synthetic image share may not exceed 30%. Scene families, pristine/
variant images, and all instances remain grouped. Builder and launcher independently reject wrong
authority, weight, protected-partition exposure, and >30% share.

Promotion uses matched real-only versus 10/20/30% DAZ ablations and untouched real human-anchor primary/
hard-bucket metrics. Synthetic improvement never replaces real calibration authority.

## 6. Autonomous generate–critic–repair path

The production path:

1. discovers every promoted person and preserves p-index identity;
2. generates candidates from independent foundation, pose, geometry, parsing, silhouette, specialist,
   custom, retrieval-informed, and deterministic families;
3. scores with independent critics plus complete-map topology/boundary/identity/protected vetoes;
4. applies bounded ROI repair with immutable-neighbor and rollback constraints;
5. reruns the complete map and all hard checks after each accepted repair;
6. certifies only exact labels/risk buckets covered by current fingerprint-bound real calibration; and
7. routes OOD, drift, disagreement, sparse evidence, identity ambiguity, or hard failure to residual
   repair/review.

Reference retrieval supplies difficult examples and coverage context. External/DAZ supervision trains
challengers. Neither can vote itself into real gold.

## 7. Binary owner decision

Human interaction is two actions over a prepared bundle: **Approve** or **Reject**. The bundle already
binds source hash, mask-set hash, evidence hash, truth/partition intent, certificate IDs when applicable,
format pass, zero blocking QA, identity pass, and split-integrity pass.

Approve seals a prepared `human_anchor_seal` in its declared partition, or records agreement for an
`autonomous_audit` without converting it to human gold or widening its certificate. Reject routes
bounded residual repair; for an autonomous audit it revokes the exact affected certificate scope.
Rejected evidence remains for failure mining.

Decisions are idempotent and stored in an append-only SHA-256 chain. An incomplete bundle cannot be
decided, and a conflicting second decision over identical evidence is blocked.

## 8. Isolation, resources, and evidence

One source image, perceptual duplicate group, every person instance, DAZ scene family, RGB variant, and
derived package stay in one split group. Only real human-anchor truth may populate calibration, test/
hard holdout, threshold tuning, certificate fitting, and final promotion authority.

Reference indexing, DAZ rendering, inference, and training share one 8 GiB GPU lease. CPU inventory,
planning, validation, and status may continue in parallel. DAZ rendering does not start while reference
classification or training owns the GPU.

DAZ disk thresholds are healthy ≥150 GiB, soft <150 GiB, hard <100 GiB, emergency <60 GiB. Hard floor
blocks new render leases; emergency stops after a safe checkpoint and protects metadata.

Status work is read-only and bounded: no recursive scans of live registries, stopping acquisition
workers, WSL/Docker restarts, visible DAZ/Chrome launches, or VHD access.

Legal eligibility, code existence, a running process, generated images, exact synthetic geometry, or a
plausible quality estimate is not completion evidence. Each P9 verify clause requires dated/hash-bound
artifacts and real holdout results where quality/promotion is affected.

## 9. P9 exit

P9 exit closes `scale_daz_maturity`; it is not the MaskFactory autonomous-runtime exit.

P9 exits only when qualified warehouse sources are converted inside their label scope; reference index,
selection, materialization, coverage, and zero-leakage pass; DAZ D0–D11, 100/1,000/10,000-scene
milestones, real ablations, failure/restore/rollback, and seven-day soak pass; DAZ benefit is proven on
untouched real images; binary decisions preserve authority; selective autonomy meets the declared
quality/labor targets; and the full MaskFactory suite is green with DAZ disabled and through its guarded
enabled path.
