"""Frozen two-stage provider benchmark matrix identity contract."""

from __future__ import annotations

import hashlib
import itertools
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..validation import ArtifactValidationError, require_valid_document

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_POLICY_PATH = (
    ROOT / "qa" / "governance" / "benchmark_matrices" / "provider_benchmark_matrix_v1.json"
)
POLICY_SHA256 = "95b6cfa6d879acc89a42709edd6ed139ec885bc20426b6695df8cdc0c672773e"
SCREENING_ROUTES = (
    ("sam2_1_only", "frozen_baseline_prompts", "sam2_1"),
    ("sam3_1_only", "sam3_1_direct", "none"),
    ("sam3_1_discovery_sam2_1_refinement", "sam3_1_discovery", "sam2_1"),
    ("sam3_1_discovery_sam3_1_refinement", "sam3_1_discovery", "sam3_1"),
    ("rfdetr_detection_sam2_1_refinement", "rfdetr_detection", "sam2_1"),
    ("rfdetr_detection_sam3_1_refinement", "rfdetr_detection", "sam3_1"),
)
ROUTE_PROVIDER_KEYS = {
    "sam2_1_only": ("sam2_1",),
    "sam3_1_only": ("sam3_1",),
    "sam3_1_discovery_sam2_1_refinement": ("sam2_1", "sam3_1"),
    "sam3_1_discovery_sam3_1_refinement": ("sam3_1",),
    "rfdetr_detection_sam2_1_refinement": ("rfdetr", "sam2_1"),
    "rfdetr_detection_sam3_1_refinement": ("rfdetr", "sam3_1"),
}
GEOMETRY = ("densepose_only", "densepose_plus_sam3d_body")
SILHOUETTE = (
    "birefnet_general",
    "birefnet_dynamic",
    "birefnet_hr",
    "birefnet_hr_matting",
    "vitmatte",
)
POSE = ("dwpose_133", "rtmw_x_384", "rtmo_l_640")
HAND_VOTE = (False, True)
PROVIDER_ARTIFACT_KEYS = (
    "birefnet_dynamic",
    "birefnet_general",
    "birefnet_hr",
    "birefnet_hr_matting",
    "densepose",
    "dwpose_133",
    "mediapipe_hands",
    "rfdetr",
    "rtmo_l_640",
    "rtmw_x_384",
    "sam2_1",
    "sam3_1",
    "sam3d_body",
    "vitmatte",
)
MEASUREMENT_SOURCE_FILES = (
    "src/maskfactory/providers/benchmark_policy.py",
    "src/maskfactory/providers/geometry_benchmark.py",
    "src/maskfactory/providers/mediapipe_ablation.py",
    "src/maskfactory/providers/pose_benchmark.py",
    "src/maskfactory/providers/provider_matrix_metrics.py",
    "src/maskfactory/providers/silhouette_benchmark.py",
    "src/maskfactory/qa/metrics.py",
)
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class ProviderMatrixError(ValueError):
    """The provider matrix policy or immutable manifest is invalid."""


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_PATTERN.fullmatch(value) is not None


