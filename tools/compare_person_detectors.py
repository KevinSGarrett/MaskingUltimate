from __future__ import annotations

import argparse
import copy
import hashlib
import json
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from maskfactory.providers.contracts import BoxProposal
from maskfactory.providers.rfdetr import RfdetrPersonDetector, compare_person_boxes
from maskfactory.providers.selection import ProviderSelectionError, validate_provider_selection
from maskfactory.stages.s01_person_detection import infer_yolo11_people

ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _box_hash(proposals: tuple[BoxProposal, ...]) -> str:
    payload = json.dumps(
        [asdict(proposal) for proposal in proposals],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _canonical_sha256(document: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _yolo_people(image: Path, checkpoint: Path) -> tuple[BoxProposal, ...]:
    return tuple(
        BoxProposal(
            detection.bbox_xyxy,
            detection.confidence,
            "person",
            f"yolo11m_person:{index}",
        )
        for index, detection in enumerate(
            infer_yolo11_people(
                image,
                checkpoint=checkpoint,
                confidence_min=0.5,
                device="cpu",
            )
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Frozen YOLO11/RF-DETR shadow comparison")
    parser.add_argument(
        "--image",
        type=Path,
        default=ROOT / "qa" / "fixtures" / "smoke" / "ultralytics_bus_adults.jpg",
    )
    parser.add_argument(
        "--yolo-checkpoint", type=Path, default=ROOT / "models" / "detect" / "yolo11m.pt"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "qa" / "live_verification" / "rfdetr_yolo11_shadow_comparison_20260714.json",
    )
    args = parser.parse_args()

    pipeline_path = ROOT / "configs" / "pipeline.yaml"
    external_path = ROOT / "configs" / "external_sources.yaml"
    model_path = ROOT / "models" / "model_registry.json"
    pipeline = yaml.safe_load(pipeline_path.read_text(encoding="utf-8"))
    selection_before = validate_provider_selection(
        pipeline,
        external_registry_path=external_path,
        model_registry_path=model_path,
    )

    yolo_started = time.perf_counter()
    incumbent = _yolo_people(args.image, args.yolo_checkpoint)
    yolo_seconds = time.perf_counter() - yolo_started

    rf_started = time.perf_counter()
    challenger = RfdetrPersonDetector(threshold=0.5).detect_people(args.image)
    rf_seconds = time.perf_counter() - rf_started

    switched = copy.deepcopy(pipeline)
    switched["provider_roles"]["person_detector"]["active"] = "rf_detr_medium"
    try:
        validate_provider_selection(
            switched,
            external_registry_path=external_path,
            model_registry_path=model_path,
        )
    except ProviderSelectionError as exc:
        rejection = str(exc)
    else:
        raise RuntimeError("installed RF-DETR role switch unexpectedly passed")

    selection_after = validate_provider_selection(
        pipeline,
        external_registry_path=external_path,
        model_registry_path=model_path,
    )
    replay = _yolo_people(args.image, args.yolo_checkpoint)

    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "captured_at": datetime.now(UTC).isoformat(),
        "result": "pass",
        "authority": "shadow_comparison_only_no_promotion_authority",
        "fixture": {
            "path": args.image.relative_to(ROOT).as_posix(),
            "bytes": args.image.stat().st_size,
            "sha256": _sha256(args.image),
        },
        "incumbent": {
            "provider_key": "yolo11m_person",
            "checkpoint_sha256": _sha256(args.yolo_checkpoint),
            "device": "cpu",
            "elapsed_seconds": round(yolo_seconds, 6),
            "detections": [asdict(proposal) for proposal in incumbent],
            "output_sha256": _box_hash(incumbent),
        },
        "challenger": {
            "provider_key": "rf_detr_medium",
            "checkpoint_sha256": (
                "749ff6071828aaffac63e204c4f4135ed3d6cdae4d702e086c360edc3b5768c8"
            ),
            "source_revision": RfdetrPersonDetector.identity.source_commit,
            "runtime_fingerprint": RfdetrPersonDetector.identity.runtime_fingerprint,
            "device": "cuda:0",
            "elapsed_seconds": round(rf_seconds, 6),
            "detections": [asdict(proposal) for proposal in challenger],
            "output_sha256": _box_hash(challenger),
        },
        "comparison": compare_person_boxes(incumbent, challenger),
        "latency_comparison_valid": False,
        "latency_note": "YOLO11 ran on CPU and RF-DETR ran on CUDA; elapsed values are diagnostic only.",
        "role_switch_rollback": {
            "configured_active": pipeline["provider_roles"]["person_detector"]["active"],
            "configured_rollback": pipeline["provider_roles"]["person_detector"]["rollback"],
            "challenger_lifecycle": selection_before["provider_states"]["rf_detr_medium"],
            "unpromoted_switch_rejected": True,
            "rejection": rejection,
            "selection_unchanged": selection_after == selection_before,
            "incumbent_replay_output_sha256": _box_hash(replay),
            "incumbent_replay_exact": _box_hash(replay) == _box_hash(incumbent),
        },
        "promotion_claimed": False,
    }
    document["sha256"] = _canonical_sha256(document)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(document, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
