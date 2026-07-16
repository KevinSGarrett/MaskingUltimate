"""Closed DAZ asset vocabulary and static compatibility-graph validation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from ...validation import require_valid_document

ASSET_ID_PATTERN = re.compile(r"^ast_[0-9a-f]{24}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_VOCABULARIES = (
    "primary_asset_classes",
    "figure_generations",
    "dependency_relations",
    "scene_categories",
    "mapping_requirements",
    "identity_statuses",
    "plugin_states",
    "static_states",
    "character_scopes",
    "capabilities",
    "facet_keys",
)


class AssetCatalogError(ValueError):
    """A closed-vocabulary or compatibility-graph refusal."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_asset_vocabularies(
    path: Path,
    *,
    authoritative_source: Path | None = None,
) -> dict[str, Any]:
    """Load the checked runtime copy and optionally prove its blueprint lineage."""

    path = Path(path)
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema_version") != "1.0.0":
        raise AssetCatalogError("vocabulary_schema_invalid", "schema_version must be 1.0.0")
    if document.get("vocabulary_version") != "1.0.0":
        raise AssetCatalogError("vocabulary_version_invalid", "unsupported vocabulary version")
    source_sha = document.get("source_sha256")
    if not isinstance(source_sha, str) or not SHA256_PATTERN.fullmatch(source_sha):
        raise AssetCatalogError("vocabulary_lineage_invalid", "source SHA-256 is missing")
    for field in REQUIRED_VOCABULARIES:
        values = document.get(field)
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(value, str) or not value for value in values)
            or len(values) != len(set(values))
        ):
            raise AssetCatalogError(
                "vocabulary_values_invalid", f"{field} must be a nonempty unique string list"
            )
    required_sentinels = {
        "primary_asset_classes": "unknown",
        "figure_generations": "other_or_unknown",
        "identity_statuses": "shadow_conflict",
        "static_states": "ineligible_unclassified",
    }
    for field, sentinel in required_sentinels.items():
        if sentinel not in document[field]:
            raise AssetCatalogError("vocabulary_sentinel_missing", f"{field} lacks {sentinel}")
    if authoritative_source is not None:
        source_path = Path(authoritative_source).resolve(strict=True)
        if _sha256_file(source_path) != source_sha:
            raise AssetCatalogError(
                "vocabulary_lineage_drift", "authoritative vocabulary SHA-256 changed"
            )
        source = yaml.safe_load(source_path.read_text(encoding="utf-8"))
        expected = {
            "primary_asset_classes": source.get("primary_asset_classes"),
            "figure_generations": source.get("generations"),
            "dependency_relations": source.get("dependency_relations"),
        }
        for field, values in expected.items():
            if document[field] != values:
                raise AssetCatalogError(
                    "vocabulary_runtime_copy_drift", f"runtime copy differs for {field}"
                )
    return document


