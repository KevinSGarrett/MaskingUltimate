"""Deterministic queryable DAZ asset pools over a validated compatibility graph."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from ...validation import require_valid_document
from .catalog import ASSET_ID_PATTERN, validate_asset_compatibility_graph

REQUIRED_POOL_IDS = (
    "g9_adult_base_figures",
    "g9_adult_character_presets",
    "g9_bounded_body_morphs",
    "g9_age_appearance_profiles",
    "g9_skin_materials_by_tone_band",
    "g9_hair_by_length_texture_construction",
    "g9_wardrobe_by_region_layer_fit",
    "g9_poses_by_taxonomy",
    "multi_person_pose_templates",
    "lights_by_profile",
    "environments_by_context_complexity",
    "props_by_occlusion_support_role",
)


class AssetPoolError(ValueError):
    """A pool policy, override, or membership projection is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_asset_pool_policy(path: Path, vocabularies: Mapping[str, Any]) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_asset_pool_policy(document, vocabularies)
    return document


def validate_asset_pool_policy(policy: Mapping[str, Any], vocabularies: Mapping[str, Any]) -> None:
    if policy.get("schema_version") != "1.0.0" or policy.get("pool_version") != "1.0.0":
        raise AssetPoolError("pool_policy_version_invalid", "schema/pool version must be 1.0.0")
    if (
        policy.get("requires_static_eligibility") is not True
        or policy.get("requires_runtime_qualification_for_generation") is not True
    ):
        raise AssetPoolError("pool_authority_boundary_invalid", "pool gates cannot be disabled")
    pools = policy.get("pools")
    if not isinstance(pools, list):
        raise AssetPoolError("pool_definitions_invalid", "pools must be a list")
    pool_ids = [entry.get("pool_id") for entry in pools if isinstance(entry, Mapping)]
    if tuple(pool_ids) != REQUIRED_POOL_IDS:
        raise AssetPoolError(
            "pool_ids_invalid", "pool IDs/order must match the approved twelve-pool contract"
        )
    list_fields = {
        "primary_asset_classes": "primary_asset_classes",
        "figure_generations": "figure_generations",
        "character_scopes": "character_scopes",
        "scene_categories": "scene_categories",
        "capabilities": "capabilities",
        "group_by": "facet_keys",
    }
    for entry in pools:
        if not isinstance(entry, Mapping):
            raise AssetPoolError("pool_definitions_invalid", "pool entry is not an object")
        for field, vocabulary in list_fields.items():
            values = entry.get(field)
            minimum = 0 if field in {"capabilities", "group_by"} else 1
            if (
                not isinstance(values, list)
                or len(values) < minimum
                or len(values) != len(set(values))
                or any(value not in vocabularies[vocabulary] for value in values)
            ):
                raise AssetPoolError("pool_filter_invalid", f"{entry.get('pool_id')}:{field}")
    overrides = policy.get("overrides")
    if not isinstance(overrides, list):
        raise AssetPoolError("pool_overrides_invalid", "overrides must be a list")
    seen = set()
    for override in overrides:
        if not isinstance(override, Mapping):
            raise AssetPoolError("pool_overrides_invalid", "override is not an object")
        identity = (override.get("pool_id"), override.get("asset_id"))
        if (
            identity in seen
            or identity[0] not in REQUIRED_POOL_IDS
            or not isinstance(identity[1], str)
            or not ASSET_ID_PATTERN.fullmatch(identity[1])
            or override.get("action") not in {"include", "exclude"}
            or not isinstance(override.get("reason"), str)
            or not override["reason"].strip()
        ):
            raise AssetPoolError("pool_overrides_invalid", str(identity))
        seen.add(identity)


