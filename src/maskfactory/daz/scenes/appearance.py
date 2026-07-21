"""Qualified deterministic skin, hair, wardrobe, and anatomy composition selection."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import yaml

from ...validation import require_valid_document
from ..assets.catalog import validate_asset_compatibility_graph
from ..assets.pools import validate_asset_pool_report
from .selection import validate_character_foundation_selection

WARDROBE_CLASSES = {
    "wardrobe_top",
    "wardrobe_bottom",
    "wardrobe_one_piece",
    "wardrobe_underwear",
    "wardrobe_swimwear",
    "wardrobe_outerwear",
    "wardrobe_glove",
    "wardrobe_sock",
    "wardrobe_footwear",
    "wardrobe_headwear",
    "accessory_wearable",
}


class AppearanceSelectionError(ValueError):
    """A qualified character appearance composition cannot be selected or replayed."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_appearance_selection_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_appearance_selection_policy(document)
    return document


def validate_appearance_selection_policy(policy: Mapping[str, Any]) -> None:
    if policy.get("schema_version") != "1.0.0" or policy.get("policy_version") != "1.0.0":
        raise AppearanceSelectionError("appearance_policy_version_invalid", "versions")
    if policy.get("anatomy_configurations") != [
        "adult_male_anatomy",
        "adult_female_anatomy",
    ] or policy.get("hair_modes") != ["none", "required"]:
        raise AppearanceSelectionError("appearance_policy_scope_invalid", "anatomy/hair")
    states = policy.get("wardrobe_states")
    expected_states = (
        "unclothed",
        "underwear_only",
        "swimwear",
        "minimal_clothing",
        "tight_fitted",
        "standard_casual",
        "loose_clothing",
        "layered_clothing",
        "formal",
        "athletic",
        "sleepwear",
        "outerwear",
        "workwear_or_uniform_generic",
        "costume_or_stylized_adult",
    )
    if not isinstance(states, Mapping) or tuple(states) != expected_states:
        raise AppearanceSelectionError("appearance_policy_wardrobe_states_invalid", str(states))
    for state, entry in states.items():
        if (
            not isinstance(entry, Mapping)
            or set(entry) != {"construction", "minimum_items", "allowed_fit_profiles"}
            or entry["construction"]
            not in {"none", "underwear", "swimwear", "partial", "full", "layered"}
            or not isinstance(entry["minimum_items"], int)
            or entry["minimum_items"] < 0
            or not isinstance(entry["allowed_fit_profiles"], list)
            or len(entry["allowed_fit_profiles"]) != len(set(entry["allowed_fit_profiles"]))
        ):
            raise AppearanceSelectionError("appearance_policy_wardrobe_state_invalid", state)
    layers = policy.get("layer_order")
    if (
        not isinstance(layers, Mapping)
        or not layers
        or any(not isinstance(value, int) or value < 0 for value in layers.values())
        or len(set(layers.values())) != len(layers)
    ):
        raise AppearanceSelectionError("appearance_policy_layer_order_invalid", str(layers))
    if policy.get("allowed_dynamic_behaviors") != ["static", "deterministic_baked"]:
        raise AppearanceSelectionError("appearance_policy_dynamic_invalid", "dynamic")
    if (
        policy.get("required_anatomy_asset_class") != "anatomy_geograft"
        or policy.get("required_anatomy_mapping_requirement") != "asset_specific"
        or policy.get("required_wardrobe_mapping_requirements")
        != ["inherited_base", "asset_specific"]
    ):
        raise AppearanceSelectionError("appearance_policy_mapping_invalid", "mapping")


