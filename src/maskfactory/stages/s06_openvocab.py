"""S06 typed GroundingDINO proposal boxes with a hard no-mask authority boundary."""

from __future__ import annotations

import json
import math
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image


class OpenVocabError(ValueError):
    """GroundingDINO proposal output violates the S06 contract."""


CHECKPOINT_SHA256 = "3b3ca2563c77c69f651d7bd133e97139c186df06231157a64c507099c52bc799"
SOURCE_REVISION = "856dde20aee659246248e20734ef9ba5214f5e44"
REQUIRED_PROMPTS = (
    "hair",
    "bra",
    "underwear",
    "shoe",
    "sock",
    "glove",
    "necklace",
    "handheld object",
    "chair",
    "bed",
    "surface",
)


@dataclass(frozen=True)
class BoxProposal:
    prompt: str
    bbox_xyxy: tuple[float, float, float, float]
    box_score: float
    text_score: float
    authority: str = "proposal_only"


def infer_gdino_proposals(
    image_path: Path,
    *,
    checkpoint: Path,
    prompts: tuple[str, ...],
    box_threshold: float = 0.30,
    text_threshold: float = 0.25,
    wsl_distribution: str = "Ubuntu-22.04",
    python_path: str = "/home/kevin/miniforge3/envs/maskfactory/bin/python",
    timeout_sec: int = 900,
) -> list[BoxProposal]:
    """Run all configured text prompts through one pinned GroundingDINO load."""
    if not Path(image_path).is_file():
        raise OpenVocabError(f"GroundingDINO input image missing: {image_path}")
    if not Path(checkpoint).is_file():
        raise OpenVocabError(f"GroundingDINO checkpoint missing: {checkpoint}")
    if not all(isinstance(prompt, str) and prompt.strip() for prompt in prompts) or len(
        set(prompts)
    ) != len(prompts):
        raise OpenVocabError("GroundingDINO prompts must be unique non-empty strings")
    if not 0 <= box_threshold <= 1 or not 0 <= text_threshold <= 1:
        raise OpenVocabError("GroundingDINO thresholds must be in 0..1")
    try:
        with Image.open(image_path) as opened:
            image_size = opened.size
    except OSError as exc:
        raise OpenVocabError(f"GroundingDINO input image invalid: {exc}") from exc
    root = Path(__file__).resolve().parents[3]
    command = [
        "wsl",
        "-d",
        wsl_distribution,
        "--",
        python_path,
        _wsl_path(root / "tools" / "run_groundingdino_wsl.py"),
        "--checkpoint",
        _wsl_path(checkpoint),
        "--image",
        _wsl_path(image_path),
        "--prompts-json",
        json.dumps(prompts),
        "--box-threshold",
        str(box_threshold),
        "--text-threshold",
        str(text_threshold),
    ]
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OpenVocabError(f"GroundingDINO WSL launch failed: {exc}") from exc
    if process.returncode:
        detail = process.stderr.strip()[-2000:] or process.stdout.strip()[-2000:]
        raise OpenVocabError(f"GroundingDINO inference failed: {detail}")
    try:
        document = json.loads(process.stdout.strip().splitlines()[-1])
        if (
            document.get("authority") != "proposal_boxes_only"
            or document.get("may_write_final_masks") is not False
        ):
            raise OpenVocabError("GroundingDINO runner violated proposal-only authority")
        expected = {
            "protocol_version": 1,
            "checkpoint_sha256": CHECKPOINT_SHA256,
            "source_revision": SOURCE_REVISION,
            "device_type": "cpu",
            "model_load_count": 1,
            "prompts": list(prompts),
            "box_threshold": box_threshold,
            "text_threshold": text_threshold,
            "image_size": list(image_size),
        }
        mismatches = {
            key: (document.get(key), value)
            for key, value in expected.items()
            if document.get(key) != value
        }
        if mismatches:
            raise OpenVocabError(f"GroundingDINO metadata violates governed contract: {mismatches}")
        if not isinstance(document.get("device"), str) or not document["device"].strip():
            raise OpenVocabError("GroundingDINO metadata requires runtime device identity")
        proposals = [
            BoxProposal(
                item["prompt"],
                tuple(float(value) for value in item["bbox_xyxy"]),
                float(item["box_score"]),
                float(item["text_score"]),
                item["authority"],
            )
            for item in document["proposals"]
        ]
    except (KeyError, TypeError, ValueError, IndexError, json.JSONDecodeError) as exc:
        raise OpenVocabError(f"GroundingDINO output invalid: {exc}") from exc
    width, height = image_size
    for proposal in proposals:
        if len(proposal.bbox_xyxy) != 4:
            raise OpenVocabError("GroundingDINO proposal bbox must have four coordinates")
        left, top, right, bottom = proposal.bbox_xyxy
        if (
            proposal.prompt not in prompts
            or proposal.authority != "proposal_only"
            or not all(math.isfinite(value) for value in proposal.bbox_xyxy)
            or not (0 <= left < right <= width and 0 <= top < bottom <= height)
            or not box_threshold <= proposal.box_score <= 1
            or not text_threshold <= proposal.text_score <= 1
        ):
            raise OpenVocabError("GroundingDINO proposal violates prompt/box/score authority")
    return proposals


