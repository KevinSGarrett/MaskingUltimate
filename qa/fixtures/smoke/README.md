# Model smoke fixtures

## `ultralytics_bus_adults.jpg`

- Purpose: M1 YOLO11m one-image inference smoke; the gate requires at least one
  COCO class-0 person detection.
- Source: the official `ultralytics` Python package `ultralytics/assets/bus.jpg`,
  corresponding to <https://ultralytics.com/images/bus.jpg>.
- Visible-subject review: street scene with clearly adult pedestrians; no
  apparent minors.
- License: Ultralytics AGPL-3.0 package asset; currently registered for local QA.
  Any later training or human-reviewed-gold use requires the normal provenance,
  license, allowed-use, intake, annotation, and QA gates.
- SHA-256: `c02019c4979c191eb739ddd944445ef408dad5679acab6fd520ef9d434bfbc63`.

## `mediapipe_thumb_up.jpg`

- Purpose: M6 MediaPipe Hand Landmarker smoke; requires exactly one hand with
  21 normalized landmarks, 21 world landmarks, and handedness.
- Source: official MediaPipe test asset
  <https://storage.googleapis.com/mediapipe-assets/thumb_up.jpg>.
- Scope: isolated hand crop; no age inference is possible or required because
  no identifiable person is depicted.
- License: MediaPipe Apache-2.0 test asset; currently registered for local QA.
- SHA-256: `5d673c081ab13b8a1812269ff57047066f9c33c07db5f4178089e8cb3fdc0291`.

## Model expectation manifest

`model_expectations.json` maps every file-backed registry key to its governed
smoke image and exact expected inference-output SHA-256. Multiple models may
reuse the same governed image; the per-model runner and output hash are unique.
The doctor replays every runner and fails if any output differs from this
registry-backed snapshot. Ollama-managed models use the separate live image
probe and API/`ollama list` digest checks because they have no checkpoint path.
