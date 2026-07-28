"""Deterministic compatible selection of qualified figure, preset, and skin assets."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from ...validation import require_valid_document
from ..assets.catalog import validate_asset_compatibility_graph
from ..assets.pools import validate_asset_pool_report

FOUNDATION_POOLS = {
    "figure": "g9_adult_base_figures",
    "preset": "g9_adult_character_presets",
    "skin": "g9_skin_materials_by_tone_band",
}


class SceneSelectionError(ValueError):
    """Qualified scene assets cannot satisfy the requested foundation combination."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def select_character_foundation(
    graph: Mapping[str, Any],
    pool_report: Mapping[str, Any],
    *,
    selection_seed: int,
    figure_generation: str = "genesis_9",
    scene_category: str = "clothed",
    tone_band: str | None = None,
) -> dict[str, Any]:
    """Select one compatible qualified base/preset/skin tuple independent of registry order."""

    validate_asset_compatibility_graph(graph)
    validate_asset_pool_report(pool_report)
    if (
        pool_report["graph_id"] != graph["graph_id"]
        or pool_report["graph_sha256"] != graph["graph_sha256"]
    ):
        raise SceneSelectionError("selection_graph_pool_mismatch", str(pool_report["report_id"]))
    if (
        not isinstance(selection_seed, int)
        or isinstance(selection_seed, bool)
        or not 0 <= selection_seed < 2**64
    ):
        raise SceneSelectionError("selection_seed_invalid", str(selection_seed))
    if figure_generation != "genesis_9":
        raise SceneSelectionError("selection_generation_unsupported", figure_generation)
    if scene_category not in {
        "clothed",
        "partial_clothing",
        "underwear",
        "swimwear",
        "unclothed",
        "neutral",
    }:
        raise SceneSelectionError("selection_scene_category_invalid", scene_category)
    if tone_band is not None and (
        not isinstance(tone_band, str) or not tone_band or not tone_band.replace("_", "a").isalnum()
    ):
        raise SceneSelectionError("selection_tone_band_invalid", str(tone_band))

    nodes = {str(node["asset_id"]): node for node in graph["nodes"]}
    pools = {str(pool["pool_id"]): pool for pool in pool_report["pools"]}
    qualified = set(pool_report["qualification_projection"]["qualified_asset_ids"])
    candidates: dict[str, list[str]] = {}
    for role, pool_id in FOUNDATION_POOLS.items():
        pool = pools.get(pool_id)
        if pool is None:
            raise SceneSelectionError("selection_required_pool_missing", pool_id)
        candidates[role] = sorted(pool["qualified_member_asset_ids"])
        if not candidates[role]:
            raise SceneSelectionError("selection_qualified_pool_empty", pool_id)

    rejection_counts: Counter[str] = Counter()
    combinations = []
    for base_id in candidates["figure"]:
        base = nodes[base_id]
        for preset_id in candidates["preset"]:
            preset = nodes[preset_id]
            for skin_id in candidates["skin"]:
                skin = nodes[skin_id]
                reason = _combination_rejection_reason(
                    base,
                    preset,
                    skin,
                    qualified=qualified,
                    figure_generation=figure_generation,
                    scene_category=scene_category,
                    tone_band=tone_band,
                )
                if reason is not None:
                    rejection_counts[reason] += 1
                    continue
                combination = (base_id, preset_id, skin_id)
                combinations.append(
                    (
                        _combination_rank(
                            selection_seed,
                            graph_sha256=str(graph["graph_sha256"]),
                            pool_report_sha256=str(pool_report["report_sha256"]),
                            combination=combination,
                        ),
                        combination,
                    )
                )
    if not combinations:
        raise SceneSelectionError(
            "selection_no_compatible_combination",
            json.dumps(dict(sorted(rejection_counts.items())), sort_keys=True),
        )
    combinations.sort()
    _, selected = combinations[0]
    request = {
        "selection_seed": selection_seed,
        "figure_generation": figure_generation,
        "scene_category": scene_category,
        "tone_band": tone_band,
    }
    content = {
        "graph_id": graph["graph_id"],
        "graph_sha256": graph["graph_sha256"],
        "pool_report_id": pool_report["report_id"],
        "pool_report_sha256": pool_report["report_sha256"],
        "request": request,
        "candidate_counts": {
            "base_figures": len(candidates["figure"]),
            "character_presets": len(candidates["preset"]),
            "skin_materials": len(candidates["skin"]),
            "compatible_combinations": len(combinations),
        },
        "rejection_counts": dict(sorted(rejection_counts.items())),
        "selected": {
            "figure_asset_id": selected[0],
            "character_preset_asset_id": selected[1],
            "skin_material_asset_id": selected[2],
        },
        "compatibility_evidence": {
            "all_assets_runtime_qualified": True,
            "all_required_dependencies_runtime_qualified": True,
            "generation_match": True,
            "scene_category_match": True,
            "preset_base_match": True,
            "skin_base_match": True,
            "tone_band_match": True,
        },
    }
    digest = _canonical_sha(content)
    document = {
        "schema_version": "1.0.0",
        "selection_id": f"dcfs_{digest[:24]}",
        "selection_sha256": digest,
        **content,
    }
    require_valid_document(document, "daz_character_foundation_selection")
    return document