def run_s06_production(
    image_path: Path,
    output_dir: Path,
    *,
    checkpoint: Path,
    prompts: tuple[str, ...],
    box_threshold: float = 0.30,
    text_threshold: float = 0.25,
) -> Path:
    """Infer then persist proposal boxes through the only typed S06 output API."""
    if prompts != REQUIRED_PROMPTS:
        raise OpenVocabError("production GroundingDINO prompt vocabulary drifted from S06 spec")
    proposals = infer_gdino_proposals(
        image_path,
        checkpoint=checkpoint,
        prompts=prompts,
        box_threshold=box_threshold,
        text_threshold=text_threshold,
    )
    return write_gdino_proposals(
        proposals,
        output_dir,
        allowed_prompts=set(prompts),
        box_threshold=box_threshold,
        text_threshold=text_threshold,
    )


def write_gdino_proposals(
    proposals: list[BoxProposal],
    output_dir: Path,
    *,
    allowed_prompts: set[str],
    box_threshold: float = 0.30,
    text_threshold: float = 0.25,
) -> Path:
    """Validate and serialize boxes only; this API has no pixel-mask output type."""
    if not 0 <= box_threshold <= 1 or not 0 <= text_threshold <= 1:
        raise OpenVocabError("GroundingDINO thresholds must be in 0..1")
    accepted = []
    for proposal in proposals:
        if proposal.prompt not in allowed_prompts:
            raise OpenVocabError(f"unconfigured GroundingDINO prompt: {proposal.prompt}")
        left, top, right, bottom = proposal.bbox_xyxy
        if not all(math.isfinite(value) for value in proposal.bbox_xyxy):
            raise OpenVocabError("proposal bbox must be finite")
        if right <= left or bottom <= top:
            raise OpenVocabError("proposal bbox must have positive area")
        if not 0 <= proposal.box_score <= 1 or not 0 <= proposal.text_score <= 1:
            raise OpenVocabError("proposal scores must be in 0..1")
        if proposal.authority != "proposal_only":
            raise OpenVocabError("GroundingDINO authority must remain proposal_only")
        if proposal.box_score >= box_threshold and proposal.text_score >= text_threshold:
            accepted.append(proposal)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "gdino_boxes.json"
    document = {
        "schema_version": "1.0.0",
        "authority": "proposal_boxes_only",
        "may_write_final_masks": False,
        "allowed_consumers": ["sam2_prompting", "fusion_evidence"],
        "box_threshold": box_threshold,
        "text_threshold": text_threshold,
        "proposals": [asdict(proposal) for proposal in accepted],
    }
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _wsl_path(path: Path) -> str:
    resolved = Path(path).resolve()
    drive = resolved.drive.rstrip(":").lower()
    if not drive:
        raise OpenVocabError(f"expected Windows drive path: {resolved}")
    return f"/mnt/{drive}{resolved.as_posix().split(':', 1)[1]}"
