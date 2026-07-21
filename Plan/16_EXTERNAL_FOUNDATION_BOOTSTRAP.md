# Document 16: External Foundation Bootstrap

**Purpose:** identify already-built datasets, models, and ComfyUI workflows that can accelerate MaskFactory without weakening the gold-mask standard.

**Doc-24 authority amendment:** the foundation stack produces candidates, never unilateral authority.
Its final transaction has two explicitly separate routes: optional human review may create
`human_approved_gold`, while required `core_autonomous_runtime` may create an exact-output
operationally certified artifact after the full autonomous hard-QA/critic/stability/repair policy.
Human review and model-library completeness are not core-runtime prerequisites.

MaskFactory should not hand-build every low-level capability from scratch. The practical foundation is a fused stack of existing human parsing, pose, dense body geometry, object prompting, and mask-refinement tools, wrapped by MaskFactory ontology, QA, and provenance rules.

## 1. Core Position

No single external model or workflow is mask authority.

External tools may produce candidates, priors, boxes, landmarks, probability maps, masks, or overlays.
Final authority is created only by one of the two governed transactions:

`source -> candidate stack -> deterministic QA -> independent critics -> bounded repair -> exact-output operational certificate | autonomous abstention`

or, for the optional human-truth lane:

`source -> candidate stack -> QA panels -> human review -> human_approved_gold package`

Both routes protect the project from the failure mode that caused earlier face masks to drift into
hair or neighboring regions: a model proposal looked plausible but was never checked against
source-visible geometry. Neither a model proposal nor an LLM/VLM verdict can issue authority.

## 2. Highest-Value Model/Workflow Sources

| Source | Use in MaskFactory | Authority level |
|---|---|---|
| Sapiens human part segmentation | Primary full-body semantic parsing prior for body parts | Strong candidate prior, never sole authority |
| SCHP human parsing | Companion pass for clothing/body parsing and cross-checks | Secondary vote |
| DensePose | Front/back, left/right, surface continuity, impossible adjacency checks | Geometry referee |
| DWPose/OpenPose/MediaPipe | Pose, hands, feet, crop boxes, left/right, contact/occlusion cues | Geometry source |
| SAM2 | Boundary refinement from prompts, crop lanes, alpha/matte proposals | Boundary refiner |
| Florence2/GroundingDINO | Open-vocabulary boxes for hair, garments, accessories, objects | Prompt/box source only |
| BiRefNet/RMBG | Full person silhouette, hair/background separation, first-stage mask | Silhouette source |
| CVAT + SAM2 interactor | Human-in-the-loop correction and review | Annotation tool |
| Civitai workflows | Reference wiring for ComfyUI node graphs and prototypes | Prototype/reference only |

## 2.1 Civitai Detector Roles

