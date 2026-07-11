"""One-image SCHP ATR/LIP smoke in the authoritative CUDA WSL environment."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import types
from collections import OrderedDict
from pathlib import Path

import cv2
import numpy as np
import torch
from torch import nn

REPOSITORY = "https://github.com/GoGoDuck912/Self-Correction-Human-Parsing.git"
REVISION = "eb84c432cc697f494d99662a05f2335eb2f26095"
SOURCE = Path.home() / ".cache" / "maskfactory" / "schp" / REVISION
SETTINGS = {"atr": (18, 512), "lip": (20, 473)}


class PureInferenceABN(nn.BatchNorm2d):
    """State-compatible inference replacement for SCHP's obsolete CUDA ABN."""

    def __init__(self, num_features: int, activation: str = "none", **kwargs):
        super().__init__(num_features, **kwargs)
        self.activation = activation

    def forward(self, tensor: torch.Tensor) -> torch.Tensor:
        result = super().forward(tensor)
        if self.activation == "leaky_relu":
            return torch.nn.functional.leaky_relu(result, 0.01, inplace=False)
        if self.activation == "elu":
            return torch.nn.functional.elu(result, inplace=False)
        if self.activation == "relu":
            return torch.nn.functional.relu(result, inplace=False)
        return result


def _ensure_source() -> None:
    if (SOURCE / "networks" / "AugmentCE2P.py").is_file():
        return
    SOURCE.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--filter=blob:none", REPOSITORY, str(SOURCE)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(SOURCE), "checkout", "--detach", REVISION],
        check=True,
        capture_output=True,
        text=True,
    )


def infer(checkpoint: Path, image_path: Path, dataset: str) -> np.ndarray:
    _ensure_source()
    num_classes, input_size = SETTINGS[dataset]
    compatibility_module = types.ModuleType("modules")
    compatibility_module.InPlaceABNSync = PureInferenceABN
    sys.modules["modules"] = compatibility_module
    sys.path.insert(0, str(SOURCE))
    import networks

    model = networks.init_model("resnet101", num_classes=num_classes, pretrained=None)
    checkpoint_document = torch.load(checkpoint, map_location="cpu", weights_only=True)
    state = OrderedDict(
        (name.removeprefix("module."), tensor)
        for name, tensor in checkpoint_document["state_dict"].items()
    )
    model.load_state_dict(state, strict=True)
    model.eval().cuda()

    bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError(f"cannot read smoke image {image_path}")
    resized = cv2.resize(bgr, (input_size, input_size), interpolation=cv2.INTER_LINEAR)
    tensor = torch.from_numpy(resized).permute(2, 0, 1).float().div(255)
    mean = torch.tensor([0.406, 0.456, 0.485]).view(3, 1, 1)
    std = torch.tensor([0.225, 0.224, 0.229]).view(3, 1, 1)
    tensor = ((tensor - mean) / std).unsqueeze(0).cuda()
    with torch.inference_mode():
        output = model(tensor)
    logits = output[0][-1]
    if logits.ndim != 4 or logits.shape[:2] != (1, num_classes):
        raise ValueError(f"unexpected logits shape {list(logits.shape)}")
    logits = torch.nn.functional.interpolate(
        logits.float(), size=(input_size, input_size), mode="bilinear", align_corners=True
    )
    probabilities = logits.softmax(dim=1)[0].cpu().numpy().astype(np.float32)
    del tensor, logits, output, model
    torch.cuda.empty_cache()
    return probabilities


def run(checkpoint: Path, image_path: Path, dataset: str) -> dict[str, object]:
    num_classes, input_size = SETTINGS[dataset]
    try:
        probabilities = infer(checkpoint, image_path, dataset)
    except ValueError as exc:
        return {"passed": False, "output_sha256": "", "reason": str(exc)}
    labels = probabilities.argmax(axis=0).astype(np.uint8)
    unique_labels = sorted(int(value) for value in np.unique(labels))
    foreground_fraction = float((labels != 0).mean())
    output_hash = hashlib.sha256(labels.tobytes()).hexdigest()
    passed = bool(len(unique_labels) >= 2 and 0.01 < foreground_fraction < 0.99)
    return {
        "passed": passed,
        "output_sha256": output_hash if passed else "",
        "dataset": dataset,
        "num_classes": num_classes,
        "logits_shape": [1, num_classes, input_size, input_size],
        "label_map_shape": list(labels.shape),
        "unique_labels": unique_labels,
        "foreground_fraction": round(foreground_fraction, 6),
        "torch": torch.__version__,
        "device": torch.cuda.get_device_name(0),
        "source_revision": REVISION,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--dataset", choices=sorted(SETTINGS), required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.checkpoint, args.image, args.dataset), sort_keys=True))


if __name__ == "__main__":
    main()