def build_asset_compatibility_graph(
    records: Iterable[Mapping[str, Any]],
    vocabularies: Mapping[str, Any],
    *,
    plugins: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a deterministic static graph; runtime smoke remains a later authority layer."""

    _validate_vocabulary_mapping(vocabularies)
    plugin_registry = dict(plugins or {})
    _validate_plugin_registry(plugin_registry, vocabularies)
    normalized = [_normalize_record(record, vocabularies) for record in records]
    normalized.sort(key=lambda row: row["asset_id"])
    asset_ids = [str(row["asset_id"]) for row in normalized]
    duplicates = sorted(value for value, count in Counter(asset_ids).items() if count > 1)
    if duplicates:
        raise AssetCatalogError(
            "catalog_asset_id_duplicate", "duplicate asset IDs: " + ", ".join(duplicates)
        )
    by_id = {str(row["asset_id"]): row for row in normalized}
    edges = []
    missing_targets: dict[str, list[str]] = {}
    for row in normalized:
        source_id = str(row["asset_id"])
        for dependency in row["dependencies"]:
            target = str(dependency["target_asset_id"])
            relation = str(dependency["relation"])
            resolved = target in by_id
            edges.append(
                {
                    "source_asset_id": source_id,
                    "target_asset_id": target,
                    "relation": relation,
                    "required": bool(dependency["required"]),
                    "resolved": resolved,
                }
            )
            if dependency["required"] and not resolved:
                missing_targets.setdefault(source_id, []).append(target)
        for target in row["compatibility_bases"]:
            resolved = target in by_id and by_id[target]["primary_asset_class"] == "figure_base"
            edges.append(
                {
                    "source_asset_id": source_id,
                    "target_asset_id": target,
                    "relation": "compatibility_base",
                    "required": True,
                    "resolved": resolved,
                }
            )
    _reject_required_cycles(edges)
    nodes = []
    for row in normalized:
        asset_id = str(row["asset_id"])
        reasons = []
        if (
            row["primary_asset_class"] == "unknown"
            or "other_or_unknown" in row["figure_generations"]
        ):
            reasons.append("ineligible_unclassified")
        if row["identity_status"] in {"duplicate_copy", "shadow_conflict"}:
            reasons.append("ineligible_identity_conflict")
        if missing_targets.get(asset_id):
            reasons.append("ineligible_missing_dependency")
        incompatible_bases = sorted(
            edge["target_asset_id"]
            for edge in edges
            if edge["source_asset_id"] == asset_id
            and edge["relation"] == "compatibility_base"
            and not edge["resolved"]
        )
        if incompatible_bases:
            reasons.append("ineligible_incompatible_base")
        missing_plugins = sorted(
            plugin
            for plugin in row["required_plugins"]
            if plugin not in plugin_registry or plugin_registry[plugin].get("state") != "available"
        )
        if missing_plugins:
            reasons.append("ineligible_missing_plugin")
        static_state = reasons[0] if reasons else "static_eligible_pending_smoke"
        nodes.append(
            {
                **row,
                "static_state": static_state,
                "blocking_reasons": sorted(set(reasons)),
                "missing_dependency_asset_ids": sorted(set(missing_targets.get(asset_id, []))),
                "missing_plugin_ids": missing_plugins,
                "incompatible_base_ids": incompatible_bases,
                "generation_pool_eligible": static_state == "static_eligible_pending_smoke",
                "qualified": False,
                "qualification_boundary": "runtime_smoke_and_mapping_certificate_required",
            }
        )
    edges.sort(
        key=lambda edge: (
            edge["source_asset_id"],
            edge["relation"],
            edge["target_asset_id"],
        )
    )
    fingerprint = _canonical_sha({"nodes": nodes, "edges": edges, "plugins": plugin_registry})
    document = {
        "schema_version": "1.0.0",
        "graph_id": f"acg_{fingerprint[:24]}",
        "graph_sha256": fingerprint,
        "vocabulary_version": vocabularies["vocabulary_version"],
        "vocabulary_source_sha256": vocabularies["source_sha256"],
        "summary": {
            "asset_count": len(nodes),
            "edge_count": len(edges),
            "static_eligible_pending_smoke": sum(
                row["static_state"] == "static_eligible_pending_smoke" for row in nodes
            ),
            "ineligible_count": sum(
                row["static_state"] != "static_eligible_pending_smoke" for row in nodes
            ),
            "unknown_asset_count": sum(row["primary_asset_class"] == "unknown" for row in nodes),
            "unresolved_required_edge_count": sum(
                edge["required"] and not edge["resolved"] for edge in edges
            ),
            "qualified_asset_count": 0,
        },
        "plugins": [
            {
                "plugin_id": plugin_id,
                "state": entry.get("state"),
                "version": entry.get("version"),
                "sha256": entry.get("sha256"),
            }
            for plugin_id, entry in sorted(plugin_registry.items())
        ],
        "nodes": nodes,
        "edges": edges,
    }
    require_valid_document(document, "daz_asset_compatibility_graph")
    return document


def publish_asset_compatibility_graph(
    graph: Mapping[str, Any], output_root: Path
) -> tuple[Path, bool]:
    """Publish one immutable graph revision without replacing an existing identity."""

    require_valid_document(graph, "daz_asset_compatibility_graph")
    graph_id = str(graph["graph_id"])
    payload = (json.dumps(graph, indent=2, sort_keys=True) + "\n").encode("utf-8")
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    target = output_root / f"{graph_id}.json"
    if target.exists():
        if target.read_bytes() != payload:
            raise AssetCatalogError(
                "catalog_graph_immutable_conflict", "existing graph bytes differ"
            )
        return target, False
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{graph_id}.", suffix=".tmp", dir=output_root
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
                raise AssetCatalogError(
                    "catalog_graph_immutable_conflict", "concurrent graph bytes differ"
                )
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return target, True


def _validate_vocabulary_mapping(vocabularies: Mapping[str, Any]) -> None:
    if vocabularies.get("schema_version") != "1.0.0":
        raise AssetCatalogError("vocabulary_schema_invalid", "schema_version must be 1.0.0")
    for field in REQUIRED_VOCABULARIES:
        values = vocabularies.get(field)
        if not isinstance(values, list) or not values or len(values) != len(set(values)):
            raise AssetCatalogError("vocabulary_values_invalid", field)


def _normalize_record(record: Mapping[str, Any], vocabularies: Mapping[str, Any]) -> dict[str, Any]:
    asset_id = record.get("asset_id")
    if not isinstance(asset_id, str) or not ASSET_ID_PATTERN.fullmatch(asset_id):
        raise AssetCatalogError("catalog_asset_id_invalid", str(asset_id))
    scalar_vocabularies = {
        "primary_asset_class": "primary_asset_classes",
        "identity_status": "identity_statuses",
        "mapping_requirement": "mapping_requirements",
        "character_scope": "character_scopes",
    }
    normalized: dict[str, Any] = {"asset_id": asset_id}
    for field, vocabulary in scalar_vocabularies.items():
        value = record.get(field)
        if value not in vocabularies[vocabulary]:
            raise AssetCatalogError("catalog_vocabulary_invalid", f"{asset_id}:{field}:{value}")
        normalized[field] = value
    list_vocabularies = {
        "figure_generations": "figure_generations",
        "scene_categories": "scene_categories",
    }
    for field, vocabulary in list_vocabularies.items():
        values = record.get(field)
        if not isinstance(values, list) or not values or len(values) != len(set(values)):
            raise AssetCatalogError("catalog_list_invalid", f"{asset_id}:{field}")
        unknown = sorted(set(values) - set(vocabularies[vocabulary]))
        if unknown:
            raise AssetCatalogError(
                "catalog_vocabulary_invalid", f"{asset_id}:{field}:{','.join(unknown)}"
            )
        normalized[field] = sorted(values)
    for field in ("compatibility_bases", "required_plugins"):
        values = record.get(field, [])
        if (
            not isinstance(values, list)
            or len(values) != len(set(values))
            or any(not isinstance(value, str) or not value for value in values)
        ):
            raise AssetCatalogError("catalog_list_invalid", f"{asset_id}:{field}")
        normalized[field] = sorted(values)
    capabilities = record.get("capabilities", [])
    if not isinstance(capabilities, list) or len(capabilities) != len(set(capabilities)):
        raise AssetCatalogError("catalog_list_invalid", f"{asset_id}:capabilities")
    unknown_capabilities = sorted(set(capabilities) - set(vocabularies["capabilities"]))
    if unknown_capabilities:
        raise AssetCatalogError(
            "catalog_vocabulary_invalid",
            f"{asset_id}:capabilities:{','.join(unknown_capabilities)}",
        )
    normalized["capabilities"] = sorted(capabilities)
    facets = record.get("facets", {})
    if not isinstance(facets, Mapping):
        raise AssetCatalogError("catalog_facets_invalid", asset_id)
    unknown_facets = sorted(set(facets) - set(vocabularies["facet_keys"]))
    if unknown_facets:
        raise AssetCatalogError(
            "catalog_vocabulary_invalid", f"{asset_id}:facets:{','.join(unknown_facets)}"
        )
    if any(
        not isinstance(value, str) or not re.fullmatch(r"^[a-z][a-z0-9_]*$", value)
        for value in facets.values()
    ):
        raise AssetCatalogError("catalog_facets_invalid", asset_id)
    normalized["facets"] = dict(sorted(facets.items()))
    dependencies = record.get("dependencies", [])
    if not isinstance(dependencies, list):
        raise AssetCatalogError("catalog_dependencies_invalid", asset_id)
    normalized_dependencies = []
    seen_dependencies = set()
    for dependency in dependencies:
        if not isinstance(dependency, Mapping):
            raise AssetCatalogError("catalog_dependencies_invalid", asset_id)
        target = dependency.get("target_asset_id")
        relation = dependency.get("relation")
        required = dependency.get("required")
        if (
            not isinstance(target, str)
            or not ASSET_ID_PATTERN.fullmatch(target)
            or relation not in vocabularies["dependency_relations"]
            or not isinstance(required, bool)
        ):
            raise AssetCatalogError("catalog_dependencies_invalid", asset_id)
        identity = (target, relation)
        if identity in seen_dependencies:
            raise AssetCatalogError("catalog_dependency_duplicate", f"{asset_id}:{identity}")
        seen_dependencies.add(identity)
        normalized_dependencies.append(
            {"target_asset_id": target, "relation": relation, "required": required}
        )
    normalized["dependencies"] = sorted(
        normalized_dependencies, key=lambda row: (row["relation"], row["target_asset_id"])
    )
    return normalized


def _reject_required_cycles(edges: list[dict[str, Any]]) -> None:
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        if (
            edge["required"]
            and edge["resolved"]
            and edge["relation"] not in {"conflicts", "supersedes", "compatibility_base"}
        ):
            adjacency.setdefault(edge["source_asset_id"], []).append(edge["target_asset_id"])
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(asset_id: str, trail: tuple[str, ...]) -> None:
        if asset_id in visiting:
            cycle = trail[trail.index(asset_id) :]
            raise AssetCatalogError("catalog_dependency_cycle", " -> ".join(cycle))
        if asset_id in visited:
            return
        visiting.add(asset_id)
        for target in sorted(adjacency.get(asset_id, [])):
            visit(target, trail + (target,))
        visiting.remove(asset_id)
        visited.add(asset_id)

    for asset_id in sorted(adjacency):
        visit(asset_id, (asset_id,))


def _validate_plugin_registry(
    plugins: Mapping[str, Mapping[str, Any]], vocabularies: Mapping[str, Any]
) -> None:
    for plugin_id, record in plugins.items():
        if not isinstance(plugin_id, str) or not plugin_id or not isinstance(record, Mapping):
            raise AssetCatalogError("catalog_plugin_registry_invalid", str(plugin_id))
        state = record.get("state")
        if state not in vocabularies["plugin_states"]:
            raise AssetCatalogError("catalog_plugin_registry_invalid", f"{plugin_id}:{state}")
        if state == "available" and (
            not isinstance(record.get("version"), str)
            or not record["version"]
            or not isinstance(record.get("sha256"), str)
            or not SHA256_PATTERN.fullmatch(record["sha256"])
        ):
            raise AssetCatalogError(
                "catalog_plugin_registry_invalid",
                f"available plugin lacks version/hash: {plugin_id}",
            )


def _canonical_sha(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "AssetCatalogError",
    "build_asset_compatibility_graph",
    "load_asset_vocabularies",
    "publish_asset_compatibility_graph",
]
