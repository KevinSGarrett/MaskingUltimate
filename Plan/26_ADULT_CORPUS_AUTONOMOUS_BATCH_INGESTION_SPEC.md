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
- COCO segmentation may use polygon arrays or validated compressed/uncompressed
  RLE. RLE canvas and run totals must match exactly; decoded pixel area is
  recomputed, while a stale exporter `area` field is preserved as advisory
  lineage rather than overriding the mask. Polygon bbox alignment accepts either
  the frozen IoU floor or at most 1.5 pixels of per-edge rasterization
  quantization; larger mismatches remain quarantined rather than lowering QC.
- COCO boxes are prompts/coarse detection supervision, never pixel masks.
- sexual-action and position labels are scene/action supervision and evaluation
  context, never anatomy pixels.
- The exact 6,537 files under
  `C:\Comfy_UI_Main\MaskedWarehouse\Nude\CivitAI_Top_NSFW_Images` are
  `reference_and_tournament_input`, `reference_only_no_mask_truth`, and
  `synthetic_or_generated`. They have zero polygon, bbox, or segmentation
  annotations. Their filenames join exactly to `prompts.json`; prompt and
  `nsfwLevel` values are weak scene/action/retrieval context only and cannot
  create pixel anatomy labels, fine labels, boxes, or masks.
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

The CivitAI reference lane is exactly 26 shards (25 of 256 records and one of
137 records). Every shard runs independent multi-provider proposal generation,
provider comparison, hard QC, strict per-record visual review, bounded repair,
and terminal accept/abstain/quarantine handling. Only newly generated,
hash-bound artifacts that pass the full autonomous qualification policy may
become machine-verified supervision at their earned tier; neither the source
image nor its prompt is gold, labeled segmentation supervision, or pixel truth.

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
The remote CivitAI files retain the exact relative
`Nude/CivitAI_Top_NSFW_Images` path and reference-only role; synchronization
must not relabel or relocate them into a mask, annotation, or gold directory.

Provider inference and strict-VLM bursts use direct selected-pod execution,
auto-tuned microbatches, 64-record panel
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

## 9. Canonical real-data-first learning priority

This section is the authoritative execution-order amendment for docs 12, 17,
23, and 25. It does not weaken their truth, leakage, qualification, or release
requirements.

The first production learning cycle uses the adopted real/external and
reference populations before large-scale DAZ generation:

1. qualify and normalize existing masks, COCO polygons/RLE, boxes, points,
   silhouettes, scene/action tags, gold packages, and reference-only images;
2. train the real-supervision foundation and its ownership, coarse-anatomy,
   atomic-anatomy, specialist, and boundary components;
3. use SAM 3.1, SAM 3D Body where applicable, and hypothesis-distinct
   independent providers to expand bbox/reference records into candidates;
4. autonomously qualify exact candidates through deterministic QA, qualified
   independent visual review, bounded repair, and immutable outcomes;
5. retrain from the enlarged qualified population;
6. mine remaining label/domain/risk/ownership/boundary deficits; and
7. activate DAZ scale generation only for measured residual gaps and controlled
   real-only versus real-plus-DAZ ablations.

Small DAZ foundation, mapping, and deterministic-render tests may continue when
they are independent and useful. DAZ 1,000/10,000-scene scale, training-mixture
promotion, and soak work are deferred until the real-data learning cycle emits
an immutable gap report identifying synthetic-truth targets. DAZ never becomes
the default training foundation merely because rendering is available.

## 10. Hierarchical model and package architecture

The unified ontology and final package remain authoritative, but internal model
routing is hierarchical rather than requiring one flat model to solve every
class:

`source -> person/character discovery -> instance ownership/occlusion order ->
whole-person silhouette -> coarse anatomy -> atomic anatomy specialists ->
edge/boundary refinement -> complete-map consistency -> temporal consistency`.

Required independently benchmarked roles include:

- person discovery, p-index/character ownership, and cross-person exclusion;
- whole-person and coarse anatomical regions;
- fine face and facial-feature parsing;
- hands, individual fingers, feet, and toes;
- hair, flyaways, and other thin structures;
- breasts, nipples, areolas, penis/shaft/glans, scrotum/testicles,
  vulva/vaginal region, anus, buttocks, and left/right buttock according to the
  active ontology and exact source evidence;
- clothing/skin and adjacent-label boundaries;
- multi-person contact, occlusion, and ownership;
- boundary refinement and complete-map recomposition.

Each role publishes exact checkpoint/runtime/input/output hashes and measured
per-label/per-risk results. A specialist may improve its bound labels but cannot
silently overwrite another instance, protected label, ontology state, or
package authority.

## 11. Representation-specific use and source granularity