def select_character_appearance(
    graph: Mapping[str, Any],
    pool_report: Mapping[str, Any],
    foundation_selection: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    selection_seed: int,
    anatomy_configuration: str,
    hair_mode: str,
    wardrobe_state: str,
) -> dict[str, Any]:
    """Select qualified anatomy/hair/wardrobe around an exact foundation selection."""

    validate_asset_compatibility_graph(graph)
    validate_asset_pool_report(pool_report)
    validate_character_foundation_selection(foundation_selection, graph, pool_report)
    validate_appearance_selection_policy(policy)
    if (
        not isinstance(selection_seed, int)
        or isinstance(selection_seed, bool)
        or not 0 <= selection_seed < 2**64
    ):
        raise AppearanceSelectionError("appearance_selection_seed_invalid", str(selection_seed))
    if anatomy_configuration not in policy["anatomy_configurations"]:
        raise AppearanceSelectionError("appearance_anatomy_invalid", anatomy_configuration)
    if hair_mode not in policy["hair_modes"]:
        raise AppearanceSelectionError("appearance_hair_mode_invalid", hair_mode)
    if wardrobe_state not in policy["wardrobe_states"]:
        raise AppearanceSelectionError("appearance_wardrobe_state_invalid", wardrobe_state)

    nodes = {str(node["asset_id"]): node for node in graph["nodes"]}
    qualified = set(pool_report["qualification_projection"]["qualified_asset_ids"])
    pools = {str(pool["pool_id"]): pool for pool in pool_report["pools"]}
    base_id = str(foundation_selection["selected"]["figure_asset_id"])
    skin_id = str(foundation_selection["selected"]["skin_material_asset_id"])
    scene_category = str(foundation_selection["request"]["scene_category"])
    if skin_id not in qualified:
        raise AppearanceSelectionError("appearance_foundation_skin_unqualified", skin_id)

    rejection_counts: Counter[str] = Counter()
    anatomy_candidates = []
    for asset_id in sorted(qualified):
        node = nodes[asset_id]
        reason = _anatomy_rejection(
            node,
            base_id=base_id,
            scene_category=scene_category,
            anatomy_configuration=anatomy_configuration,
            qualified=qualified,
            policy=policy,
        )
        if reason is None:
            anatomy_candidates.append(asset_id)
        elif node["primary_asset_class"] == policy["required_anatomy_asset_class"]:
            rejection_counts[reason] += 1
    if not anatomy_candidates:
        raise AppearanceSelectionError("appearance_anatomy_pool_empty", anatomy_configuration)

    hair_pool = pools.get("g9_hair_by_length_texture_construction")
    if hair_pool is None:
        raise AppearanceSelectionError("appearance_hair_pool_missing", "hair")
    hair_candidates = []
    for asset_id in hair_pool["qualified_member_asset_ids"]:
        reason = _common_rejection(
            nodes[asset_id],
            base_id=base_id,
            scene_category=scene_category,
            qualified=qualified,
        )
        if reason is None:
            hair_candidates.append(str(asset_id))
        else:
            rejection_counts[f"hair_{reason}"] += 1
    hair_options: list[str | None] = [None] if hair_mode == "none" else hair_candidates
    if hair_mode == "required" and not hair_options:
        raise AppearanceSelectionError("appearance_hair_pool_empty", "hair")

    wardrobe_pool = pools.get("g9_wardrobe_by_region_layer_fit")
    if wardrobe_pool is None:
        raise AppearanceSelectionError("appearance_wardrobe_pool_missing", "wardrobe")
    wardrobe_candidates = []
    for asset_id in wardrobe_pool["qualified_member_asset_ids"]:
        node = nodes[asset_id]
        reason = _wardrobe_rejection(
            node,
            base_id=base_id,
            scene_category=scene_category,
            wardrobe_state=wardrobe_state,
            qualified=qualified,
            policy=policy,
        )
        if reason is None:
            wardrobe_candidates.append(str(asset_id))
        else:
            rejection_counts[f"wardrobe_{reason}"] += 1
    wardrobe_sets = _wardrobe_combinations(
        wardrobe_candidates,
        nodes=nodes,
        state=wardrobe_state,
        policy=policy,
    )
    if not wardrobe_sets:
        raise AppearanceSelectionError("appearance_wardrobe_combination_empty", wardrobe_state)

    combinations = []
    for anatomy_id in anatomy_candidates:
        for hair_id in hair_options:
            for wardrobe_ids in wardrobe_sets:
                combination = {
                    "anatomy_asset_id": anatomy_id,
                    "hair_asset_id": hair_id,
                    "wardrobe_asset_ids": list(wardrobe_ids),
                }
                combinations.append(
                    (
                        _canonical_sha(
                            {
                                "algorithm": "sha256_rank_v1",
                                "selection_seed": selection_seed,
                                "foundation_selection_sha256": foundation_selection[
                                    "selection_sha256"
                                ],
                                "combination": combination,
                            }
                        ),
                        combination,
                    )
                )
    combinations.sort(key=lambda row: row[0])
    selected = combinations[0][1]
    wardrobe_records = [
        _wardrobe_record(nodes[asset_id]) for asset_id in selected["wardrobe_asset_ids"]
    ]
    request = {
        "selection_seed": selection_seed,
        "anatomy_configuration": anatomy_configuration,
        "hair_mode": hair_mode,
        "wardrobe_state": wardrobe_state,
    }
    content = {
        "graph_id": graph["graph_id"],
        "graph_sha256": graph["graph_sha256"],
        "pool_report_id": pool_report["report_id"],
        "pool_report_sha256": pool_report["report_sha256"],
        "foundation_selection_id": foundation_selection["selection_id"],
        "foundation_selection_sha256": foundation_selection["selection_sha256"],
        "request": request,
        "candidate_counts": {
            "anatomy_assets": len(anatomy_candidates),
            "hair_assets": len(hair_candidates),
            "wardrobe_assets": len(wardrobe_candidates),
            "wardrobe_combinations": len(wardrobe_sets),
            "appearance_combinations": len(combinations),
        },
        "rejection_counts": dict(sorted(rejection_counts.items())),
        "selected": {
            "skin_material_asset_id": skin_id,
            "anatomy_asset_id": selected["anatomy_asset_id"],
            "hair_asset_id": selected["hair_asset_id"],
            "wardrobe_state": wardrobe_state,
            "wardrobe_items_inner_to_outer": wardrobe_records,
        },
        "compatibility_evidence": {
            "all_assets_runtime_qualified": True,
            "all_required_dependencies_runtime_qualified": True,
            "base_compatibility_passed": True,
            "anatomy_mapping_required": True,
            "wardrobe_mapping_required": True,
            "inner_to_outer_order_defined": True,
            "dynamic_behavior_deterministic": True,
            "scene_category_match": True,
        },
    }
    digest = _canonical_sha(content)
    document = {
        "schema_version": "1.0.0",
        "selection_id": f"dcas_{digest[:24]}",
        "selection_sha256": digest,
        **content,
    }
    require_valid_document(document, "daz_character_appearance_selection")
    return document


