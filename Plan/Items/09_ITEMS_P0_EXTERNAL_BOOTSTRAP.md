# ITEMS - Phase P0: External Foundation Bootstrap

Goal: use already-built datasets, models, and Civitai workflows to seed MaskFactory without reducing the gold-mask standard.

## MF-P0-09 — External source registry and bootstrap plan (spec: 16)
- [ ] MF-P0-09.01 Create `configs\external_sources.yaml` with entries for Sapiens, SCHP, DWPose/OpenPose, MediaPipe, DensePose, SAM2, Florence2, GroundingDINO, BiRefNet/RMBG, CVAT, and selected datasets.
- [ ] MF-P0-09.02 Record official source URL, license status, local install/cache path, version, expected output type, and MaskFactory role for each provider.
- [ ] MF-P0-09.03 Build a dataset registry covering LV-MHP/MHP-v2, LIP, CIHP, ATR, PASCAL-Person-Part, DensePose-COCO, COCO keypoints, MPII, CelebAMask-HQ/LaPa/Helen, and clothing datasets such as DeepFashion/ModaNet/Fashionpedia.
- [ ] MF-P0-09.04 Mark Dataset Ninja and similar platforms as discovery/inspection aids only unless they are the official dataset host.

## MF-P0-10 — Civitai workflow reference intake (spec: 16, Civitai README)
- [ ] MF-P0-10.01 Review `Plan\Civitai\civitai_bootstrap_manifest.json` and classify each Civitai item as provider inference, ComfyUI graph reference, annotation aid, QA visualization, or reject.
- [ ] MF-P0-10.02 Inspect extracted `imageToOpenPose.json` and document required custom nodes for DWPose/DensePose/OpenPose preprocessing.
- [ ] MF-P0-10.03 Inspect extracted `mask_add_remove_self.json` and document how mask add/subtract can support human correction and QA without becoming mask authority.
- [ ] MF-P0-10.04 For metadata-only Civitai workflows, record whether manual browser download is needed, blocked, unnecessary, or superseded by official upstream repositories.

## MF-P0-11 — External provider probe command (spec: 16)
- [ ] MF-P0-11.01 Implement `maskfactory external probe` to report installed/missing providers and model files without downloading large weights automatically.
- [ ] MF-P0-11.02 Implement provider-level hash/provenance capture for model files and workflow references.
- [ ] MF-P0-11.03 Probe output writes JSON evidence listing provider availability, version, model path, and degraded/fallback status.

## MF-P0-12 — External fixture smoke run (spec: 16)
- [ ] MF-P0-12.01 Implement `maskfactory external run-fixtures` for a tiny fixture set and save raw provider outputs before remap or fusion.
- [ ] MF-P0-12.02 Generate side-by-side provider panels: source, silhouette, parsing, pose, DensePose, SAM2 proposal, and disagreement heatmap.
- [ ] MF-P0-12.03 Verify no provider output is promoted directly to gold and every output includes source-image hash plus provider provenance.

## MF-P0-13 — Local MaskedWarehouse intake (spec: 16, MASKEDWAREHOUSE_SOURCE_REGISTRY)
- [ ] MF-P0-13.01 Inventory `C:\Comfy_UI_Main\MaskedWarehouse` datasets and write per-source image/mask counts, file formats, and label encodings.
- [ ] MF-P0-13.02 Build initial remap plans for CelebAMask-HQ, LaPa, LV-MHP-v1, the swimsuit segmentation sample, and the Body archive.
- [ ] MF-P0-13.03 Generate sample overlays for at least 5 face-source masks and 5 body-source masks to verify source-mask alignment before training use.
- [ ] MF-P0-13.04 Record license/provenance status for every MaskedWarehouse source before any converted mask enters fixtures, training, or gold package workflows.

## MF-P0-14 - Adult-inclusive Civitai body-resource intake (spec: 16, Civitai README)
- [ ] MF-P0-14.01 Classify every adult/NSFW-labeled Civitai detector, workflow, pose pack, and manual-download candidate by MaskFactory role: provider vote, ComfyUI graph reference, stress fixture, QA probe, or reject.
- [ ] MF-P0-14.02 Register usable auxiliary detector models for shoes/footwear, feet, hair, lips, socks, hands, face bands, armpits, nails, mouth, and any manually supplied rear/accessory/body detectors with hash, path, version, and install target.
- [ ] MF-P0-14.03 Build a pose/control stress-fixture list from adult OpenPose/OpenPose+Depth packs covering contact, occlusion, hands-on-body, rear-body, from-below perspective, and difficult body visibility.
- [ ] MF-P0-14.04 Verify no adult/NSFW Civitai asset is used as training data, gold reference masks, or production mask authority until provenance, license, consent status, and allowed use are explicitly recorded.