| Civitai asset | Intended MaskFactory role |
|---|---|
| YOLO Dataset Auto-Annotate Workflow | Bootstrap detector-label generation from local image folders using Florence2/SAM2; useful for creating candidate YOLO datasets, never gold. |
| Hand Detailer/Segmentation - ADetailer | Hand-lane candidate detector for crop experiments and disagreement panels. |
| Eye Detailer/Segmentation - ADetailer | Face protected-region and eye-mask QA cross-check. |
| Mask aDetailer - Face detailer for Eyes, Eyebrows, and Nose | Face-band cross-check for eyes, brows, and nose only. |
| ADetailer 2d mouth detection | Mouth/lip detector vote; must be tested for illustration bias. |
| ADetailer 2d armpit yolov8 | Optional underarm/chest/arm boundary experiment; must be tested for illustration bias. |
| Nails Segmentation - ADetailer | Optional nail/hand-detail detector; not hand or finger authority. |
| RMBG-2.0 | Person/background silhouette and review workflow reference. |
| ADetailer shoes/footwear yolov8 | Lower-body footwear/material detector vote for shoe/sock/foot separation QA. |
| ADetailer Foot Model / foot_yolov8x | Foot-region detector candidates for feet, toes, ankle crops, and pose-vs-mask disagreement panels. |
| ADetailer Hair Model | Hair/face boundary detector vote; useful for preventing face/eye/brow masks from drifting into hair. |
| Socks Segmentation - ADetailer | Sock/material detector vote for lower-leg and foot lanes. |
| assDetailer | Registered detector candidate for glute/rear/pelvis and pants/panties boundary QA; never sole anatomy authority. |
| Teeth, lips, glasses, jewelry, rings, tattoo, head-accessory detectors | Specialist protected-region/object votes for face, hands, skin detail, and accessory preservation. |
| OpenPose and OpenPose+Depth packs | Pose/control stress fixtures for contact, occlusion, hands-on-body, from-below perspective, and difficult body visibility. |
| Multi-person/contact OpenPose packs | Stress fixtures for protected `other_person`, overlapping limbs, torso/chest contact, carrying/hugging, rear views, and multi-character separation. |
| Clothing/tops detection and clothing-swap workflows | Garment-mask references and clothing/material boundary experiments; not material authority without remap and QA. |
| Person cutout / SAM2 workflows | Silhouette and person-mask references for cross-checking BiRefNet/RMBG/SAM2 proposals. |

## 2.2 Uniform Civitai intake

Admission is utility-gated:

- Accept detector, segmentation, workflow, pose, depth, and control assets when they improve candidate masks, stress fixtures, QA coverage, or ComfyUI wiring.
- Record source URL, file hash, local path, version, and role in `Plan\Civitai\civitai_bootstrap_manifest.json`.
- Treat pose packs as stress fixtures by default; eligible source/control pairs may also become training examples or seed reviewed gold after the normal source, annotation, QA, and authority gates pass.
- Treat detector outputs as votes that must be checked against Sapiens/SCHP/DensePose/DWPose/SAM2 consensus.
- Apply the same provenance, license, allowed-use, intake, annotation, QA, and authority rules to every asset.

The current Civitai searches found useful rear/foot/hand/hair/sock/shoe/clothing/accessory detector candidates, person/silhouette workflow references, and several multi-person pose/depth packs. They did not surface a strong dedicated vagina, penis, genital, nipple, areola, or breast segmentation detector. Those regions should therefore be handled by the primary full-body parsing stack, DensePose/pose geometry, protected-region QA, and reviewed gold masks rather than a single Civitai detector.

## 3. Dataset and Platform Sources

Dataset platforms like Dataset Ninja are useful, but only as discovery, inspection, label-preview, and dataset comparison tools. They should not be treated as the canonical license or download authority unless the platform is the dataset's official host.

Useful dataset families:

| Dataset/platform | Why it helps | Suggested MaskFactory use |
|---|---|---|
| LV-MHP / MHP-v2 | Multi-human parsing with part labels and occlusion-heavy people | Evaluate multi-person/protected `other_person`, body-part parsing, occlusion cases |
| LIP | Large human parsing benchmark with body/clothing labels | Training/eval seed for body parsing and clothing priors |
| CIHP | Crowd instance-level human parsing | Multi-person separation, protected other-person class, occlusion stress tests |
| ATR | Clothing-rich human parsing | SCHP-ATR mapping and material/clothing priors |
| PASCAL-Person-Part | Classic person-part segmentation | Low-complexity sanity fixtures for head/torso/limbs |
| DensePose-COCO | Dense body surface annotations | 3D prior and left/right/front/back referee validation |
| COCO person keypoints | Pose/keypoint baseline | DWPose/OpenPose validation and fixture construction |
| MPII Human Pose | Pose diversity | Pose-tags and difficult limb-angle fixtures |
| CelebAMask-HQ / LaPa / Helen | Face/hair/eyes/nose/mouth masks | Face/hair protected region and facial QA lanes |
| DeepFashion / ModaNet / Fashionpedia | Clothing and garment parsing | Material map, straps, waistband, clothing/skin boundary cases |
| EgoHands / hand segmentation datasets | Hands and contact cases | Hand/finger crop lane pretraining and QA fixtures |

