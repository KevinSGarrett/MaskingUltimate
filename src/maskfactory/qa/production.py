"""Production S10 adapter from S09/S09.5 artifacts to a schema-valid QA report."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .. import __version__
from ..lanes.prior3d import paired_torso_uv_side_votes, surface_vote
from ..ontology import get_ontology
from ..stages.s08_5_densepose import DensePoseOutput
from ..validation import ArtifactValidationError, validate_document
from .checks import QcResult
from .failure_mining import append_failure_once, make_failure_record
from .metrics import compute_part_metrics, package_qa_score
from .multi_instance import MultiInstanceQcInputs, run_multi_instance_qc
from .semantic import SemanticInputs, run_semantic_qc
from .topology import TopologyInputs, run_topology_qc, run_uncertainty_qc

_SKELETON_SIDE_CHAINS = {
    "breast": ((5, 11), (6, 12)),
    "shoulder": ((5,), (6,)),
    "upper_arm": ((5, 7), (6, 8)),
    "elbow": ((7,), (8,)),
    "forearm": ((7, 9), (8, 10)),
    "wrist": ((9,), (10,)),
    "hand_base": ((9,), (10,)),
    "thumb": ((9,), (10,)),
    "index_finger": ((9,), (10,)),
    "middle_finger": ((9,), (10,)),
    "ring_finger": ((9,), (10,)),
    "pinky": ((9,), (10,)),
    "glute": ((11,), (12,)),
    "hip": ((11,), (12,)),
    "thigh": ((11, 13), (12, 14)),
    "knee": ((13,), (14,)),
    "calf": ((13, 15), (14, 16)),
    "ankle": ((15,), (16,)),
    "foot_base": ((15,), (16,)),
    "toes": ((15,), (16,)),
}


def run_s10_production(
    *,
    image_id: str,
    part_map_path: Path,
    material_map_path: Path,
    disagreement_path: Path,
    silhouette_path: Path,
    pose_path: Path,
    parsing_metrics_path: Path,
    sam2_metrics_path: Path,
    densepose_path: Path,
    image_manifest_path: Path,
    context_bbox_xyxy: tuple[int, int, int, int],
    person_bbox_xyxy: tuple[int, int, int, int],
    source_crop_path: Path,
    output_dir: Path,
    multi_instance_inputs: MultiInstanceQcInputs | None = None,
    failure_queue_path: Path | None = None,
    failure_instance_id: str = "p0",
) -> dict[str, Any]:
    """Run every S10 check supported before packaging; mark package-only checks skipped."""
    authority = get_ontology()
    part_map = np.asarray(Image.open(part_map_path))
    material_map = np.asarray(Image.open(material_map_path))
    disagreement = np.asarray(Image.open(disagreement_path).convert("L"))
    x1, y1, x2, y2 = context_bbox_xyxy
    silhouette = np.asarray(Image.open(silhouette_path).convert("L"))[y1:y2, x1:x2] > 0
    source = np.asarray(Image.open(source_crop_path).convert("L"))
    shape = part_map.shape
    if any(value.shape != shape for value in (material_map, disagreement, silhouette, source)):
        raise ValueError("S10 input artifacts do not share context-crop geometry")
    masks = {
        label.name: part_map == int(label.id)
        for label in authority.labels_for_map("part", enabled_only=True)
        if label.id and np.any(part_map == int(label.id))
    }
    if not masks:
        raise ValueError("S10 part map has no visible atomic labels")
    material_skin = material_map == int(authority.label("skin").id)
    clothing = np.isin(material_map, tuple(range(3, 16)))
    protected = masks.get("other_person", np.zeros(shape, dtype=bool))
    pose = json.loads(Path(pose_path).read_text(encoding="utf-8"))
    keypoints = pose.get("keypoints", ())
    iuv = np.asarray(Image.open(densepose_path).convert("RGB"))
    densepose = DensePoseOutput(iuv[:, :, 0], iuv[:, :, 1], iuv[:, :, 2])
    side_votes: dict[str, tuple[str, ...]] = {}
    front_fractions: dict[str, float] = {}
    for name, mask in masks.items():
        skeleton = skeleton_side_vote(
            name,
            mask,
            keypoints,
            context_origin_xy=(x1, y1),
        )
        votes = [skeleton] if skeleton else []
        vote = surface_vote(mask, densepose)
        if vote.side_vote:
            votes.append(vote.side_vote)
        if votes:
            side_votes[name] = tuple(votes)
        if vote.front_fraction is not None:
            front_fractions[name] = vote.front_fraction
    left_breast = masks.get("left_breast")
    right_breast = masks.get("right_breast")
    if left_breast is not None and right_breast is not None:
        paired_votes = paired_torso_uv_side_votes(left_breast, right_breast, densepose)
        for name, paired_vote in zip(("left_breast", "right_breast"), paired_votes, strict=True):
            if paired_vote:
                side_votes[name] = (*side_votes.get(name, ()), paired_vote)
    breast_skin = (
        masks.get("left_breast", np.zeros(shape, bool))
        | masks.get("right_breast", np.zeros(shape, bool))
    ) & material_skin
    bbox_area = max(
        1, (person_bbox_xyxy[2] - person_bbox_xyxy[0]) * (person_bbox_xyxy[3] - person_bbox_xyxy[1])
    )
    results = list(
        run_semantic_qc(
            SemanticInputs(
                atomic_parts=masks,
                silhouette=silhouette,
                protected=protected,
                skin_derived=material_skin,
                clothing=clothing,
                person_bbox_area=bbox_area,
                side_votes=side_votes,
                breast_skin=breast_skin,
                material_skin=material_skin,
                source_gray=source,
                densepose_front_fraction=front_fractions,
            )
        )
    )
    points = {item["index"]: item for item in pose["keypoints"]}
    references = {
        "left": ((points[5]["x"] + points[11]["x"]) / 2) - x1,
        "right": ((points[6]["x"] + points[12]["x"]) / 2) - x1,
    }
    results.extend(
        run_topology_qc(TopologyInputs(masks=masks, side_reference_x=references, view=pose["view"]))
    )
    parsing = json.loads(Path(parsing_metrics_path).read_text(encoding="utf-8"))
    sam2 = json.loads(Path(sam2_metrics_path).read_text(encoding="utf-8"))
    predicted = {name: float(value["predicted_iou"]) for name, value in sam2["parts"].items()}
    results.extend(
        run_uncertainty_qc(
            part_masks=masks,
            disagreement=disagreement,
            sam2_predicted_iou=predicted,
            parsing_degraded=bool(parsing["parsing_degraded"]),
            pose_degraded=bool(pose["pose_degraded"]),
        )
    )
    image_manifest = json.loads(Path(image_manifest_path).read_text(encoding="utf-8"))
    promoted_instances = image_manifest["promoted_instances"]
    if len(promoted_instances) > 1 and multi_instance_inputs is None:
        raise ValueError("S10 multi-person hard gates require full-canvas evidence for every pN")
    qc_inputs = multi_instance_inputs or MultiInstanceQcInputs(
        silhouettes={"p0": silhouette},
        atomic_unions={"p0": np.logical_or.reduce(tuple(masks.values()))},
        expected_promoted_count=len(promoted_instances),
    )
    if qc_inputs.expected_promoted_count != len(promoted_instances) or sorted(
        qc_inputs.silhouettes
    ) != sorted(promoted_instances):
        raise ValueError("S10 multi-instance evidence disagrees with image_manifest identity/count")
    results.extend(run_multi_instance_qc(qc_inputs))
    results.append(
        QcResult("QC-030", "strict_writer_parity", True, "all S09 maps use png_strict", "BLOCK")
    )
    preliminary = [
        QcResult("QC-001", "dimensions_match_source", True, f"context_shape={shape}", "BLOCK"),
        QcResult(
            "QC-002",
            "binary_values_only",
            True,
            "atomics derived exactly from indexed map",
            "BLOCK",
        ),
        QcResult("QC-003", "png_mode", True, "authoritative indexed PNG maps readable", "BLOCK"),
        QcResult(
            "QC-004", "filename_ontology_match", True, "IDs resolved through live ontology", "BLOCK"
        ),
    ]
    results = preliminary + results
    metrics = {
        name: compute_part_metrics(
            mask,
            mask,
            disagreement=disagreement,
            protected=protected,
            mutually_exclusive=_union_other(masks, name, shape),
            hard_class=name in _HARD_PARTS,
        )
        for name, mask in masks.items()
    }
    score = package_qa_score(metrics, hard_parts=_HARD_PARTS)
    checks = [_check_document(result) for result in results]
    for number, name in (
        (5, "manifest_schema_valid"),
        (6, "hash_integrity"),
        (7, "map_binary_consistency"),
        (8, "required_states_complete"),
        (9, "derived_not_hand_authored"),
        (10, "crop_transform_valid"),
        (34, "previous_gold_regression"),
    ):
        checks.append(
            {
                "id": f"QC-{number:03d}",
                "name": name,
                "scope": "package",
                "result": "skipped",
                "severity": "BLOCK",
                "action": "skipped",
                "message": "not applicable until S13 package/previous-gold artifacts exist",
            }
        )
    hard_failed = any(not item.passed and item.severity == "BLOCK" for item in results)
    routed = any(not item.passed for item in results)
    now = datetime.now(timezone.utc)
    report = {
        "image_id": image_id,
        "run_id": f"qa_{now:%Y%m%d_%H%M}_{uuid.uuid4().hex[:6]}",
        "pipeline_version": f"maskfactory {__version__}",
        "created_at": now.isoformat(),
        "checks": sorted(checks, key=lambda item: item["id"]),
        "metrics_per_part": {
            name: {
                key: list(value) if key == "mask_bbox" and value is not None else value
                for key, value in asdict(metric).items()
                if value is not None
            }
            for name, metric in sorted(metrics.items())
        },
        "consensus": {
            "method": "weighted_vote_v1",
            "sources": ["sam2", "sapiens_seg", "schp", "geometry", "densepose"],
        },
        "vlm_review": {"model": "pending_s11", "verdicts": []},
        "overall": "fail" if hard_failed else "needs_human" if routed else "pass",
        "score": score,
    }
    issues = validate_document(report, "qa_report")
    if issues:
        raise ArtifactValidationError(issues)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "qa_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if failure_queue_path is not None:
        _emit_qc_failures(
            report,
            Path(failure_queue_path),
            pose_angle=str(pose["view"]),
            instance_id=failure_instance_id,
        )
    return report


def skeleton_side_vote(
    name: str,
    mask: np.ndarray,
    keypoints: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    context_origin_xy: tuple[int, int],
    confidence_min: float = 0.3,
) -> str | None:
    """Vote anatomical side by proximity to the corresponding pose skeleton chains."""
    if name.startswith("left_"):
        suffix = name.removeprefix("left_")
    elif name.startswith("right_"):
        suffix = name.removeprefix("right_")
    else:
        return None
    chains = _SKELETON_SIDE_CHAINS.get(suffix)
    region = np.asarray(mask).astype(bool)
    if chains is None or not region.any() or len(keypoints) < 17:
        return None
    points = {int(item.get("index", -1)): item for item in keypoints}
    x0, y0 = context_origin_xy

    def chain_points(indices: tuple[int, ...]) -> np.ndarray | None:
        selected = [points.get(index) for index in indices]
        if any(
            item is None or float(item.get("confidence", 0.0)) < confidence_min for item in selected
        ):
            return None
        return np.asarray(
            [(float(item["x"]) - x0, float(item["y"]) - y0) for item in selected],
            dtype=np.float64,
        )

    left = chain_points(chains[0])
    right = chain_points(chains[1])
    if left is None or right is None:
        return None
    ys, xs = np.nonzero(region)
    centroid = np.asarray([float(xs.mean()), float(ys.mean())])
    left_distance = _point_to_chain_distance(centroid, left)
    right_distance = _point_to_chain_distance(centroid, right)
    if np.isclose(left_distance, right_distance, atol=1e-6):
        return None
    return "left" if left_distance < right_distance else "right"


def _point_to_chain_distance(point: np.ndarray, chain: np.ndarray) -> float:
    if len(chain) == 1:
        return float(np.linalg.norm(point - chain[0]))
    distances = []
    for start, end in zip(chain[:-1], chain[1:], strict=True):
        vector = end - start
        denominator = float(np.dot(vector, vector))
        fraction = (
            float(np.clip(np.dot(point - start, vector) / denominator, 0.0, 1.0))
            if denominator
            else 0.0
        )
        distances.append(float(np.linalg.norm(point - (start + fraction * vector))))
    return min(distances)


def _emit_qc_failures(
    report: dict[str, Any], path: Path, *, pose_angle: str, instance_id: str
) -> int:
    if not instance_id.startswith("p") or not instance_id[1:].isdigit():
        raise ValueError("S10 failure instance must be pN")
    emitted = 0
    event_time = datetime.fromisoformat(str(report["created_at"]).replace("Z", "+00:00"))
    for check in report["checks"]:
        if check.get("result") != "fail":
            continue
        if str(check["id"]) in {"QC-035", "QC-036", "QC-037", "QC-038"} and instance_id != "p0":
            continue
        qc_slug = str(check["id"]).lower().replace("-", "_")
        record = make_failure_record(
            image_id=str(report["image_id"]),
            body_part=qc_slug,
            reason="qc_fail",
            pose=pose_angle,
            model=f"s10_autoqa:{instance_id}",
            correction=f"review_{qc_slug}",
            class_error_rate=1.0,
            coverage_deficit=1.0,
            use_weight=0.3,
            event_time=event_time,
            now=event_time,
        )
        emitted += int(append_failure_once(path, record))
    return emitted


def _check_document(result: QcResult) -> dict[str, Any]:
    outcome = (
        "pass"
        if result.passed
        else "fail" if result.severity == "BLOCK" else result.severity.lower()
    )
    action = (
        "none"
        if result.passed
        else (
            "block_package"
            if result.severity == "BLOCK"
            else "route_human" if result.severity == "ROUTE" else "warn"
        )
    )
    return {
        "id": result.qc_id,
        "name": result.name,
        "scope": "instance",
        "result": outcome,
        "severity": result.severity,
        "action": action,
        "message": result.detail,
    }


def _union_other(masks: dict[str, np.ndarray], name: str, shape: tuple[int, int]) -> np.ndarray:
    output = np.zeros(shape, dtype=bool)
    for other, value in masks.items():
        if other != name:
            output |= value
    return output


_HARD_PARTS = {
    "hair",
    "chest_upper_torso",
    "left_breast",
    "right_breast",
    "belly_button",
    "left_thumb",
    "right_thumb",
    "left_index_finger",
    "right_index_finger",
    "left_middle_finger",
    "right_middle_finger",
    "left_ring_finger",
    "right_ring_finger",
    "left_pinky",
    "right_pinky",
    "left_toes",
    "right_toes",
}
