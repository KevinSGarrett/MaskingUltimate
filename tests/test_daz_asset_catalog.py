from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.daz.assets import (
    AssetCatalogError,
    build_asset_compatibility_graph,
    load_asset_vocabularies,
    publish_asset_compatibility_graph,
    validate_asset_compatibility_graph,
)

ROOT = Path(__file__).resolve().parents[1]
VOCABULARIES = ROOT / "configs" / "daz" / "asset_vocabularies.yaml"
AUTHORITATIVE = (
    ROOT / "Plan" / "Daz" / "Asset_Manifest" / "vocabularies" / "controlled_vocabularies.yaml"
)


def _id(token: str) -> str:
    return "ast_" + token * 24


def _record(token: str, primary_class: str, **overrides) -> dict:
    record = {
        "asset_id": _id(token),
        "asset_sha256": token * 64,
        "primary_asset_class": primary_class,
        "identity_status": "unique",
        "mapping_requirement": "none",
        "character_scope": "adult_human",
        "figure_generations": ["genesis_9"],
        "scene_categories": ["clothed"],
        "compatibility_bases": [],
        "required_plugins": [],
        "capabilities": [],
        "facets": {},
        "dependencies": [],
    }
    record.update(overrides)
    return record


def test_runtime_vocabulary_copy_is_closed_unique_and_blueprint_hash_bound() -> None:
    document = load_asset_vocabularies(VOCABULARIES, authoritative_source=AUTHORITATIVE)
    assert document["primary_asset_classes"][0] == "figure_base"
    assert document["primary_asset_classes"][-1] == "unknown"
    assert "genesis_9" in document["figure_generations"]
    assert document["source_sha256"] == (
        "f8181470dcc2095278ef3407379925b89c56be8814d4300c73992da1a5c9c1f9"
    )


def test_graph_is_deterministic_and_never_promotes_static_eligibility_to_qualification(
    tmp_path: Path,
) -> None:
    vocabularies = load_asset_vocabularies(VOCABULARIES)
    base = _record("a", "figure_base")
    wardrobe = _record(
        "b",
        "wardrobe_top",
        compatibility_bases=[base["asset_id"]],
        required_plugins=["dforce"],
        dependencies=[
            {"target_asset_id": base["asset_id"], "relation": "fits_to", "required": True}
        ],
    )
    plugins = {
        "dforce": {
            "state": "available",
            "version": "1.0.0",
            "sha256": "c" * 64,
        }
    }
    first = build_asset_compatibility_graph([wardrobe, base], vocabularies, plugins=plugins)
    second = build_asset_compatibility_graph([base, wardrobe], vocabularies, plugins=plugins)
    assert first == second
    assert first["summary"] == {
        "asset_count": 2,
        "edge_count": 2,
        "static_eligible_pending_smoke": 2,
        "ineligible_count": 0,
        "unknown_asset_count": 0,
        "unresolved_required_edge_count": 0,
        "qualified_asset_count": 0,
    }
    assert all(node["qualified"] is False for node in first["nodes"])
    assert all(node["generation_pool_eligible"] is True for node in first["nodes"])

    output = tmp_path / "published"
    target, published = publish_asset_compatibility_graph(first, output)
    assert published is True
    assert publish_asset_compatibility_graph(first, output) == (target, False)


def test_unknown_identity_missing_dependency_plugin_and_base_fail_closed() -> None:
    vocabularies = load_asset_vocabularies(VOCABULARIES)
    missing = _id("f")
    records = [
        _record(
            "a",
            "unknown",
            identity_status="duplicate_copy",
            figure_generations=["other_or_unknown"],
            compatibility_bases=[missing],
            required_plugins=["not-installed"],
            dependencies=[{"target_asset_id": missing, "relation": "requires", "required": True}],
        )
    ]
    graph = build_asset_compatibility_graph(records, vocabularies)
    node = graph["nodes"][0]
    assert node["generation_pool_eligible"] is False
    assert node["qualified"] is False
    assert node["blocking_reasons"] == [
        "ineligible_identity_conflict",
        "ineligible_incompatible_base",
        "ineligible_missing_dependency",
        "ineligible_missing_plugin",
        "ineligible_unclassified",
    ]
    assert graph["summary"]["unresolved_required_edge_count"] == 2