| Representation | Permitted learning use |
|---|---|
| qualified COCO polygons/RLE | weighted segmentation supervision within the exact source label scope |
| boxes | detection/ownership training and prompts for independent mask generation |
| masks/silhouettes | boundary, proposal-comparison, calibration, or training use only at earned authority |
| points | prompt/refinement training and repair-policy evaluation |
| action/position labels | scene context, retrieval, sampling, and evaluation; never anatomy pixels |
| reference-only images | self-supervised representation learning, retrieval, hard-case discovery, proposals, and tournaments |
| prompt text | weak retrieval/context metadata only |
| current certified packages | highest-authority training/calibration inputs within certificate scope |
| DAZ synchronized passes | targeted exact synthetic geometry and controlled ablation inputs |

Raw labels remain immutable. A coarse label such as `genitals`, `breast`,
`buttocks`, or `penis` is not silently decomposed into fine atomic classes.
Fine supervision requires independent pixel evidence and the normal
qualification path.

## 12. Staged teacher-student learning program

### 12.1 Real-supervision foundation

Train first from qualified polygons/RLE, certified packages, and other
pixel-authoritative inputs. Use source-family-balanced sampling, per-source and
per-label reliability weights, rare-class sampling, and explicit
coarse-versus-fine losses. No one large dataset or correlated version may
dominate a batch or cross a split.

### 12.2 Reference-domain representation learning

Use leakage-safe training partitions from `F:\Reference_Images` and
reference-only MaskedWarehouse sources for self-supervised or masked-image
representation learning. This may improve photographic anatomy, pose,
body-shape, lighting, crop, contact, occlusion, small-part, and multi-person
features without inventing pixel labels. Frozen benchmark, critic
qualification, calibration, validation, test, and holdout images are excluded.

### 12.3 Proposal expansion

Process bbox and reference records through detection, ownership consensus,
SAM 3.1-first segmentation, SAM 3D Body when its geometry is applicable,
independent segmentation families, specialist providers, deterministic hard
QA, qualified primary criticism, independent-family jury, and bounded repair.
Unqualified outputs remain candidates or terminal abstentions/quarantines.

### 12.4 Iterative self-training

Every cycle uses an immutable mixture manifest with independently measured
weights:

- highest: current exact-scope human-anchor or autonomous-certified gold;
- medium: qualified external polygons/RLE;
- lower: exact machine-verified candidates eligible for the declared training
  experiment;
- zero pixel-loss weight: reference images, prompts, boxes, action tags, and
  unqualified proposals.

The student is promoted only after leakage-disjoint frozen evaluation and
per-label/per-domain/per-risk non-regression. Its improved predictions begin a
new candidate revision; they never retroactively upgrade parent authority.

### 12.5 Hard-case mining

Rank the next records from provider disagreement, small-target scale,
multi-person contact, cross-person leakage, rare labels, extreme crop,
occlusion, boundary disagreement, wrong side/front-back/owner, repair
exhaustion, and weak per-domain certification yield. Easy-case volume cannot
hide missing hard strata.

## 13. Self-hosted LLM/VLM roles in the learning cycle

The text/planning model performs dataset reconciliation, ontology-mapping
proposals, batch planning, failure clustering, coverage analysis, hard-case
selection, bounded repair-hypothesis construction, and milestone/exception
summaries.

Qualified visual roles inspect each exact record's full source, binary mask,
overlay, contour, target crop, ownership view, protected neighbors,
disagreement map, and before/after repair evidence. They diagnose and localize;
they do not author authoritative pixels, clear hard-QC failures, change frozen
thresholds, promote truth, or issue certificates. Segmentation/refinement
providers create new mask revisions, and the deterministic certificate service
alone evaluates authority. Contact sheets remain navigation and throughput
evidence, never per-record approval.

## 14. Temporal video extension and audio boundary

After the still-image hierarchy has a qualified champion, the video lane adds
keyframe segmentation, bidirectional propagation, correspondence/flow
consistency, persistent character ownership, temporal boundary stability,
cut/occlusion/re-entry detection, and automatic uncertain-frame
re-segmentation. Every accepted frame mask retains source-frame and temporal
lineage.

Audio supplies timing, scene/shot, speaker/performer, and action-context
metadata only when the consumer workflow needs it. It is not anatomical pixel
truth and cannot train, validate, or certify a body-part mask by itself.

## 15. DAZ activation and benefit gate

The immutable real-data gap report must identify target labels, viewpoints,
ownership/contact cases, occlusions, crops, or topology failures before DAZ
scale work is admitted. DAZ then generates only the declared gap cells, such as
rare angles, exact laterality, severe foreshortening, cross-person contact,
out-of-frame anatomy, protected-region interaction, depth/ownership, and
visible-versus-amodal comparisons.

Matched real-only and real-plus-DAZ challengers use identical splits, seeds,
configs, and evaluation. DAZ weight is retained only when untouched real
holdouts improve or remain non-inferior with no label, ownership, boundary, or
hard-bucket regression. Otherwise the synthetic lane is disabled or narrowed
without delaying the real-data learning program.
