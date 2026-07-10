# MaskedWarehouse Source Registry

This registry records the already-downloaded masked image datasets under `C:\Comfy_UI_Main\MaskedWarehouse` that should feed MaskFactory.

These datasets are not automatically gold. They are source material for remapping, fixtures, provider validation, training seed data, and QA panels. Every dataset must still pass license/provenance review, label remapping, source-image hashing, and MaskFactory format conversion before it can be used for training or gold-package creation.

## Local Warehouse Roots

| Local path | Current role | Notes |
|---|---|---|
| `C:\Comfy_UI_Main\MaskedWarehouse\CelebAMask-HQ` | Face, hair, brows, eyes, nose, mouth, lips, skin/neck candidate source | Useful for face protected regions, face/hair QA, and facial component remap tests. |
| `C:\Comfy_UI_Main\MaskedWarehouse\LaPa` | Face parsing and landmark-associated face masks | Useful for face geometry validation and cross-checking facial masks against landmark priors. |
| `C:\Comfy_UI_Main\MaskedWarehouse\Body\LV-MHP-v1` | Multi-human/full-body parsing source | Highest-value body source currently present. Use for body-part parsing, occlusion, multi-person/protected-person stress tests. |
| `C:\Comfy_UI_Main\MaskedWarehouse\Body\UniDataPro_swimsuit-human-segmentation-dataset` | Swimsuit/body color segmentation sample | Useful for visible body shape and skin/clothing boundary experiments. Masks are RGB color segmentation masks and require color-to-label remap. |
| `C:\Comfy_UI_Main\MaskedWarehouse\Body\archive` | Body segmentation archive material | Requires inventory before use; likely useful for body silhouette and broad human segmentation references. |

## Required Intake Steps

1. Create an inventory JSON per dataset: source root, image count, mask count, file extensions, dimensions, label format, and hash sample.
2. Record license and official upstream source.
3. Build explicit remap tables into MaskFactory `PART`, `MATERIAL`, `REGION`, and `PROTECTED` labels.
4. Convert only through scripts; do not hand-copy masks into gold package folders.
5. Generate visual QA panels before using a converted dataset for training or fixtures.
6. Mark ambiguous, missing, or incompatible labels as `ambiguous_do_not_use` instead of forcing them into the ontology.

## Recommended Use by MaskFactory Stage

| Stage | Dataset use |
|---|---|
| S02 silhouette | Body archive, swimsuit segmentation, LV-MHP person masks. |
| S03 human parsing | LV-MHP, LIP/CIHP if added later, broad body archive after remap. |
| S04 pose sanity | Use image/mask pairs to build pose/draft fixtures, but keypoints still come from pose providers. |
| S05 geometry priors | LV-MHP and swimsuit masks for broad body region sanity, not final joint/finger/toe splits. |
| S08 material/clothing | Swimsuit/body sample and future Fashionpedia/DeepFashion/ModaNet sources. |
| Face/hair protected regions | CelebAMask-HQ and LaPa. |
| Training seed data | Only after license/provenance/remap/QA conversion gates pass. |

## Non-Negotiable Rules

- Existing masks in `MaskedWarehouse` are source masks, not MaskFactory gold masks.
- Do not mix face-only datasets into full-body part training without explicit role tags.
- Do not train on RGB color masks until a deterministic color-to-label map is written and tested.
- Do not let any external dataset override the visible-pixel-only rule.
- Do not use warehouse data without recording license/provenance status.

