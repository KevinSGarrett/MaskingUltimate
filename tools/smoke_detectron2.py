"""Verify the pinned detectron2 extension executes a CUDA 12.8 operator."""

from __future__ import annotations

import json

import detectron2
import detectron2._C as detectron2_c
import torch
from detectron2.layers import nms_rotated


def main() -> None:
    boxes = torch.tensor(
        [
            [10.0, 10.0, 8.0, 8.0, 0.0],
            [10.0, 10.0, 8.0, 8.0, 0.0],
            [30.0, 30.0, 4.0, 4.0, 15.0],
        ],
        device="cuda",
    )
    scores = torch.tensor([0.9, 0.8, 0.7], device="cuda")
    keep = nms_rotated(boxes, scores, 0.5)
    torch.cuda.synchronize()

    result = {
        "detectron2_version": detectron2.__version__,
        "extension": detectron2_c.__file__,
        "compiled_cuda_version": detectron2_c.get_cuda_version(),
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "device": torch.cuda.get_device_name(0),
        "capability": list(torch.cuda.get_device_capability(0)),
        "nms_input_device": str(boxes.device),
        "nms_output_device": str(keep.device),
        "nms_keep": keep.cpu().tolist(),
    }
    print(json.dumps(result, indent=2))

    assert result["compiled_cuda_version"] == "CUDA 12.8"
    assert result["capability"] == [12, 0]
    assert result["nms_input_device"] == "cuda:0"
    assert result["nms_output_device"] == "cuda:0"
    assert result["nms_keep"] == [0, 2]


if __name__ == "__main__":
    main()
