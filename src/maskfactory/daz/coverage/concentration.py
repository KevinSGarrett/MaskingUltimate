"""History-bound dominance, cooldown, and near-duplicate concentration gate."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

import yaml

from ...validation import require_valid_document
from .selection import validate_candidate_selection

SHA256 = re.compile(r"^[0-9a-f]{64}$")
TOKEN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
ENTITY_TYPES = (
    "character_preset_id",
    "skin_material_asset_id",
    "hair_asset_id",
    "complete_outfit_signature",
    "garment_asset_id",
    "pose_asset_id",
    "environment_asset_id",
    "asset_product_family",
)


class ConcentrationError(ValueError):
    """Concentration policy, history, report, or publication is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_concentration_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_concentration_policy(document)
    return document


def validate_concentration_policy(policy: Mapping[str, Any]) -> None:
    if not isinstance(policy, Mapping) or set(policy) != {
        "schema_version",
        "policy_version",
        "dominance_caps",
        "dominance_growth_floor_count",
        "base_product_exemption_requires_explicit_id",
        "cooldown_windows",
        "near_duplicate",
        "exact_candidate_repeat_allowed",
        "selection",
        "authority",
        "publication",
    }:
        raise ConcentrationError("concentration_policy_fields_invalid", str(policy))
    if policy["schema_version"] != "1.0.0" or policy["policy_version"] != "1.0.0":
        raise ConcentrationError("concentration_policy_identity_invalid", str(policy))
    if (
        policy["dominance_caps"]
        != dict(zip(ENTITY_TYPES, (0.03, 0.03, 0.02, 0.02, 0.05, 0.005, 0.03, 0.10), strict=True))
        or policy["dominance_growth_floor_count"] != 1
        or policy["base_product_exemption_requires_explicit_id"] is not True
    ):
        raise ConcentrationError("concentration_policy_caps_invalid", str(policy))
    if policy["cooldown_windows"] != {
        "scene_family_id": 32,
        "character_preset_id": 4,
        "hair_asset_id": 4,
        "pose_asset_id": 8,
        "environment_asset_id": 4,
    }:
        raise ConcentrationError("concentration_policy_cooldowns_invalid", str(policy))
    if (
        policy["near_duplicate"]
        != {
            "signature": "scene_family_id",
            "rolling_window": 128,
            "maximum_members": 1,
            "variant_axes_excluded": [
                "lighting_profile",
                "exposure_profile",
                "resolution_profile",
                "depth_of_field_mode",
                "motion_blur_mode",
                "render_profile",
                "degradation_lane",
            ],
            "continuous_axes_included": ["body_morph_value"],
        }
        or policy["exact_candidate_repeat_allowed"] is not False
    ):
        raise ConcentrationError("concentration_policy_duplicate_invalid", str(policy))
    if policy["selection"] != {
        "order": "original_feasible_rank",
        "first_passing_candidate_admitted": True,
        "all_limited_is_honest_unsatisfied": True,
    }:
        raise ConcentrationError("concentration_policy_selection_invalid", str(policy))
    if policy["authority"] != {
        "stage": "technical_concentration_gate",
        "admission_is_recipe": False,
        "admission_is_render_authority": False,
        "admission_creates_gold": False,
    } or policy["publication"] != {"immutable": True, "atomic": True}:
        raise ConcentrationError("concentration_policy_authority_invalid", str(policy))