def validate_character_appearance_selection(
    selection: Mapping[str, Any],
    graph: Mapping[str, Any],
    pool_report: Mapping[str, Any],
    foundation_selection: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> None:
    require_valid_document(selection, "daz_character_appearance_selection")
    request = selection["request"]
    expected = select_character_appearance(
        graph,
        pool_report,
        foundation_selection,
        policy,
        selection_seed=request["selection_seed"],
        anatomy_configuration=request["anatomy_configuration"],
        hair_mode=request["hair_mode"],
        wardrobe_state=request["wardrobe_state"],
    )
    if selection != expected:
        raise AppearanceSelectionError(
            "appearance_selection_replay_mismatch", str(selection["selection_id"])
        )


def publish_character_appearance_selection(
    selection: Mapping[str, Any], output_root: Path
) -> tuple[Path, bool]:
    """Atomically publish one immutable appearance selection document."""

    require_valid_document(selection, "daz_character_appearance_selection")
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{selection['selection_id']}.json"
    payload = json.dumps(selection, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise AppearanceSelectionError("appearance_publication_conflict", str(target))
        return target, False
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=root
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target, True


def _common_rejection(
    node: Mapping[str, Any], *, base_id: str, scene_category: str, qualified: set[str]
) -> str | None:
    if node["asset_id"] not in qualified:
        return "not_runtime_qualified"
    if scene_category not in node["scene_categories"]:
        return "scene_category_mismatch"
    bases = set(node["compatibility_bases"])
    if bases and base_id not in bases:
        return "base_mismatch"
    required = {str(row["target_asset_id"]) for row in node["dependencies"] if row["required"]}
    if not required.issubset(qualified):
        return "required_dependency_unqualified"
    return None


def _anatomy_rejection(
    node: Mapping[str, Any],
    *,
    base_id: str,
    scene_category: str,
    anatomy_configuration: str,
    qualified: set[str],
    policy: Mapping[str, Any],
) -> str | None:
    if node["primary_asset_class"] != policy["required_anatomy_asset_class"]:
        return "not_anatomy_asset"
    common = _common_rejection(
        node, base_id=base_id, scene_category=scene_category, qualified=qualified
    )
    if common is not None:
        return common
    if node["facets"].get("anatomy_configuration") != anatomy_configuration:
        return "configuration_mismatch"
    if node["mapping_requirement"] != policy["required_anatomy_mapping_requirement"]:
        return "mapping_requirement_missing"
    return None


def _wardrobe_rejection(
    node: Mapping[str, Any],
    *,
    base_id: str,
    scene_category: str,
    wardrobe_state: str,
    qualified: set[str],
    policy: Mapping[str, Any],
) -> str | None:
    if node["primary_asset_class"] not in WARDROBE_CLASSES:
        return "not_wardrobe"
    common = _common_rejection(
        node, base_id=base_id, scene_category=scene_category, qualified=qualified
    )
    if common is not None:
        return common
    if node["mapping_requirement"] not in policy["required_wardrobe_mapping_requirements"]:
        return "territory_mapping_missing"
    facets = node["facets"]
    for field in (
        "wardrobe_region",
        "wardrobe_layer",
        "fit_profile",
        "opacity_class",
        "dynamic_behavior",
    ):
        if not facets.get(field):
            return f"facet_missing_{field}"
    if facets["wardrobe_layer"] not in policy["layer_order"]:
        return "layer_unknown"
    if facets["dynamic_behavior"] not in policy["allowed_dynamic_behaviors"]:
        return "dynamic_nondeterministic"
    state_policy = policy["wardrobe_states"][wardrobe_state]
    if facets["fit_profile"] not in state_policy["allowed_fit_profiles"]:
        return "fit_profile_mismatch"
    declared_state = facets.get("wardrobe_state")
    if declared_state is not None and declared_state != wardrobe_state:
        return "state_mismatch"
    construction = state_policy["construction"]
    if construction == "underwear" and node["primary_asset_class"] not in {
        "wardrobe_underwear",
        "wardrobe_one_piece",
    }:
        return "underwear_class_mismatch"
    if construction == "swimwear" and node["primary_asset_class"] not in {
        "wardrobe_swimwear",
        "wardrobe_one_piece",
    }:
        return "swimwear_class_mismatch"
    return None


def _wardrobe_combinations(
    candidates: list[str],
    *,
    nodes: Mapping[str, Mapping[str, Any]],
    state: str,
    policy: Mapping[str, Any],
) -> list[tuple[str, ...]]:
    state_policy = policy["wardrobe_states"][state]
    construction = state_policy["construction"]
    if construction == "none":
        return [()]
    if construction in {"underwear", "swimwear", "partial"}:
        return [(_sorted_wardrobe((asset_id,), nodes, policy)) for asset_id in candidates]
    one_piece = [
        asset_id
        for asset_id in candidates
        if nodes[asset_id]["primary_asset_class"] == "wardrobe_one_piece"
    ]
    tops = [
        asset_id
        for asset_id in candidates
        if nodes[asset_id]["primary_asset_class"] == "wardrobe_top"
    ]
    bottoms = [
        asset_id
        for asset_id in candidates
        if nodes[asset_id]["primary_asset_class"] == "wardrobe_bottom"
    ]
    base_sets = [(asset_id,) for asset_id in one_piece] + [
        (top, bottom) for top in tops for bottom in bottoms
    ]
    if construction == "full":
        raw_sets = base_sets
    else:
        outer = [
            asset_id
            for asset_id in candidates
            if nodes[asset_id]["primary_asset_class"] == "wardrobe_outerwear"
        ]
        raw_sets = [(*base, outer_id) for base in base_sets for outer_id in outer]
    minimum = int(state_policy["minimum_items"])
    canonical = {
        _sorted_wardrobe(item_set, nodes, policy)
        for item_set in raw_sets
        if len(item_set) >= minimum
    }
    return sorted(canonical)


def _sorted_wardrobe(
    asset_ids: tuple[str, ...],
    nodes: Mapping[str, Mapping[str, Any]],
    policy: Mapping[str, Any],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            asset_ids,
            key=lambda asset_id: (
                policy["layer_order"][nodes[asset_id]["facets"]["wardrobe_layer"]],
                asset_id,
            ),
        )
    )


def _wardrobe_record(node: Mapping[str, Any]) -> dict[str, Any]:
    facets = node["facets"]
    return {
        "asset_id": node["asset_id"],
        "primary_asset_class": node["primary_asset_class"],
        "wardrobe_region": facets["wardrobe_region"],
        "wardrobe_layer": facets["wardrobe_layer"],
        "fit_profile": facets["fit_profile"],
        "opacity_class": facets["opacity_class"],
        "dynamic_behavior": facets["dynamic_behavior"],
    }


def _canonical_sha(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()


__all__ = [
    "AppearanceSelectionError",
    "WARDROBE_CLASSES",
    "load_appearance_selection_policy",
    "publish_character_appearance_selection",
    "select_character_appearance",
    "validate_appearance_selection_policy",
    "validate_character_appearance_selection",
]
