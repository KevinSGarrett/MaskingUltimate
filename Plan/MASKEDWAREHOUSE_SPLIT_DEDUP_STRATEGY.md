# MaskedWarehouse Split-Dedup Strategy

**Proof tier:** `STATIC_PASS` planning + algorithm contract only.  
**Not:** full-corpus admission, gold labeling, runtime qualification, or production training enablement.

## Goal

Before any eligible MaskedWarehouse source (`celebamask_hq`, `lapa`, `lv_mhp_v1`) may be
admitted as train-only `external_labeled_reference` / `weighted_pseudo_label`, every source
image must be bound into an exact/perceptual split group so near-duplicates cannot leak
across train/val/test partitions (`split_dedup_passed` gate).

## Locked algorithm (already implemented)

| Field | Value |
|---|---|
| Exact identity | SHA-256 of source image bytes |
| Perceptual hash | `dHash64` 9×8 bilinear grayscale |
| Pairing index | Segmented Hamming blocks (`find_hamming_pairs`) |
| Default threshold | Hamming ≤ 3 |
| Partition rule | All records sharing `split_group_id` stay in one downstream partition |
| Implementation | `src/maskfactory/external_supervision_dedup.py` |
| Unit proof | `tests/test_external_supervision_dedup.py` |

External source masks remain **never gold**. Split-dedup evidence cannot mint gold,
holdout, calibration, or certified-volume authority.

## Why full live materialization is deferred

A complete cross-source run hashes and dHashes on the order of **~57k images** and emits a
large sealed `records[]` artifact. Under current disk pressure this project must not:

- copy MaskedWarehouse trees into the repo
- materialize a multi-GB sealed record dump under `runtime_artifacts/`
- claim `split_dedup_passed` from fixtures or strategy text alone

## STATIC strategy (honest tiers)

1. **Algorithm STATIC_PASS** — unit/fixture tests prove exact union, perceptual pairing,
   upstream-split conflict detection, seal/schema, and fail-closed hash drift.
2. **Strategy receipt STATIC_PASS** — machine-readable receipt binds this document hash and
   explicitly sets `admission_ready=false`, `source_masks_are_gold=false`,
   `full_corpus_materialized=false`.
3. **Bounded sample probe STATIC_PASS** — optional tiny deterministic sample from sealed
   manifests may exercise the live path without claiming the admission gate.
4. **Full-corpus `split_dedup_passed`** — remains **open** until a capacity-safe off-project
   or project-contained sealed artifact covers all three manifests end-to-end.

## Admission rule

`any_source_admitted` stays false while `split_dedup_passed` is missing for any eligible
source. Strategy receipts and fixture gate sets are **not** substitutes for the live gate.

## Operator resume

When free disk and I/O budget allow, run:

```text
python -m maskfactory.external_supervision_dedup \
  --celebamask_hq-manifest <sealed> --celebamask_hq-root <root> \
  --lapa-manifest <sealed> --lapa-root <root> \
  --lv_mhp_v1-manifest <sealed> --lv_mhp_v1-root <root> \
  --output <sealed split_dedup_passed.json>
```

Then materialize under `runtime_artifacts/external_supervision/shared/` and re-run the
qualification gap report. Do not free disk destructively to force this step.
