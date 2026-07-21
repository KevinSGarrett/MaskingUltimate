# Instruction 09: External Foundation Bootstrap Playbook

Use this playbook when turning existing datasets, models, or Civitai workflows into MaskFactory foundation components.

## Read Order

1. `Plan\16_EXTERNAL_FOUNDATION_BOOTSTRAP.md`
2. `Plan\Civitai\README.md`
3. `Plan\Civitai\civitai_bootstrap_manifest.json`
4. `Plan\Civitai\manual_downloads_inventory.json`
5. `Plan\MASKEDWAREHOUSE_SOURCE_REGISTRY.md`
6. `Plan\07_PIPELINE_STAGE_SPECS.md`
7. `Plan\08_SPECIALIST_LANES_SPEC.md`

## Rules

- Treat every external model as a proposal source, not truth.
- Preserve raw output before remapping or post-processing.
- Record source URL, model version, file hash, install path, inference settings, and source-image hash.
- Map labels through explicit config tables; do not infer class names in code.
- Use Civitai workflows to learn graph wiring, not to replace MaskFactory stages.
- Do not discard adult/NSFW-labeled Civitai assets solely because of the label. Evaluate them by masking/segmentation/detector/pose/control/workflow utility, provenance, license, and safe/legal use.
- Adult/NSFW Civitai assets may be detector candidates, pose/control stress fixtures, ComfyUI wiring references, QA probes, and training inputs. They are eligible for training and may seed human-reviewed gold after explicit provenance, license, adult-age/consent, allowed-use, intake, annotation, and QA verification.
- Use Dataset Ninja and similar platforms to discover datasets, inspect label taxonomies, and compare coverage. Download from official dataset sources whenever possible.
- Store model weights outside `Plan\`, normally under model cache or runtime model directories.
- Store documentation, manifests, small workflow JSONs, and dataset registry records inside `Plan\`.
- Treat `C:\Comfy_UI_Main\MaskedWarehouse` as an available local source root for face and body segmentation data, but still require inventory, provenance, remap, and QA before training use.

## Getting Started

1. Create `configs\external_sources.yaml` with provider entries for Sapiens, SCHP, DWPose, DensePose, SAM2, BiRefNet, Florence2, GroundingDINO, and each selected dataset.
2. Create one provider wrapper per model family under `src\maskfactory\providers\`.
3. Add a `maskfactory external probe` command that reports installed/missing providers.
4. Add a `maskfactory external run-fixtures` command that runs every installed provider on a tiny fixture set and writes raw outputs under `work\external_probe\`.
5. Add remap tables under `configs\remap\`.
6. Add QA overlays for provider-vs-provider disagreement before fusion.

## Dataset Intake Checklist

For each dataset:

- Official home page or repository.
- License and allowed use.
- Download command or manual download instruction.
- Label list and label IDs.
- Whether labels are person-part, material, clothing, keypoint, dense surface, instance, or face parsing.
- Mapping into MaskFactory PART/MATERIAL/REGION labels.
- Split policy: train, validation, holdout, fixture-only, or license-blocked.
- Known limitations: anime-only, face-only, clothing-only, low resolution, no left/right, no hands/fingers, no toes, no occlusion labels.

## Local MaskedWarehouse Checklist

For every dataset already under `C:\Comfy_UI_Main\MaskedWarehouse`:

- Record its local path in `Plan\MASKEDWAREHOUSE_SOURCE_REGISTRY.md`.
- Count images and masks.
- Identify label format: binary, RGB color map, indexed PNG, polygon, text annotations, or mixed.
- Identify whether it is face-only, full-body, clothing/material, silhouette, or specialist-lane data.
- Build a deterministic remap file before converting any masks.
- Generate QA overlays on a small sample before accepting it into fixtures or training.
- Keep source masks separate from MaskFactory gold packages.

## Civitai Workflow Intake Checklist

For each Civitai workflow:

- Store metadata JSON in `Plan\Civitai\metadata\`.
- Store small workflow JSON/ZIP in `Plan\Civitai\archives\` and `Plan\Civitai\extracted\` when Civitai download permits.
- Record blocked downloads in `civitai_bootstrap_manifest.json`.
- If a file is manually downloaded into `Plan\Civitai\manual_downloads`, register it in `manual_downloads_inventory.json`, hash it, extract/copy it according to policy, and merge the registered path into `civitai_bootstrap_manifest.json`.
- Identify required custom nodes and model files.
- Decide whether the workflow is useful for provider inference, ComfyUI serving, annotation review, or QA visualization.
- Rebuild the graph as a controlled MaskFactory workflow before production use.

## Adult/NSFW Body-Resource Intake Checklist

For each adult/NSFW-labeled Civitai or dataset resource:

- Record the actual role: detector, segmentation model, pose/depth fixture, prompt workflow, annotation aid, or reject.
- Record whether the asset contains model weights, workflow JSON, pose images, masks, or only metadata.
- Verify download status in `Plan\Civitai\civitai_bootstrap_manifest.json`: downloaded, manual-browser-required, metadata-only, blocked, or rejected.
- Use adult pose/control packs to stress test occlusion, contact, body visibility, perspective, hands-on-body, rear-body, and clothing/skin boundary cases.
- Use adult/body detectors only as proposal votes; compare against Sapiens, SCHP, DensePose, DWPose/MediaPipe, SAM2, and source-image overlays.
- Promote eligible adult/NSFW assets into training datasets, and into the normal human-reviewed gold workflow, once license, provenance, adult-age/consent status, and allowed use are explicitly recorded and all intake/annotation/QA gates pass.

## Provider Authority Matrix

| Provider | Allowed output | Forbidden output |
|---|---|---|
| Sapiens | Semantic part prior and probability maps | Final gold mask |
| SCHP | Clothing/body parsing cross-check | Final material map without fusion |
| DWPose/OpenPose/MediaPipe | Keypoints, crop boxes, handedness evidence | Pixel masks |
| DensePose | Surface/referee evidence | Standalone body-part map |
| SAM2 | Refined mask candidate from prompts | Semantic label decision |
| Florence2/GroundingDINO | Text-conditioned boxes/prompts | Body-part authority |
| BiRefNet/RMBG | Person silhouette candidate | Atomic body-part masks |
| Civitai workflow | Prototype graph/reference wiring | Unreviewed production stage |
