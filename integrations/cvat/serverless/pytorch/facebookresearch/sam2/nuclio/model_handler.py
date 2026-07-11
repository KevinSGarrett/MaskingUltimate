"""CPU-only SAM 2.1 image predictor used by the CVAT Nuclio adapter."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import torch
from PIL import Image
from sam2.build_sam import build_sam2
from sam2.sam2_image_predictor import SAM2ImagePredictor


class ModelHandler:
    """Own a single CPU predictor; Nuclio limits this worker to one request."""

    def __init__(self) -> None:
        checkpoint = "/opt/nuclio/sam2/sam2.1_hiera_base_plus.pt"
        config = "configs/sam2.1/sam2.1_hiera_b+.yaml"
        model = build_sam2(config, checkpoint, device="cpu")
        self.predictor = SAM2ImagePredictor(model)

    def handle(
        self,
        *,
        image: Image.Image,
        pos_points: Sequence[Sequence[float]],
        neg_points: Sequence[Sequence[float]],
        box: Sequence[float] | None,
    ) -> np.ndarray:
        """Predict the highest-scoring mask for CVAT point/box prompts."""
        points = [*pos_points, *neg_points]
        if not points and box is None:
            raise ValueError("SAM2 needs at least one point or a bounding box")

        coords = np.asarray(points, dtype=np.float32) if points else None
        labels = (
            np.asarray([1] * len(pos_points) + [0] * len(neg_points), dtype=np.int32)
            if points
            else None
        )
        prompt_box = np.asarray(box, dtype=np.float32) if box is not None and len(box) else None
        if prompt_box is not None and prompt_box.shape != (4,):
            raise ValueError(
                f"SAM2 bounding box must have four coordinates, got {prompt_box.shape}"
            )

        with torch.inference_mode():
            self.predictor.set_image(np.asarray(image))
            masks, scores, _ = self.predictor.predict(
                point_coords=coords,
                point_labels=labels,
                box=prompt_box,
                multimask_output=True,
            )
        best = masks[int(np.argmax(scores))]
        return best.astype(np.uint8) * 255