def test_invalid_vocabulary_duplicate_id_and_required_cycle_are_rejected() -> None:
    vocabularies = load_asset_vocabularies(VOCABULARIES)
    invalid = deepcopy(vocabularies)
    invalid["primary_asset_classes"].append("unknown")
    with pytest.raises(AssetCatalogError, match="vocabulary_values_invalid"):
        build_asset_compatibility_graph([], invalid)

    record = _record("a", "figure_base")
    with pytest.raises(AssetCatalogError, match="asset_id_duplicate"):
        build_asset_compatibility_graph([record, record], vocabularies)

    left = _record(
        "a",
        "figure_base",
        dependencies=[{"target_asset_id": _id("b"), "relation": "requires", "required": True}],
    )
    right = _record(
        "b",
        "figure_base",
        dependencies=[{"target_asset_id": _id("a"), "relation": "requires", "required": True}],
    )
    with pytest.raises(AssetCatalogError, match="dependency_cycle"):
        build_asset_compatibility_graph([left, right], vocabularies)


def test_catalog_cli_publishes_graph_and_rejects_unhashed_available_plugin(tmp_path: Path) -> None:
    records = tmp_path / "records.json"
    records.write_text(json.dumps([_record("a", "figure_base")]), encoding="utf-8")
    runner = CliRunner()
    invocation = runner.invoke(
        main,
        [
            "daz",
            "assets",
            "catalog-graph",
            "--records",
            str(records),
            "--output",
            str(tmp_path / "published"),
        ],
    )
    assert invocation.exit_code == 0, invocation.output
    assert json.loads(invocation.output)["reason"] == "asset_catalog_graph_complete"

    plugins = tmp_path / "plugins.json"
    plugins.write_text(
        json.dumps({"bad": {"state": "available", "version": None, "sha256": None}}),
        encoding="utf-8",
    )
    invocation = runner.invoke(
        main,
        [
            "daz",
            "assets",
            "catalog-graph",
            "--records",
            str(records),
            "--plugins",
            str(plugins),
            "--output",
            str(tmp_path / "published"),
        ],
    )
    assert invocation.exit_code == 88
    assert "lacks version/hash" in json.loads(invocation.output)["reason"]


def test_graph_identity_summary_and_edge_resolution_tampering_fail_closed() -> None:
    vocabularies = load_asset_vocabularies(VOCABULARIES)
    base = _record("a", "figure_base")
    preset = _record("b", "character_preset", compatibility_bases=[base["asset_id"]])
    graph = build_asset_compatibility_graph([base, preset], vocabularies)
    validate_asset_compatibility_graph(graph)

    changed_node = deepcopy(graph)
    changed_node["nodes"][0]["asset_sha256"] = "f" * 64
    with pytest.raises(AssetCatalogError, match="catalog_graph_identity_mismatch"):
        validate_asset_compatibility_graph(changed_node)

    changed_summary = deepcopy(graph)
    changed_summary["summary"]["asset_count"] = 1
    with pytest.raises(AssetCatalogError, match="catalog_graph_summary_mismatch"):
        validate_asset_compatibility_graph(changed_summary)

    changed_edge = deepcopy(graph)
    changed_edge["edges"][0]["resolved"] = False
    plugin_map = {
        row["plugin_id"]: {
            "state": row["state"],
            "version": row["version"],
            "sha256": row["sha256"],
        }
        for row in changed_edge["plugins"]
    }
    digest = hashlib.sha256(
        json.dumps(
            {
                "nodes": changed_edge["nodes"],
                "edges": changed_edge["edges"],
                "plugins": plugin_map,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    changed_edge["graph_sha256"] = digest
    changed_edge["graph_id"] = "acg_" + digest[:24]
    with pytest.raises(AssetCatalogError, match="catalog_graph_edge_resolution_mismatch"):
        validate_asset_compatibility_graph(changed_edge)
