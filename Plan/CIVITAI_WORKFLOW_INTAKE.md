# Civitai Workflow Intake Decisions

This tracked note records the P0 Civitai intake decisions. The local source tree under
`Plan\Civitai\` remains reference material only and is intentionally excluded from Git.
The complete per-file classification is generated at
`configs\civitai_classifications.json` by `tools\classify_civitai_manifest.py`.

Every listed asset has `proposal_or_reference_only` authority. No Civitai output can
be promoted directly to a MaskFactory gold mask. Training or gold use additionally
requires explicit license, provenance, consent, and allowed-use review.

## `imageToOpenPose.json`

Inspected source:
`Plan\Civitai\extracted\simpleImageToDWPoseDense_v10\imageToOpenPose.json`.
The graph contains 12 nodes and 11 links and requires:

- ComfyUI core: `LoadImage`, `PreviewImage`, and `PrimitiveInt`.
- `comfyui_controlnet_aux` 1.1.0: `DWPreprocessor`, `DensePosePreprocessor`,
  and the unused/bypassable `AnimalPosePreprocessor`. Its referenced runtime files
  include `yolo_nas_l_fp16.onnx`, `dw-ll_ucoco_384_bs5.torchscript.pt`,
  `densepose_r50_fpn_dl.torchscript`, `yolox_l.torchscript.pt`, and
  `rtmpose-m_ap10k_256_bs5.torchscript.pt`.
- `comfyui-openpose` 1.0.0: `OpenPose - Get poses`, configured for COCO at
  confidence 0.4 and emitting both a keypoint image and keypoint-only data.
- `cg-use-everywhere` 6.2.1: four `Anything Everywhere` routing nodes.
- rgthree-comfy: `Fast Groups Bypasser (rgthree)` for choosing the displayed
  preprocessor output.

MaskFactory use: a ComfyUI graph reference for DWPose/DensePose/OpenPose
preprocessing and debug panels. Pose keypoints are geometry evidence; DensePose is a
referee. Neither is pixel-mask or semantic-label authority. AnimalPose is not part of
the human pipeline and should remain bypassed.

## `mask_add_remove_self.json`

Inspected source:
`Plan\Civitai\extracted\SegmentMaskMaskAddRemove_v10\mask_add_remove_self.json`.
The graph contains 22 nodes and 22 links, with separate subtract and add paths:

- ComfyUI core: `LoadImage`.
- ComfyUI Impact Subpack: `UltralyticsDetectorProvider`; the bundled graph expects
  `segm/person_yolov8m-seg.pt`.
- ComfyUI Impact Pack: `SegmDetectorSEGS`, `SegsToCombinedMask`, `MaskToSEGS`,
  `SubtractMaskForEach`, and `AddMask`.
- ComfyUI Essentials: `MaskPreview+` preview nodes.
- rgthree-comfy: presentation-only `Label (rgthree)` nodes.

The subtract path converts an edited mask to SEGS and subtracts those regions from
the detector SEGS. The add path converts detector and edited masks to combined masks
and applies `AddMask`. This is classified as an annotation aid: it can accelerate a
human correction or produce a QA comparison, but its result is never written as
gold directly. A MaskFactory adapter must import the result through the canonical
label maps, regenerate binary masks through `png_strict`, rerun all format and
semantic QA, preserve provenance, and still require human approval.

## Metadata-only variants

Six records failed direct Civitai download with HTTP 401, but each is an older variant
with a newer downloaded replacement. Their disposition is therefore
`superseded_by_downloaded_variant` and their download action is `unnecessary`:

| Metadata-only file | Downloaded replacement |
|---|---|
| `yoloDatasetAuto_v10.zip` | `yoloDatasetAuto_v20.zip` |
| `handDetailer_v1b.zip` | `handDetailer_v2V9c.zip` |
| `handDetailer_v1.zip` | `handDetailer_v2V9c.zip` |
| `eyeDetailerSegmentation_v1b.zip` | `eyeDetailerSegmentation_v2.zip` |
| `eyeDetailerSegmentation_v1.zip` | `eyeDetailerSegmentation_v2.zip` |
| `adetailer2dArmpitYolov8_v10Bbox.zip` | `adetailer2dArmpitYolov8_v10Segmentation.zip` |

No manual browser download is required for these variants. If a future comparison
specifically needs an older variant, it must be reopened as a new, explicit intake
decision rather than silently downloaded.