def validate_character_foundation_selection(
    selection: Mapping[str, Any],
    graph: Mapping[str, Any],
    pool_report: Mapping[str, Any],
) -> None:
    """Recompute an exact selection and refuse stale or tampered output."""

    require_valid_document(selection, "daz_character_foundation_selection")
    request = selection["request"]
    expected = select_character_foundation(
        graph,
        pool_report,
        selection_seed=request["selection_seed"],
        figure_generation=request["figure_generation"],
        scene_category=request["scene_category"],
        tone_band=request["tone_band"],
    )
    if selection != expected:
        raise SceneSelectionError("selection_replay_mismatch", str(selection["selection_id"]))


def publish_character_foundation_selection(
    selection: Mapping[str, Any], output_root: Path
) -> tuple[Path, bool]:
    """Atomically publish immutable selection evidence after structural validation."""

    require_valid_document(selection, "daz_character_foundation_selection")
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{selection['selection_id']}.json"
    payload = json.dumps(selection, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise SceneSelectionError("selection_publication_conflict", str(target))
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


def _combination_rejection_reason(
    base: Mapping[str, Any],
    preset: Mapping[str, Any],
    skin: Mapping[str, Any],
    *,
    qualified: set[str],
    figure_generation: str,
    scene_category: str,
    tone_band: str | None,
) -> str | None:
    rows = (base, preset, skin)
    if any(row["asset_id"] not in qualified for row in rows):
        return "asset_not_runtime_qualified"
    if any(figure_generation not in row["figure_generations"] for row in rows):
        return "generation_mismatch"
    if any(scene_category not in row["scene_categories"] for row in rows):
        return "scene_category_mismatch"
    if not _base_compatible(preset, str(base["asset_id"])):
        return "preset_base_mismatch"
    if not _base_compatible(skin, str(base["asset_id"])):
        return "skin_base_mismatch"
    if tone_band is not None and skin["facets"].get("tone_band") != tone_band:
        return "tone_band_mismatch"
    required_dependencies = {
        str(dependency["target_asset_id"])
        for row in rows
        for dependency in row["dependencies"]
        if dependency["required"]
    }
    if not required_dependencies.issubset(qualified):
        return "required_dependency_not_runtime_qualified"
    return None


def _base_compatible(node: Mapping[str, Any], base_id: str) -> bool:
    bases = set(node["compatibility_bases"])
    return not bases or base_id in bases


def _combination_rank(
    selection_seed: int,
    *,
    graph_sha256: str,
    pool_report_sha256: str,
    combination: tuple[str, str, str],
) -> str:
    return _canonical_sha(
        {
            "algorithm": "sha256_rank_v1",
            "selection_seed": selection_seed,
            "graph_sha256": graph_sha256,
            "pool_report_sha256": pool_report_sha256,
            "combination": list(combination),
        }
    )


def _canonical_sha(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()


__all__ = [
    "FOUNDATION_POOLS",
    "SceneSelectionError",
    "publish_character_foundation_selection",
    "select_character_foundation",
    "validate_character_foundation_selection",
]