def build_asset_pool_report(
    graph: Mapping[str, Any],
    policy: Mapping[str, Any],
    vocabularies: Mapping[str, Any],
    *,
    qualified_asset_ids: Iterable[str] = (),
    qualification_projection_sha256: str | None = None,
) -> dict[str, Any]:
    """Project static candidates and separately expose qualified generation members."""

    validate_asset_compatibility_graph(graph)
    validate_asset_pool_policy(policy, vocabularies)
    nodes = {str(node["asset_id"]): node for node in graph["nodes"]}
    qualified = set(qualified_asset_ids)
    if any(
        not isinstance(asset_id, str) or not ASSET_ID_PATTERN.fullmatch(asset_id)
        for asset_id in qualified
    ):
        raise AssetPoolError("pool_qualified_asset_id_invalid", str(sorted(qualified)))
    missing_qualified = sorted(qualified - set(nodes))
    if missing_qualified:
        raise AssetPoolError("pool_qualified_asset_missing", ",".join(missing_qualified))
    ineligible_qualified = sorted(
        asset_id for asset_id in qualified if not nodes[asset_id]["generation_pool_eligible"]
    )
    if ineligible_qualified:
        raise AssetPoolError(
            "pool_qualified_asset_statically_ineligible", ",".join(ineligible_qualified)
        )
    if qualification_projection_sha256 is None:
        if qualified:
            raise AssetPoolError(
                "pool_qualification_projection_hash_missing",
                "nonempty qualified assets require exact certificate projection lineage",
            )
        qualification_projection_sha256 = _canonical_sha({"active": [], "excluded": []})
    if (
        not isinstance(qualification_projection_sha256, str)
        or len(qualification_projection_sha256) != 64
        or any(character not in "0123456789abcdef" for character in qualification_projection_sha256)
    ):
        raise AssetPoolError(
            "pool_qualification_projection_hash_invalid",
            str(qualification_projection_sha256),
        )
    overrides: dict[tuple[str, str], Mapping[str, Any]] = {
        (str(row["pool_id"]), str(row["asset_id"])): row for row in policy["overrides"]
    }
    entries = []
    for definition in policy["pools"]:
        pool_id = str(definition["pool_id"])
        candidates = {
            asset_id
            for asset_id, node in nodes.items()
            if node["generation_pool_eligible"] and _matches_pool(node, definition)
        }
        applied_overrides = []
        for (override_pool, asset_id), override in sorted(overrides.items()):
            if override_pool != pool_id:
                continue
            if asset_id not in nodes:
                raise AssetPoolError("pool_override_asset_missing", f"{pool_id}:{asset_id}")
            if override["action"] == "include":
                if not nodes[asset_id]["generation_pool_eligible"]:
                    raise AssetPoolError(
                        "pool_override_ineligible_include", f"{pool_id}:{asset_id}"
                    )
                candidates.add(asset_id)
            else:
                candidates.discard(asset_id)
            applied_overrides.append(
                {
                    "asset_id": asset_id,
                    "action": override["action"],
                    "reason": override["reason"],
                }
            )
        candidate_ids = sorted(candidates)
        member_ids = sorted(asset_id for asset_id in candidates if asset_id in qualified)
        distributions = {}
        for facet in definition["group_by"]:
            counts = Counter(
                str(nodes[asset_id]["facets"].get(facet, "unknown")) for asset_id in candidate_ids
            )
            distributions[facet] = dict(sorted(counts.items()))
        entries.append(
            {
                "pool_id": pool_id,
                "filter": {
                    field: list(definition[field])
                    for field in (
                        "primary_asset_classes",
                        "figure_generations",
                        "character_scopes",
                        "scene_categories",
                        "capabilities",
                        "group_by",
                    )
                },
                "static_candidate_asset_ids": candidate_ids,
                "qualified_member_asset_ids": member_ids,
                "static_candidate_count": len(candidate_ids),
                "qualified_member_count": len(member_ids),
                "generation_enabled": bool(member_ids),
                "facet_distributions": distributions,
                "applied_overrides": applied_overrides,
            }
        )
    fingerprint = _canonical_sha(
        {
            "graph_id": graph["graph_id"],
            "pool_version": policy["pool_version"],
            "qualified_asset_ids": sorted(qualified),
            "qualification_projection_sha256": qualification_projection_sha256,
            "pools": entries,
        }
    )
    document = {
        "schema_version": "1.0.0",
        "report_id": f"apr_{fingerprint[:24]}",
        "report_sha256": fingerprint,
        "graph_id": graph["graph_id"],
        "graph_sha256": graph["graph_sha256"],
        "pool_version": policy["pool_version"],
        "authority": {
            "static_candidates_are_qualified": False,
            "runtime_qualification_required": True,
            "source_assets_copied": False,
        },
        "qualification_projection": {
            "source": "validated_active_smoke_certificates",
            "qualified_asset_ids": sorted(qualified),
            "certificate_projection_sha256": qualification_projection_sha256,
            "qualification_set_sha256": _canonical_sha({"qualified_asset_ids": sorted(qualified)}),
        },
        "summary": {
            "pool_count": len(entries),
            "static_candidate_memberships": sum(row["static_candidate_count"] for row in entries),
            "qualified_member_memberships": sum(row["qualified_member_count"] for row in entries),
            "generation_enabled_pool_count": sum(row["generation_enabled"] for row in entries),
            "empty_static_candidate_pool_count": sum(
                row["static_candidate_count"] == 0 for row in entries
            ),
        },
        "pools": entries,
    }
    require_valid_document(document, "daz_asset_pool_report")
    return document


