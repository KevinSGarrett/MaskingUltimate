"""Exact ontology/vocabulary authority for registered body-part models."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from ..ontology import Ontology, get_ontology, load_ontology
from ..ontology_v2 import DEFAULT_ONTOLOGY_V2, OntologyV2Error, resolve_v2_alias

V1_ONTOLOGY_VERSION = "body_parts_v1"
V2_ONTOLOGY_VERSION = "body_parts_v2"
V1_PART_CLASS_NAMES = tuple(
    label.name
    for label in sorted(get_ontology().labels_for_map("part"), key=lambda item: int(item.id))
)
V2_ONTOLOGY = load_ontology(DEFAULT_ONTOLOGY_V2)
V2_PART_CLASS_NAMES = tuple(
    label.name
    for label in sorted(V2_ONTOLOGY.labels_for_map("part"), key=lambda item: int(item.id))
)
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class ModelOntologyContractError(ValueError):
    """A registered model's ontology identity or vocabulary is unsafe."""


def class_names_sha256(class_names: tuple[str, ...] | list[str]) -> str:
    names = tuple(class_names)
    return hashlib.sha256(
        json.dumps(names, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def ontology_for_version(version: str) -> Ontology:
    if version == V1_ONTOLOGY_VERSION:
        return get_ontology()
    if version == V2_ONTOLOGY_VERSION:
        return V2_ONTOLOGY
    raise ModelOntologyContractError(f"unsupported body-part ontology version: {version!r}")


def validate_bodypart_model_contract(
    entry: Mapping[str, Any], *, require_explicit: bool = False
) -> dict[str, Any]:
    """Return exact body-part model metadata; v2 never receives legacy inference."""
    raw_names = entry.get("class_names")
    if not isinstance(raw_names, list) or not all(
        isinstance(name, str) and name for name in raw_names
    ):
        if require_explicit:
            raise ModelOntologyContractError("body-part model lacks explicit class_names")
        raw_names = list(V1_PART_CLASS_NAMES)
    names = tuple(raw_names)
    if len(names) != len(set(names)):
        raise ModelOntologyContractError("body-part model class_names are not unique")
    version = entry.get("ontology_version")
    if version is None and not require_explicit:
        version = V1_ONTOLOGY_VERSION
    if version not in {V1_ONTOLOGY_VERSION, V2_ONTOLOGY_VERSION}:
        raise ModelOntologyContractError("body-part model lacks a supported ontology_version")
    expected = V2_PART_CLASS_NAMES if version == V2_ONTOLOGY_VERSION else V1_PART_CLASS_NAMES
    if names != expected:
        raise ModelOntologyContractError(
            f"{version} body-part vocabulary must be exact {len(expected)} names in ID order"
        )
    vocabulary_sha = class_names_sha256(list(names))
    declared_vocabulary_sha = entry.get("class_names_sha256")
    if declared_vocabulary_sha is not None and declared_vocabulary_sha != vocabulary_sha:
        raise ModelOntologyContractError("body-part class_names_sha256 mismatch")
    checkpoint_sha = entry.get("sha256")
    config_sha = entry.get("inference_config_sha256")
    if require_explicit or version == V2_ONTOLOGY_VERSION:
        if not all(
            isinstance(value, str) and SHA256_PATTERN.fullmatch(value)
            for value in (checkpoint_sha, config_sha)
        ):
            raise ModelOntologyContractError("body-part artifact hashes are incomplete")
        expected_hashes = {
            "checkpoint_sha256": checkpoint_sha,
            "inference_config_sha256": config_sha,
        }
        if entry.get("artifact_hashes") != expected_hashes:
            raise ModelOntologyContractError("body-part artifact_hashes do not match artifacts")
    return {
        "ontology_version": version,
        "class_names": list(names),
        "class_names_sha256": vocabulary_sha,
        "num_classes": len(names),
        "artifact_hashes": {
            "checkpoint_sha256": checkpoint_sha,
            "inference_config_sha256": config_sha,
        },
    }


def canonicalize_served_selector(value: str, *, ontology_version: str) -> dict[str, Any]:
    """Canonicalize one atomic serving selector and preserve requested provenance."""
    if not isinstance(value, str) or not value.strip():
        raise ModelOntologyContractError("served selector must be a non-empty string")
    requested = value.strip()
    ontology = ontology_for_version(ontology_version)
    try:
        label = ontology.label(requested)
        canonical = requested
        was_alias = False
        warning = None
    except Exception as original:
        if ontology_version != V2_ONTOLOGY_VERSION:
            raise ModelOntologyContractError(
                f"unknown ontology label requested: {requested}"
            ) from original
        try:
            resolution = resolve_v2_alias(requested)
        except OntologyV2Error as exc:
            raise ModelOntologyContractError(str(exc)) from exc
        canonical = resolution.canonical
        was_alias = resolution.was_alias
        warning = resolution.warning
        try:
            label = ontology.label(canonical)
        except Exception as exc:
            raise ModelOntologyContractError(
                f"served selector is a derived union, not an atomic model class: {canonical}"
            ) from exc
    if label.id is None:
        raise ModelOntologyContractError(
            f"served selector is a derived union, not an atomic model class: {canonical}"
        )
    if label.map not in {"part", "material"}:
        raise ModelOntologyContractError(
            f"served selector is not an indexed atomic model class: {canonical}"
        )
    return {
        "requested": requested,
        "canonical": canonical,
        "was_alias": was_alias,
        "warning": warning,
        "ontology_version": ontology_version,
        "class_id": int(label.id),
        "map": label.map,
    }