def build_concentration_report(
    *,
    selection_report: Mapping[str, Any],
    candidate_batch: Mapping[str, Any],
    vocabulary_report: Mapping[str, Any],
    history_snapshot: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    _validate_inputs(selection_report, candidate_batch, vocabulary_report, history_snapshot, policy)
    content = _compute_content(selection_report, candidate_batch, history_snapshot, policy)
    digest = _sha(content)
    report = {
        "schema_version": "1.0.0",
        "report_id": f"dcon_{digest[:24]}",
        "report_sha256": digest,
        **content,
    }
    require_valid_document(report, "daz_concentration_report")
    return report


def validate_concentration_report(
    report: Mapping[str, Any],
    *,
    selection_report: Mapping[str, Any],
    candidate_batch: Mapping[str, Any],
    vocabulary_report: Mapping[str, Any],
    history_snapshot: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> None:
    require_valid_document(report, "daz_concentration_report")
    _validate_inputs(selection_report, candidate_batch, vocabulary_report, history_snapshot, policy)
    expected = _compute_content(selection_report, candidate_batch, history_snapshot, policy)
    digest = _sha(expected)
    if report != {
        "schema_version": "1.0.0",
        "report_id": f"dcon_{digest[:24]}",
        "report_sha256": digest,
        **expected,
    }:
        raise ConcentrationError(
            "concentration_report_semantics_invalid", str(report.get("report_id"))
        )


def publish_concentration_report(
    report: Mapping[str, Any],
    output_root: Path,
    *,
    selection_report: Mapping[str, Any],
    candidate_batch: Mapping[str, Any],
    vocabulary_report: Mapping[str, Any],
    history_snapshot: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> tuple[Path, bool]:
    validate_concentration_report(
        report,
        selection_report=selection_report,
        candidate_batch=candidate_batch,
        vocabulary_report=vocabulary_report,
        history_snapshot=history_snapshot,
        policy=policy,
    )
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{report['report_id']}.json"
    payload = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise ConcentrationError("concentration_publication_conflict", str(target))
        return target, False
    descriptor, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=root)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target, True


def derive_candidate_history_record(
    candidate: Mapping[str, Any], policy: Mapping[str, Any]
) -> dict[str, Any]:
    """Return the exact pre-render family and contribution identity for one candidate."""
    discrete = {row["axis_id"]: row["value"] for row in candidate["discrete"]}
    registry = {row["axis_id"]: row["value"] for row in candidate["registry"]}
    continuous = {row["axis_id"]: row["value"] for row in candidate["continuous"]}
    excluded = set(policy["near_duplicate"]["variant_axes_excluded"])
    family_basis = {
        "discrete": {axis: value for axis, value in discrete.items() if axis not in excluded},
        "registry": registry,
        "continuous": {
            axis: continuous[axis] for axis in policy["near_duplicate"]["continuous_axes_included"]
        },
    }
    family_digest = _sha(family_basis)
    outfit_digest = _sha({"garment_asset_ids": [registry["garment_asset_id"]]})
    contributions = {
        "character_preset_id": registry["character_preset_id"],
        "skin_material_asset_id": registry["skin_material_asset_id"],
        "hair_asset_id": registry["hair_asset_id"],
        "complete_outfit_signature": f"outfit_{outfit_digest[:24]}",
        "garment_asset_id": registry["garment_asset_id"],
        "pose_asset_id": registry["pose_asset_id"],
        "environment_asset_id": registry["environment_asset_id"],
        "asset_product_family": registry["asset_product_family"],
    }
    return {
        "candidate_id": candidate["candidate_id"],
        "scene_family_id": f"dfam_{family_digest[:24]}",
        "contributions": contributions,
    }


def _validate_inputs(
    selection: Mapping[str, Any],
    batch: Mapping[str, Any],
    vocabulary: Mapping[str, Any],
    history: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> None:
    validate_concentration_policy(policy)
    validate_candidate_selection(selection, candidate_batch=batch, vocabulary_report=vocabulary)
    if (
        not isinstance(history, Mapping)
        or set(history) != {"snapshot_id", "snapshot_sha256", "base_product_ids", "records"}
        or not TOKEN.fullmatch(str(history.get("snapshot_id")))
        or not SHA256.fullmatch(str(history.get("snapshot_sha256")))
        or not isinstance(history.get("base_product_ids"), list)
        or len(history["base_product_ids"]) != len(set(history["base_product_ids"]))
        or any(
            not re.fullmatch(r"daz_product_[A-Za-z0-9_-]+", value)
            for value in history["base_product_ids"]
        )
        or not isinstance(history.get("records"), list)
    ):
        raise ConcentrationError("concentration_history_invalid", str(history))
    content = {
        "snapshot_id": history["snapshot_id"],
        "base_product_ids": history["base_product_ids"],
        "records": history["records"],
    }
    if history["snapshot_sha256"] != _sha(content):
        raise ConcentrationError("concentration_history_hash_invalid", history["snapshot_id"])
    seen = set()
    for record in history["records"]:
        if (
            not isinstance(record, Mapping)
            or set(record) != {"candidate_id", "scene_family_id", "contributions"}
            or not re.fullmatch(r"dc_[0-9a-f]{24}", str(record.get("candidate_id")))
            or not re.fullmatch(r"dfam_[0-9a-f]{24}", str(record.get("scene_family_id")))
            or set(record.get("contributions", {})) != set(ENTITY_TYPES)
            or record["candidate_id"] in seen
        ):
            raise ConcentrationError("concentration_history_record_invalid", str(record))
        seen.add(record["candidate_id"])


def _compute_content(
    selection: Mapping[str, Any],
    batch: Mapping[str, Any],
    history: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    candidates = {row["candidate_id"]: row for row in batch["candidates"]}
    ranked = sorted(
        (row for row in selection["rows"] if row["feasible"]), key=lambda row: row["rank"]
    )
    history_records = history["records"]
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for record in history_records:
        for entity_type, entity_id in record["contributions"].items():
            counts[entity_type][entity_id] += 1
    base_ids = set(history["base_product_ids"])
    projected_total = len(history_records) + 1
    rows = []
    admitted_id = None
    for scored in ranked:
        identity = derive_candidate_history_record(candidates[scored["candidate_id"]], policy)
        contributions = []
        dominance_failures = []
        for entity_type in ENTITY_TYPES:
            entity_id = identity["contributions"][entity_type]
            historical = counts[entity_type][entity_id]
            projected = historical + 1
            cap = policy["dominance_caps"][entity_type]
            allowed = max(
                policy["dominance_growth_floor_count"], math.floor(cap * projected_total + 1e-12)
            )
            exempt = entity_type == "asset_product_family" and entity_id in base_ids
            passes = exempt or projected <= allowed
            if not passes:
                dominance_failures.append(entity_type)
            contributions.append(
                {
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "historical_count": historical,
                    "projected_count": projected,
                    "projected_total": projected_total,
                    "projected_share": projected / projected_total,
                    "maximum_share": cap,
                    "allowed_count": allowed,
                    "base_product_exempt": exempt,
                    "passes": passes,
                }
            )
        cooldown_failures = []
        for entity_type, window in policy["cooldown_windows"].items():
            value = (
                identity["scene_family_id"]
                if entity_type == "scene_family_id"
                else identity["contributions"][entity_type]
            )
            recent = history_records[-window:]
            if any(
                (
                    record["scene_family_id"]
                    if entity_type == "scene_family_id"
                    else record["contributions"][entity_type]
                )
                == value
                for record in recent
            ):
                cooldown_failures.append(entity_type)
        exact_repeat = any(
            record["candidate_id"] == identity["candidate_id"] for record in history_records
        )
        near_recent = history_records[-policy["near_duplicate"]["rolling_window"] :]
        near_count = sum(
            record["scene_family_id"] == identity["scene_family_id"] for record in near_recent
        )
        passes = (
            not dominance_failures
            and not cooldown_failures
            and not exact_repeat
            and near_count < policy["near_duplicate"]["maximum_members"]
        )
        admitted = passes and admitted_id is None
        if admitted:
            admitted_id = identity["candidate_id"]
        rows.append(
            {
                "candidate_id": identity["candidate_id"],
                "original_rank": scored["rank"],
                "scene_family_id": identity["scene_family_id"],
                "contributions": contributions,
                "cooldown_failures": cooldown_failures,
                "dominance_failures": dominance_failures,
                "exact_repeat": exact_repeat,
                "near_duplicate_count": near_count,
                "near_duplicate_limit": policy["near_duplicate"]["maximum_members"],
                "passes": passes,
                "admitted": admitted,
            }
        )
    reason_counts = Counter()
    for row in rows:
        reason_counts.update(f"cooldown:{value}" for value in row["cooldown_failures"])
        reason_counts.update(f"dominance:{value}" for value in row["dominance_failures"])
        if row["exact_repeat"]:
            reason_counts["exact_candidate_repeat"] += 1
        if row["near_duplicate_count"] >= row["near_duplicate_limit"]:
            reason_counts["near_duplicate_limit"] += 1
    max_share = {
        entity_type: max(
            (
                entry["projected_share"]
                for row in rows
                for entry in row["contributions"]
                if entry["entity_type"] == entity_type
            ),
            default=0.0,
        )
        for entity_type in ENTITY_TYPES
    }
    all_families = [record["scene_family_id"] for record in history_records]
    if admitted_id is not None:
        all_families.append(next(row["scene_family_id"] for row in rows if row["admitted"]))
    family_counts = Counter(all_families)
    duplicate_members = sum(count for count in family_counts.values() if count > 1)
    near_rate = duplicate_members / len(all_families) if all_families else None
    summary = {
        "feasible_candidate_count": len(ranked),
        "evaluated_count": len(rows),
        "passing_count": sum(row["passes"] for row in rows),
        "limited_count": sum(not row["passes"] for row in rows),
        "admitted_count": int(admitted_id is not None),
        "limit_reason_counts": dict(sorted(reason_counts.items())),
        "maximum_projected_share_by_entity_type": max_share,
        "near_duplicate_rate_after_admission": near_rate,
    }
    return {
        "policy_version": policy["policy_version"],
        "policy_sha256": _sha(policy),
        "selection": {
            "selection_id": selection["selection_id"],
            "selection_sha256": selection["selection_sha256"],
        },
        "candidate_batch": {"batch_id": batch["batch_id"], "batch_sha256": batch["batch_sha256"]},
        "history_snapshot": {
            "snapshot_id": history["snapshot_id"],
            "snapshot_sha256": history["snapshot_sha256"],
            "accepted_record_count": len(history_records),
            "base_product_ids": history["base_product_ids"],
        },
        "rows": rows,
        "admitted_candidate_id": admitted_id,
        "satisfied": admitted_id is not None,
        "summary": summary,
        "authority": dict(policy["authority"]),
        "publication": dict(policy["publication"]),
    }


def _sha(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()