def _timestamp(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderMatrixError(f"{field} is not an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ProviderMatrixError(f"{field} lacks a timezone")
    return parsed.astimezone(UTC)


def measurement_bundle_sha256(policy: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {relative: policy["source_hashes"][relative] for relative in MEASUREMENT_SOURCE_FILES}
    )


def validate_policy(
    document: Mapping[str, Any],
    *,
    root: Path = ROOT,
    expected_sha256: str | None = POLICY_SHA256,
) -> None:
    try:
        require_valid_document(document, "provider_benchmark_matrix_policy")
    except ArtifactValidationError as exc:
        raise ProviderMatrixError(str(exc)) from exc
    payload = {key: value for key, value in document.items() if key != "sha256"}
    if document["sha256"] != canonical_sha256(payload):
        raise ProviderMatrixError("provider matrix policy hash mismatch")
    if expected_sha256 is not None and document["sha256"] != expected_sha256:
        raise ProviderMatrixError("provider matrix policy differs from locked hash")
    routes = tuple(
        (row["route_id"], row["candidate_source"], row["refinement"])
        for row in document["screening_routes"]
    )
    if routes != SCREENING_ROUTES:
        raise ProviderMatrixError("provider matrix screening routes drifted")
    dimensions = document["enrichment_dimensions"]
    if (
        tuple(dimensions["geometry"]) != GEOMETRY
        or tuple(dimensions["silhouette"]) != SILHOUETTE
        or tuple(dimensions["pose"]) != POSE
        or tuple(dimensions["mediapipe_hand_vote"]) != HAND_VOTE
    ):
        raise ProviderMatrixError("provider matrix enrichment grid drifted")
    if tuple(document["required_provider_artifact_keys"]) != PROVIDER_ARTIFACT_KEYS:
        raise ProviderMatrixError("provider matrix artifact vocabulary drifted")
    if document["measurement_contract"] != {
        "required_label_count": 65,
        "required_cell_artifact_keys": [
            "determinism_outputs",
            "metric_observations",
            "prediction_manifest",
            "runtime_log",
        ],
        "required_deterministic_repeats": 2,
        "explicit_raw_count_denominators_required": True,
        "finite_nonnegative_runtime_required": True,
    }:
        raise ProviderMatrixError("provider matrix measurement contract drifted")
    finalist = document["finalist_contract"]
    if finalist != {
        "minimum_count": 1,
        "maximum_count": 6,
        "selection_requires_hash_sealed_screening_result": True,
        "every_selected_route_must_expand_full_grid": True,
    }:
        raise ProviderMatrixError("provider matrix finalist contract drifted")
    if document["truth_contract"] != {
        "tier": "human_anchor_gold",
        "partition": "holdout",
        "image_disjoint": True,
    }:
        raise ProviderMatrixError("provider matrix truth contract drifted")
    for relative, expected in document["source_hashes"].items():
        source = Path(root) / relative
        if not source.is_file() or _file_sha256(source) != expected:
            raise ProviderMatrixError(f"provider matrix source hash drift: {relative}")


def load_policy(path: Path = DEFAULT_POLICY_PATH, *, root: Path = ROOT) -> dict[str, Any]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ProviderMatrixError("provider matrix policy is not an object")
    validate_policy(document, root=root)
    return document


def _screening_provider_keys(route_id: str) -> list[str]:
    return sorted(ROUTE_PROVIDER_KEYS[route_id])


def _enrichment_provider_keys(
    route_id: str,
    geometry: str,
    silhouette: str,
    pose: str,
    hand_vote: bool,
) -> list[str]:
    keys = set(ROUTE_PROVIDER_KEYS[route_id])
    keys.add("densepose")
    if geometry == "densepose_plus_sam3d_body":
        keys.add("sam3d_body")
    keys.add(silhouette)
    keys.add(pose)
    if hand_vote:
        keys.add("mediapipe_hands")
    return sorted(keys)


def expected_screening_cells(shared_identity_sha256: str) -> list[dict[str, Any]]:
    return [
        {
            "cell_id": route_id,
            "route_id": route_id,
            "candidate_source": candidate_source,
            "refinement": refinement,
            "shared_identity_sha256": shared_identity_sha256,
            "provider_artifact_keys": _screening_provider_keys(route_id),
        }
        for route_id, candidate_source, refinement in SCREENING_ROUTES
    ]


def expected_enrichment_cells(
    selected_routes: Sequence[str], shared_identity_sha256: str
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for route_id in selected_routes:
        for geometry, silhouette, pose, hand_vote in itertools.product(
            GEOMETRY, SILHOUETTE, POSE, HAND_VOTE
        ):
            rows.append(
                {
                    "cell_id": (
                        f"{route_id}__{geometry}__{silhouette}__{pose}__"
                        f"mediapipe_{int(hand_vote)}"
                    ),
                    "base_route_id": route_id,
                    "geometry": geometry,
                    "silhouette": silhouette,
                    "pose": pose,
                    "mediapipe_hand_vote": hand_vote,
                    "shared_identity_sha256": shared_identity_sha256,
                    "provider_artifact_keys": _enrichment_provider_keys(
                        route_id, geometry, silhouette, pose, hand_vote
                    ),
                }
            )
    return rows


def validate_manifest(
    document: Mapping[str, Any],
    *,
    policy: Mapping[str, Any] | None = None,
    root: Path = ROOT,
) -> None:
    policy_document = dict(policy) if policy is not None else load_policy(root=root)
    validate_policy(policy_document, root=root)
    try:
        require_valid_document(document, "provider_benchmark_matrix_manifest")
    except ArtifactValidationError as exc:
        raise ProviderMatrixError(str(exc)) from exc
    payload = {key: value for key, value in document.items() if key != "sha256"}
    if document["sha256"] != canonical_sha256(payload):
        raise ProviderMatrixError("provider matrix manifest hash mismatch")
    if document["policy_sha256"] != policy_document["sha256"]:
        raise ProviderMatrixError("provider matrix manifest policy hash mismatch")
    if document["matrix_id"] != policy_document["policy_id"]:
        raise ProviderMatrixError("provider matrix identity mismatch")
    if _timestamp(document["opened_at"], "opened_at") <= _timestamp(
        policy_document["frozen_at"], "policy.frozen_at"
    ):
        raise ProviderMatrixError("provider matrix opened before policy freeze")

    shared = document["shared_identity"]
    truth = policy_document["truth_contract"]
    exact = {
        "truth_tier": truth["tier"],
        "truth_partition": truth["partition"],
        "image_disjoint": truth["image_disjoint"],
        "qa_sha256": policy_document["source_hashes"]["configs/qa.yaml"],
        "pipeline_sha256": policy_document["source_hashes"]["configs/pipeline.yaml"],
        "ontology_sha256": policy_document["source_hashes"]["configs/ontology_v2.yaml"],
        "measurement_bundle_sha256": measurement_bundle_sha256(policy_document),
    }
    for field, expected in exact.items():
        if shared[field] != expected:
            raise ProviderMatrixError(f"provider matrix shared {field} mismatch")
    identity_hashes = (
        shared["evaluation_set_sha256"],
        shared["prompt_set_sha256"],
        shared["part_set_sha256"],
        shared["hardware_profile_sha256"],
    )
    if len(set(identity_hashes)) != len(identity_hashes):
        raise ProviderMatrixError("provider matrix shared identities are conflated")
    artifacts = shared["provider_artifact_sha256"]
    if tuple(sorted(artifacts)) != PROVIDER_ARTIFACT_KEYS or any(
        not _is_sha256(value) for value in artifacts.values()
    ):
        raise ProviderMatrixError("provider matrix artifact identities are incomplete")
    shared_sha256 = canonical_sha256(shared)
    if document["screening_cells"] != expected_screening_cells(shared_sha256):
        raise ProviderMatrixError("provider matrix screening cells are incomplete or drifted")

    selection = document["finalist_selection"]
    selected = selection["selected_routes"]
    route_ids = [row[0] for row in SCREENING_ROUTES]
    contract = policy_document["finalist_contract"]
    if (
        len(selected) < contract["minimum_count"]
        or len(selected) > contract["maximum_count"]
        or len(selected) != len(set(selected))
        or any(route not in route_ids for route in selected)
        or not _is_sha256(selection["screening_result_sha256"])
    ):
        raise ProviderMatrixError("provider matrix finalist selection is invalid")
    expected = expected_enrichment_cells(selected, shared_sha256)
    if document["enrichment_cells"] != expected:
        raise ProviderMatrixError("provider matrix enrichment grid is incomplete or drifted")


def seal_manifest(
    draft: Mapping[str, Any],
    *,
    policy: Mapping[str, Any] | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    document = dict(draft)
    if "sha256" in document:
        raise ProviderMatrixError("provider matrix draft is already sealed")
    document["sha256"] = canonical_sha256(document)
    validate_manifest(document, policy=policy, root=root)
    return document


__all__ = [
    "DEFAULT_POLICY_PATH",
    "GEOMETRY",
    "HAND_VOTE",
    "POLICY_SHA256",
    "POSE",
    "PROVIDER_ARTIFACT_KEYS",
    "ProviderMatrixError",
    "SCREENING_ROUTES",
    "SILHOUETTE",
    "canonical_sha256",
    "expected_enrichment_cells",
    "expected_screening_cells",
    "load_policy",
    "measurement_bundle_sha256",
    "seal_manifest",
    "validate_manifest",
    "validate_policy",
]