## 4. Civitai References Added

`Plan\Civitai\` now contains:

- Civitai metadata for DWPose/DensePose/OpenPose, DensePose ControlNet, Florence2+SAM2, SAM2, SAM2 alpha matte, mask add/subtract, YOLO auto-annotate, hand/eye/mouth/armpit/nail segmentation detectors, RMBG, and selected face-band detectors.
- Extracted workflow JSON for the DWPose/DensePose/OpenPose reference workflow.
- Extracted workflow JSON for the mask add/subtract reference workflow.
- Extracted RMBG workflow references, SAM2/Florence workflow references, YOLO auto-annotation workflow, DWPose/depth workflow, face/hand/armpit/nail/mouth detector assets, and DensePose ControlNet metadata/manual-path registration.
- Detector and fixture intake for shoes/footwear, feet, hair, lips, socks, assDetailer, foot/shoe segmentation, teeth, glasses, jewelry, rings, tattoo, head accessories, OpenPose+Depth poses, covering-body poses, hands-on-body poses, from-below perspective poses, breast/contact poses, multi-person poses, hand-in-hair poses, rear-body poses, and the 525-pose OpenPose pack.
- Registered workflow references for prompt-based Florence segmentation, RotoMaker, SDMatte, Auto Masking/Removing, hand fixing, clothes swap, person cutout, and multi-character control.
- Registered manual downloads for anime foot YOLO, person/female detection, tops/clothing detection, anime hair detection, feet pose/depth assets, hand auto-mask workflows, SAM2 person cutout, multi-character mask/control, multi-control/depth-mask workflows, clothing SegmentAnything workflows, breast-region workflow reference, rear-body OpenPose support, and a large manual-path-only clothing extractor model.

Some older alternate file variants remain metadata-only because Civitai blocked direct file download with API token authentication and they were not manually supplied. Large model binaries are intentionally not duplicated inside the plan folder.

Manual downloads supplied under `Plan\Civitai\manual_downloads` are registered in `Plan\Civitai\manual_downloads_inventory.json` and merged into `Plan\Civitai\civitai_bootstrap_manifest.json` with hashes.

## 4.1 Local MaskedWarehouse Sources

`C:\Comfy_UI_Main\MaskedWarehouse` is a first-class external source root for MaskFactory. It currently includes:

- `CelebAMask-HQ`: face/hair/facial-component masks for protected face and facial QA lanes.
- `LaPa`: face parsing and landmark-associated face masks.
- `Body\LV-MHP-v1`: multi-human/full-body parsing source.
- `Body\UniDataPro_swimsuit-human-segmentation-dataset`: swimsuit/body color segmentation sample; requires color-to-label remap.
- `Body\archive`: body segmentation archive material requiring inventory before use.

See `Plan\MASKEDWAREHOUSE_SOURCE_REGISTRY.md` for the intake rules.

## 5. Foundation Build Order

1. Build the dataset registry first: official URL, license, labels, download method, local path, ontology mapping, split policy, and allowed use.
2. Inventory `C:\Comfy_UI_Main\MaskedWarehouse` and classify each local source as face, full-body, clothing/material, silhouette, fixture, or training-candidate.
3. Install or wrap Sapiens, SCHP, DWPose, DensePose, SAM2, and BiRefNet as separate providers.
4. Run each provider on the same fixture image set and save raw outputs unchanged.
5. Build remap tables from provider labels and warehouse labels to MaskFactory ontology.
6. Add consensus fusion only after raw provider outputs and remaps are inspectable.
7. Add Civitai workflow adapters only where they accelerate ComfyUI graph integration or debug visualization.
8. Never promote a Civitai workflow output directly to gold.

## 6. Minimum Viable External Bootstrap Gate

The external bootstrap foundation is usable only when:

- At least one full-body semantic parser is producing indexed maps.
- At least one pose provider is producing whole-body and hand/foot keypoints.
- At least one silhouette provider is producing person masks.
- SAM2 can refine at least one body-region prompt from a prior.
- DensePose or equivalent 3D signal is available for referee checks, or the lack is explicitly marked degraded.
- Dataset registry includes official sources and license status.
- All outputs are stored with provenance and source-image hash.

## 7. Anti-Patterns

- Do not use a Civitai workflow as a hidden final mask generator.
- Do not mix datasets with incompatible licenses into training without recording license class.
- Do not train on platform preview images or screenshots.
- Do not use Dataset Ninja previews as source masks unless the dataset license and original files are obtained correctly.
- Do not let Florence2/GroundingDINO boxes override pose, parsing, or DensePose on body parts.
- Do not let SAM2 decide semantic labels.

## 8. Governed Auxiliary Specialist Runtime

Downloaded Civitai detector checkpoints become useful only through the controlled runtime in
`src\maskfactory\providers\civitai_auxiliary.py` and
`configs\civitai_auxiliary_runtime.yaml`. Registration alone is not runtime integration.

The runtime has three non-disabled authority tiers:

- `shadow`: execute and preserve raw output for evaluation; no draft influence.
- `assist`: may improve bounded S05/S07 prompts, S08 material seeds, protected-region QA, or
  review overlays. It may not enter S09 as an independent vote.
- `vote`: all `assist` uses plus a maximum 0.05 S09 evidence weight, but only while an exact
  checkpoint/runtime/dataset promotion certificate is current.

Every checkpoint runs sequentially and is selected by explicit view, pose-tag, domain, prior,
or specialist-crop gates. The embedded task and class vocabulary must exactly match config.
Raw masks, boxes, confidence, checkpoint SHA-256, source SHA-256, ROI, and runtime-config hash are
preserved before remapping. Character-left/right hand and foot support is resolved only by overlap
with S05's already-sided crop requests; an auxiliary detector never invents handedness.

Promotion to `vote` requires at least 30 human-approved gold instances, positive mean-IoU and
boundary-F gains of at least 0.01 versus the same pipeline without that detector, and no tracked
hard-class regression. A failed or stale certificate falls back to shadow. Review-time change is
recorded separately and determines whether a technically accurate provider is worth its latency.

Live bootstrap evidence must be treated honestly. On the first governed real-person probe, the
hand/foot/hair specialists produced useful bounded proposals, while the sock detector falsely
labeled bare legs and the headwear detector mislabeled hair. The latter outputs therefore remain
shadow/protected-only until gold evidence supports promotion.

S12 packages include the source-aligned specialist overlay, normalized protected/QA proposals,
and the existing disagreement heatmap so reviewers can judge each proposal independently. The
downloaded mask add/subtract idea is implemented as a controlled canonical-label-map delta: it
accepts strict binary operations, requires an explicit ontology replacement for subtraction,
stages under `work`, refuses frozen gold, regenerates derived masks, reruns hard-block QA, and
still cannot approve the package without the normal human gate.

S11 consumes the same validated auxiliary summary before S12 packaging. Exact ontology candidates
are rendered as separately identified evidence for the local Qwen reviewer and every explicitly
eligible cloud teacher, while protected-only proposals join collision checking. Exact specialist
masks are also registered as proposal-only tournament candidates with their real checkpoint
provenance and complete-map QA results. A specialist/final union disagreement of at least 0.03
forces careful routing and pinned evidence; it does not grant the specialist additional authority.

The 22 pose/control packs are consumed by `datasets/civitai_stress.py`, not merely inventoried.
It verifies archive identity, enumerates deterministic sample assets from every pack, and emits a
reproducible S15 stress/acquisition plan covering contact, occlusion, hands-on-body, rear-body,
from-below, difficult visibility, and multi-person cases. These controls are test inputs; source
images can enter training or reviewed gold only through the separately governed intake path.