def publish_asset_pool_report(report: Mapping[str, Any], output_root: Path) -> tuple[Path, bool]:
    validate_asset_pool_report(report)
    report_id = str(report["report_id"])
    payload = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    target = output_root / f"{report_id}.json"
    if target.exists():
        if target.read_bytes() != payload:
            raise AssetPoolError("pool_report_immutable_conflict", "existing bytes differ")
        return target, False
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{report_id}.", suffix=".tmp", dir=output_root
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_name, target)
        except FileExistsError:
            if target.read_bytes() != payload:
                raise AssetPoolError("pool_report_immutable_conflict", "concurrent bytes differ")
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return target, True


def validate_asset_pool_report(report: Mapping[str, Any]) -> None:
    """Verify content identity, counts, and static/qualified authority separation."""

    require_valid_document(report, "daz_asset_pool_report")
    projection = report["qualification_projection"]
    qualified = projection["qualified_asset_ids"]
    expected_set_sha = _canonical_sha({"qualified_asset_ids": qualified})
    if projection["qualification_set_sha256"] != expected_set_sha:
        raise AssetPoolError("pool_qualification_set_hash_mismatch", str(report["report_id"]))
    for pool in report["pools"]:
        static = pool["static_candidate_asset_ids"]
        members = pool["qualified_member_asset_ids"]
        if static != sorted(static) or members != sorted(members):
            raise AssetPoolError("pool_membership_order_invalid", str(pool["pool_id"]))
        if not set(members).issubset(static) or not set(members).issubset(qualified):
            raise AssetPoolError("pool_qualified_membership_invalid", str(pool["pool_id"]))
        if pool["static_candidate_count"] != len(static):
            raise AssetPoolError("pool_static_count_mismatch", str(pool["pool_id"]))
        if pool["qualified_member_count"] != len(members):
            raise AssetPoolError("pool_qualified_count_mismatch", str(pool["pool_id"]))
        if pool["generation_enabled"] != bool(members):
            raise AssetPoolError("pool_generation_state_mismatch", str(pool["pool_id"]))
    summary = {
        "pool_count": len(report["pools"]),
        "static_candidate_memberships": sum(
            pool["static_candidate_count"] for pool in report["pools"]
        ),
        "qualified_member_memberships": sum(
            pool["qualified_member_count"] for pool in report["pools"]
        ),
        "generation_enabled_pool_count": sum(
            pool["generation_enabled"] for pool in report["pools"]
        ),
        "empty_static_candidate_pool_count": sum(
            pool["static_candidate_count"] == 0 for pool in report["pools"]
        ),
    }
    if report["summary"] != summary:
        raise AssetPoolError("pool_summary_mismatch", str(report["report_id"]))
    fingerprint = _canonical_sha(
        {
            "graph_id": report["graph_id"],
            "pool_version": report["pool_version"],
            "qualified_asset_ids": qualified,
            "qualification_projection_sha256": projection["certificate_projection_sha256"],
            "pools": report["pools"],
        }
    )
    if report["report_sha256"] != fingerprint or report["report_id"] != f"apr_{fingerprint[:24]}":
        raise AssetPoolError("pool_report_identity_mismatch", str(report["report_id"]))


def _matches_pool(node: Mapping[str, Any], definition: Mapping[str, Any]) -> bool:
    return (
        node["primary_asset_class"] in definition["primary_asset_classes"]
        and bool(set(node["figure_generations"]) & set(definition["figure_generations"]))
        and node["character_scope"] in definition["character_scopes"]
        and bool(set(node["scene_categories"]) & set(definition["scene_categories"]))
        and set(definition["capabilities"]).issubset(node["capabilities"])
    )


def _canonical_sha(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()


__all__ = [
    "AssetPoolError",
    "REQUIRED_POOL_IDS",
    "build_asset_pool_report",
    "load_asset_pool_policy",
    "publish_asset_pool_report",
    "validate_asset_pool_report",
    "validate_asset_pool_policy",
]
