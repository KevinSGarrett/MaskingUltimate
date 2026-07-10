# Model smoke fixtures

## `ultralytics_bus_adults.jpg`

- Purpose: M1 YOLO11m one-image inference smoke; the gate requires at least one
  COCO class-0 person detection.
- Source: the official `ultralytics` Python package `ultralytics/assets/bus.jpg`,
  corresponding to <https://ultralytics.com/images/bus.jpg>.
- Visible-subject review: street scene with clearly adult pedestrians; no
  apparent minors.
- License: Ultralytics AGPL-3.0 package asset; local QA fixture only, never a
  MaskFactory training or gold image.
- SHA-256: `c02019c4979c191eb739ddd944445ef408dad5679acab6fd520ef9d434bfbc63`.
