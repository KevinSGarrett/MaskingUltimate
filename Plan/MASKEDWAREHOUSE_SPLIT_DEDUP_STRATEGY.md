# MaskedWarehouse Split-Dedup Strategy

**Proof tier:** `LIVE_PASS` for the three eligible sources.
**Authority boundary:** train-only `weighted_pseudo_label`; never gold, holdout, or production-mask authority.

## Goal

Before an eligible MaskedWarehouse source (`celebamask_hq`, `lapa`, `lv_mhp_v1`) may be
admitted, every decodable source image is bound to one exact/perceptual split group. A
hash-bound decode failure is quarantined from qualification and training without stopping
the remaining corpus.

## Locked algorithm

| Field | Value |
|---|---|
| Exact identity | SHA-256 of source image bytes, verified against its sealed source manifest |
| Primary perceptual hash | `dHash64` 9x8 bilinear grayscale |
| Secondary perceptual hash | `pHash64` 32x32 DCT top 8x8 |
| Near-duplicate rule | fixed-anchor dHash <= 3 **and** pHash <= 6 |
| Anti-chain rule | exact components are formed first; one deterministic representative may join only one fixed perceptual anchor |
| Partition rule | all records sharing `split_group_id` remain in one downstream partition |
| Implementation | `src/maskfactory/external_supervision_dedup.py` |
| Unit proof | `tests/test_external_supervision_dedup.py`, `tests/test_nude_corpus_dedup.py` |

The original single-dHash transitive result was rejected after it formed unrelated groups of
2,676 and 1,521 records. Its bytes and seal remain retained as negative evidence. Thresholds
were not lowered to obtain the accepted result.

## Accepted live result (2026-07-22)

- Source images: 57,148 (CelebAMask-HQ 30,000; LaPa 22,168; LV-MHP 4,980)
- Decodable grouped records: 57,147
- Quarantined: `lv_mhp_v1:LV-MHP-v1/images/3492.jpg` (sealed bytes matched; decode failed)
- Split groups: 53,840
- Duplicate records: 3,307
- Upstream split-conflict groups: 184; these groups must stay together downstream
- Maximum group size: 6; groups above 10: 0
- Accepted evidence seal: `45283eff4341cf58db079f981a95422fef8e97b29fc85b56332f0469edce9ae4`
- Accepted file SHA-256: `72f5555046b5999c0a7fe014748bd545ad5b0205ed878d7d7a4a26aa6cb26cf7`
- Compact committed evidence: `qa/live_verification/external_supervision_live_admission_20260722.json`

All three source-specific qualification bundles verify with no unmet gates. Admission remains
train-only weighted pseudo-label supervision. External masks do not become MaskFactory gold.

## Reproduction

```text
python -m maskfactory.external_supervision_dedup \
  --celebamask_hq-manifest <sealed> --celebamask_hq-root <root> \
  --lapa-manifest <sealed> --lapa-root <root> \
  --lv_mhp_v1-manifest <sealed> --lv_mhp_v1-root <root> \
  --output <immutable split_dedup_passed.json>
```

Materialize the accepted artifact under
`runtime_artifacts/external_supervision/shared/split_dedup_passed.json`, rebuild the gap
report, and rebuild all three qualification bundles. Never substitute the earlier STATIC
strategy receipt or the rejected single-hash artifact for the accepted live evidence.
