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

## License and Provenance Status

Machine-readable status lives in `configs/maskedwarehouse_provenance.yaml` and
must stay aligned with `configs/maskedwarehouse_inventory.json`. This table is
the human-facing summary of the current intake gate.

| Source key | Official/upstream evidence | Recorded status | Current conversion/training/gold gate |
|---|---|---|---|
| `celebamask_hq` | Local `README.txt`; official `switchablenorms/CelebAMask-HQ` GitHub project. | Non-commercial research/educational only; redistribution/commercial exploitation restricted. | Local non-distributable QA/fixtures only after remap tests and visual QA. Production training and gold-package use blocked until compatible rights are explicit. |
| `lapa` | Public LaPa GitHub project; local split structure with images, labels, and landmarks. | Non-commercial only for research/teaching/publications/personal experimentation. | Local non-distributable QA/fixtures only after remap tests and visual QA. Production training and gold-package use blocked until compatible rights are explicit. |
| `lv_mhp_v1` | Official MHP site; official `ZhaoJ9014/Multi-Human-Parsing` GitHub project; local README with matching category list. | Non-commercial only for research/teaching/scientific publication/personal experimentation. | Local non-distributable QA/fixtures only after remap tests and visual QA. Production training and gold-package use blocked until compatible rights are explicit. |
| `swimsuit_preview` | Local Hugging Face-style `README.md`; UniDataPro/Hugging Face preview page. | CC BY-NC-ND 4.0 preview metadata; full-dataset rights not established. | Visual inspection only. Converted fixtures, derivative remaps, training, and gold-package use blocked. |
| `body_archive` | Local folders plus `Human Segmentation 7 Types.xlsx`; no README/license/upstream URL found. | Unknown/unverified. | All conversion, fixture, training, distribution, and gold-package use blocked until official source and compatible license evidence are recorded. |

Recording a source here does **not** make it MaskFactory gold and does **not**
approve production training. External source masks remain source masks. Any
promotion into fixtures, training seed data, or gold-package workflows requires
the stricter gate recorded per source, plus remap tests, hashing, and visual QA.

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
