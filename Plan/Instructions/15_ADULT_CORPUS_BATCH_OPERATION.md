# 15 — Adult Corpus Batch Operation

Read `Plan/26_ADULT_CORPUS_AUTONOMOUS_BATCH_INGESTION_SPEC.md` and the seven
files named by `_MASKFACTORY_INTAKE/README_START_HERE.md` before operating this
corpus. Adopt the recorded seals before rebuilding. Run the intake validator
with `--rehash sample`, then use `tools/run_nude_corpus_canary.py` for the first
local lane proof.

Operating memory for every fresh session:

- canonical local intake:
  `C:\Comfy_UI_Main\MaskedWarehouse\Nude\_MASKFACTORY_INTAKE`;
- adopted lineage: 16 datasets, 81,910 records, 322 shards/platform,
  registry `785bfbcca98262a00519b53a360a67d22f23ec9e4b41c9bc38029f402eb9bbcf`,
  index `16a958ffdc6c304174fa8ff5b9b656a607e8e8a9e9610dac9be4a8dbff3c994a`;
- local shards are Windows-only; RunPod shards are remote-only;
- polygons, boxes, actions, references, and holdout retain different roles;
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
- GPU work requires the shared coordinator; transfers do not.

Do not call a canary, transfer, file presence, one-provider result, or critic
opinion complete corpus ingestion. Resume from durable sample/shard state and
continue automatically.
