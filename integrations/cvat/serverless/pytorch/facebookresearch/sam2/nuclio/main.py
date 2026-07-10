"""Nuclio HTTP adapter for CVAT's generic interactive-segmentation contract."""

from __future__ import annotations

import base64
import io
import json

from PIL import Image

from model_handler import ModelHandler


def init_context(context) -> None:
    """Load SAM2 once while Nuclio initializes the worker."""
    context.logger.info("SAM2 CPU initialization: 0%")
    context.user_data.model = ModelHandler()
    context.logger.info("SAM2 CPU initialization: 100%")


def handler(context, event):
    """Decode a CVAT request and return its full-resolution binary mask."""
    data = event.body
    image = Image.open(io.BytesIO(base64.b64decode(data["image"]))).convert("RGB")
    mask = context.user_data.model.handle(
        image=image,
        pos_points=data.get("pos_points", []),
        neg_points=data.get("neg_points", []),
        box=data.get("obj_bbox"),
    )
    return context.Response(
        body=json.dumps({"mask": mask.tolist()}),
        headers={},
        content_type="application/json",
        status_code=200,
    )
