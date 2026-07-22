# Document 26: Adult Corpus Autonomous Batch Ingestion and Qualification

**Status:** Kevin-approved governed amendment, adopted 2026-07-22

**Durable intake authority:**
`C:\Comfy_UI_Main\MaskedWarehouse\Nude\_MASKFACTORY_INTAKE`

**Adopted starting lineage:** 16 datasets; 81,910 records; 322 shards per
platform; registry `785bfbcca98262a00519b53a360a67d22f23ec9e4b41c9bc38029f402eb9bbcf`;
shard index `16a958ffdc6c304174fa8ff5b9b656a607e8e8a9e9610dac9be4a8dbff3c994a`.
Any rebuild records the prior lineage, changed source-tree reason, new totals,
and new seals. It never silently replaces this checkpoint.

## 1. Authority and role separation

The 16 registered sources are first-class MaskFactory product inputs under the
same provenance, rights, integrity, annotation-quality, split/leakage, and
evidence-authority rules as other sources. Adult/nude/NSFW subject matter is not
itself an exclusion category.

Source representations retain distinct roles:

- COCO polygons are external labeled references after rasterization, alignment,
  ontology, identity, deduplication, and qualification pass.
- COCO boxes are prompts/coarse detection supervision, never pixel masks.
- sexual-action and position labels are scene/action supervision and evaluation
  context, never anatomy pixels.
- CivitAI images/metadata are reference and tournament inputs with no mask truth.
- Porn-Blocker-Benchmark is frozen evaluation-only holdout and cannot train.

Downloaded labels and generated masks never become human gold or operational
authority from file presence. Eligible exact outputs follow the existing
machine-candidate, deterministic-QA, strict visual-review, operational-
certificate, release, revocation, and rollback path.

## 2. Registration and ontology

`dataset_policy.json`, `dataset_registry.generated.json`, and
`records.generated.jsonl` preserve exact dataset path, dataset/source identity,
source URL, declared license, lineage group, version policy, media domain,
annotation format, split, classes, annotation counts, source hashes, and record
identity. All 16 datasets must appear in the project adoption evidence.

The raw source label is immutable lineage. `ontology_crosswalk.json` maps only
the meaning actually supplied. Coarse `breast`, `penis`, `buttocks`, `genital`,
or similar labels do not invent laterality, areola, nipple side, shaft/glans,
scrotal side, or glute side. Fine v2 labels may be produced only by independent
model evidence that passes the normal exact-output qualification path.

## 3. Correlation, duplicate, and leakage control

Exact SHA-256 and perceptual/embedding near-duplicate groups are computed over
all records before partition use. The group key also incorporates source
lineage and discovered augmentation identity. One group cannot cross train,
validation, test, critic calibration, or holdout.

`main.v3/v4/v5` are one correlated family; v5 is preferred. `mange.v2/v3` are
one correlated family; v3 is preferred. Related variants discovered later join
the same group before any partition is assigned. The original evaluation-only
holdout policy is frozen before its first measured run.

## 4. Lane execution

The supplied 256-record shards are the scheduling authority. Local execution
uses `batch_shards/local`; RunPod uses `batch_shards/runpod`. Each lane first
runs one representative shard:

1. polygon external supervision: decode, rasterize/validate, remap, compare;
2. bbox prompt supervision: validate boxes, run multi-provider prompted masks;
3. bbox plus action tags: keep action context separate from pixel proposals;
4. reference/tournament: generate independent proposals with no source truth;
5. evaluation holdout: seal and isolate without training.

A malformed record becomes a reason-coded quarantine/abstention row and cannot
stop its shard. Systemic canary failures are corrected before expansion to
1,000 records and then the full population. Thresholds are never weakened to
increase throughput.

## 5. Durable scheduler and reporting

Queue every eligible shard. The durable state binds registry/index/shard,
sample, source, provider, policy, and output hashes. State transitions use
owned leases, bounded retry attempts, heartbeat/expiry, write-last result
markers, idempotent sample decisions, per-shard checkpoints, submitted-unknown
reconciliation, crash recovery, and replay-safe resumption.

Checkpoint every 256 records. Emit user-facing milestones every 1,000 records
or material failure/recovery event. Internally retain every record's provenance,
candidate masks, QA, panels, critic response, repair lineage, and outcome.
Routine Kevin/CVAT review is not a throughput dependency.

## 6. Autonomous mask qualification

Each eligible record uses independent provider proposals/comparison, boundary
refinement, deterministic hard QC, complete target-aware source/mask/overlay/
contour/ownership panels, and a separate strict-VLM structured verdict. Contact
sheets are scheduling aids only; no sheet-level vote approves its members.

Hard-QC blocks cannot be cleared by a critic. Bounded deterministic repair
creates a new candidate and reruns all gates. Terminal outcomes are
machine-verified candidate, repair queued, abstained/rejected, quarantined
input, or holdout-only. Operational certificates remain exact-output scoped,
signed, current, unrevoked, and hash-bound under existing policy.

## 7. RunPod synchronization and capacity

Canonical remote root is `/workspace/assets/MaskedWarehouse/Nude`; source
`/workspace/paths.env` and require
`MASKED_WAREHOUSE=/workspace/assets/MaskedWarehouse`. Probe before transfer.
Compare allowlisted files by relative path, size, and SHA-256; upload only
missing or changed paths from `runpod_transfer_files.generated.txt`. Preserve
paths, exclude ZIP duplicates/cache internals, retain extras for reconciliation,
and verify local/pod registry seals and counts after transfer.

CPU/network transfer needs no GPU lease. Provider inference and strict-VLM
bursts use SharedRunPodCoordinator v2, auto-tuned microbatches, 64-record panel
jobs, 16-record review bursts with per-record verdicts, and serialized
incompatible large models.

## 8. Coverage, training, release, and recovery

Dataset/milestone reports stratify anatomy, action/position, media domain,
split, provider agreement, QC failure, repair success, abstention, quarantine,
and certification yield. Aggregate success cannot hide a failing dataset,
label, action, or hard bucket.

Only qualified supervision enters immutable training datasets at its exact
truth tier and weight. Holdout and correlated variants remain isolated.
Training/benchmarking/champion promotion must measure adult-anatomy classes and
false positives, preserve source-family grouping, and bind exact dataset seals.
Released packages use the frozen MaskFactory-to-ComfyUI contracts and normal
certificate/invalidation/rollback authority.

Completion requires all 81,910 adopted records to have one durable accounted
outcome, local/RunPod reconciliation, corpus-scale resume/throughput evidence,
coverage/failure reports, and measured participation of accepted supervision in
training, benchmark/champion qualification, and the released bridge path.
