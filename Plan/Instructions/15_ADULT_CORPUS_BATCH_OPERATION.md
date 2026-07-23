# 15 — Adult Corpus Batch Operation

Read `Plan/26_ADULT_CORPUS_AUTONOMOUS_BATCH_INGESTION_SPEC.md` and the seven
files named by `_MASKFACTORY_INTAKE/README_START_HERE.md` before operating this
corpus. Adopt the recorded seals before rebuilding. Run the intake validator
with `--rehash sample`. Local canary tooling is limited to CPU decode/schema/
queue preflight; provider inference, strict review, repair, and qualification
canaries run directly on persistent RunPod storage.

## Real-data-first execution order

Document 26 §§9–15 is binding. Prioritize the registered real/external and
reference populations before large-scale DAZ generation:

1. qualify polygons/RLE, boxes, points, masks, silhouettes, action tags,
   certified packages, and reference-only images under their exact roles;
2. train the source-family-balanced real-supervision foundation and
   hierarchical ownership/anatomy/specialist/boundary cascade;
3. run leakage-safe self-supervised representation learning over eligible
   reference partitions;
4. expand bbox/reference records with SAM 3.1, SAM 3D Body when applicable,
   independent provider families, hard QA, qualified visual review, and
   bounded repair;
5. retrain only from immutable weighted mixtures and promote only measured
   non-regressing challengers;
6. mine hard cases and publish an immutable residual-gap report; and
7. activate DAZ scale only for those measured gaps and matched real holdout
   ablations.

DAZ foundation/mapping canaries may continue independently. Do not select
1,000/10,000-scene rendering, synthetic-mixture training, or DAZ soak ahead of
ready real-data qualification, training, proposal-expansion, or hard-case
work.

The self-hosted text model plans batches, reconciles labels, clusters failures,
and proposes bounded repairs. Qualified visual models review exact per-record
panels. Only segmentation/refinement providers change pixels, and only the
deterministic certificate service evaluates authority.

Operating memory for every fresh session:

- canonical local intake:
  `C:\Comfy_UI_Main\MaskedWarehouse\Nude\_MASKFACTORY_INTAKE`;
- adopted lineage: 16 datasets, 81,910 records, 322 shards/platform,
  registry `785bfbcca98262a00519b53a360a67d22f23ec9e4b41c9bc38029f402eb9bbcf`,
  index `16a958ffdc6c304174fa8ff5b9b656a607e8e8a9e9610dac9be4a8dbff3c994a`;
- local shards are Windows-only; RunPod shards are remote-only;
- polygons, boxes, actions, references, and holdout retain different roles;
- the 6,537 files in `CivitAI_Top_NSFW_Images` are reference-only generated
  source images across 26 shards, with zero source polygon/bbox/segmentation
  truth; join filenames to `prompts.json` only for weak scene/action/retrieval
  context and never infer pixel anatomy or fine labels from prompt text;
- preserve their exact `Nude/CivitAI_Top_NSFW_Images` relative path and
  reference-only role on RunPod; only newly generated masks that pass full
  per-record qualification may earn machine-verified supervision;
- decode both polygon arrays and valid COCO RLE; require exact RLE canvas/run
  totals, recompute pixel area, retain stale source-area metadata as advisory,
  preserve the 0.90 polygon bbox IoU floor, and allow only the separately logged
  1.5-pixel per-edge rasterization-quantization alternative;
- raw labels are preserved and coarse labels never create fine anatomy;
- one failed record is quarantined/abstained while the shard continues;
- checkpoint each 256; report each 1,000 or material failure/recovery milestone;
- strict visual review returns one bound verdict per record and never clears a
  hard-QC failure or approves from contact-sheet gestalt;
- routine manual CVAT/Kevin review is optional exception handling;
- RunPod transfer probes first and copies only allowlisted missing/drifted paths;
- GPU/VRAM admission, reservation, checkout, capacity scheduling, and file-lock
  governance are disabled.
- the production provider order begins with governed SAM 3.1 and SAM 3D Body
  where applicable, followed by hypothesis-distinct modern providers; SAM2.1
  is benchmark/rollback or a typed bounded fallback only, and local `pth-sam2`
  is optional CVAT assistance with no production authority;
- milestone reports lead with pod/volume/lease identity, exact provider/runtime
  hashes, source/output hashes, hard-QC, strict-review, repair, terminal-outcome,
  and coverage counts. Local checks appear only when a selected local integration
  requirement materially depends on them.

Do not call a canary, transfer, file presence, one-provider result, or critic
opinion complete corpus ingestion. Resume from durable sample/shard state and
continue automatically.
