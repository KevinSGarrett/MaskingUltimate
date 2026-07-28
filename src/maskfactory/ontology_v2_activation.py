"""Failure-atomic rehearsal for the ontology-v2 and derived-authority pair.

This module deliberately exposes rehearsal only. Production activation remains
blocked by MF-P7-06.06 and must add the complete registry/workflow/model gate.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from .ontology_generator import build_ontology
from .ontology_v2 import (
    DEFAULT_DERIVED_V2,
    DEFAULT_ONTOLOGY_V2,
    build_derived_v2,
    build_ontology_v2,
    render_derived_v2,
    render_ontology_v2,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ACTIVE_ONTOLOGY = ROOT / "configs" / "ontology.yaml"
DEFAULT_ACTIVE_DERIVED = ROOT / "configs" / "derived.yaml"
DEFAULT_REHEARSAL_EVIDENCE = (
    ROOT / "qa" / "live_verification" / "ontology_v2_derived_activation_20260715.json"
)
REQUIRED_V2_DERIVED = {
    "both_areolae": "part:left_areola | part:right_areola",
    "both_nipples": "part:left_nipple | part:right_nipple",
    "left_nipple_areola_complex": "part:left_areola | part:left_nipple",
    "right_nipple_areola_complex": "part:right_areola | part:right_nipple",
    "both_nipple_areola_complexes": (
        "derived:left_nipple_areola_complex | derived:right_nipple_areola_complex"
    ),
    "left_breast_full": "part:left_breast | part:left_areola | part:left_nipple",
    "right_breast_full": "part:right_breast | part:right_areola | part:right_nipple",
    "both_breasts_full": "derived:left_breast_full | derived:right_breast_full",
    "penis_visible": "part:penis_shaft | part:glans_penis",
    "scrotum_visible": "part:left_scrotal_region | part:right_scrotal_region",
    "external_genitalia_visible": "part:vulva | derived:penis_visible | derived:scrotum_visible",
    "external_pelvic_anatomy_visible": "derived:external_genitalia_visible | part:anus",
    "pelvic_anatomy_visible": "part:pelvic_region | derived:external_pelvic_anatomy_visible",
}


class OntologyV2ActivationError(ValueError):
    """An ontology/derived authority pair is incomplete, stale, or non-atomic."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_yaml(data: bytes, name: str) -> dict[str, Any]:
    try:
        document = yaml.safe_load(data.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise OntologyV2ActivationError(f"{name} is invalid YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise OntologyV2ActivationError(f"{name} root must be a mapping")
    return document


def _render(document: Mapping[str, Any]) -> bytes:
    return yaml.safe_dump(dict(document), sort_keys=False, allow_unicode=True, width=100).encode(
        "utf-8"
    )


def _derived_names(ontology: Mapping[str, Any]) -> set[str]:
    labels = ontology.get("labels")
    if not isinstance(labels, list):
        raise OntologyV2ActivationError("ontology labels must be a list")
    return {
        str(label["name"])
        for label in labels
        if isinstance(label, Mapping) and label.get("mask_type") == "derived_union"
    }


def validate_v2_authority_pair(
    ontology_data: bytes,
    derived_data: bytes,
    *,
    expected_status: str,
) -> dict[str, Any]:
    """Validate exact ontology-v2 identity and one formula for every derived label."""
    ontology = _load_yaml(ontology_data, "ontology-v2 authority")
    derived = _load_yaml(derived_data, "derived-v2 authority")
    if (
        ontology.get("config_version") != "2.0.0"
        or ontology.get("mask_ontology_version") != "body_parts_v2"
        or ontology.get("activation_status") != expected_status
    ):
        raise OntologyV2ActivationError("ontology-v2 authority identity/status is invalid")
    if (
        derived.get("config_version") != "2.0.0"
        or derived.get("mask_ontology_version") != "body_parts_v2"
        or derived.get("activation_status") != expected_status
        or not isinstance(derived.get("formulas"), dict)
    ):
        raise OntologyV2ActivationError("derived-v2 authority identity/status is invalid")
    formula_names = set(derived["formulas"])
    expected_names = _derived_names(ontology)
    if formula_names != expected_names:
        raise OntologyV2ActivationError(
            "derived-v2 formula registry does not exactly match ontology derived labels"
        )
    for name, formula in REQUIRED_V2_DERIVED.items():
        if derived["formulas"].get(name) != formula:
            raise OntologyV2ActivationError(f"derived-v2 required formula drifted: {name}")
    part_labels = [
        label
        for label in ontology["labels"]
        if isinstance(label, Mapping) and label.get("map") == "part"
    ]
    if [label.get("id") for label in part_labels] != list(range(66)):
        raise OntologyV2ActivationError("ontology-v2 PART IDs are not exact contiguous 0..65")
    return {
        "ontology_version": "body_parts_v2",
        "activation_status": expected_status,
        "part_class_count": 66,
        "formula_count": len(formula_names),
        "required_v2_formula_count": len(REQUIRED_V2_DERIVED),
        "ontology_sha256": _sha256(ontology_data),
        "derived_sha256": _sha256(derived_data),
    }


def render_active_v2_authority_pair() -> tuple[bytes, bytes]:
    """Render activation-ready bytes without writing either active authority."""
    ontology = deepcopy(build_ontology_v2())
    derived = deepcopy(build_derived_v2())
    ontology["activation_status"] = "active"
    derived["activation_status"] = "active"
    rendered = (_render(ontology), _render(derived))
    validate_v2_authority_pair(*rendered, expected_status="active")
    return rendered


def _validate_active_v1(ontology_data: bytes, derived_data: bytes) -> None:
    ontology = _load_yaml(ontology_data, "active ontology")
    derived = _load_yaml(derived_data, "active derived authority")
    expected_formulas = {
        label["name"]: label["formula"]
        for label in build_ontology()["labels"]
        if label["mask_type"] == "derived_union"
    }
    if ontology.get("mask_ontology_version") != "body_parts_v1":
        raise OntologyV2ActivationError("active source ontology is not body_parts_v1")
    if derived.get("formulas") != expected_formulas:
        raise OntologyV2ActivationError("active v1 derived authority has drifted")


def _write_fsynced(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _restore_exact(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.restore-{uuid.uuid4().hex}")
    try:
        _write_fsynced(temporary, data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _switch_pair_failure_atomic(
    ontology_path: Path,
    derived_path: Path,
    ontology_data: bytes,
    derived_data: bytes,
    *,
    replace: Callable[[Path, Path], None] = os.replace,
) -> dict[str, Any]:
    """Replace both files or restore both exact originals after any observed failure."""
    ontology_path = Path(ontology_path)
    derived_path = Path(derived_path)
    if ontology_path.parent.resolve() != derived_path.parent.resolve():
        raise OntologyV2ActivationError("ontology and derived authorities must share a directory")
    originals = {
        ontology_path: ontology_path.read_bytes(),
        derived_path: derived_path.read_bytes(),
    }
    _validate_active_v1(originals[ontology_path], originals[derived_path])
    desired = {ontology_path: ontology_data, derived_path: derived_data}
    validate_v2_authority_pair(ontology_data, derived_data, expected_status="active")
    staged = {path: path.with_name(f".{path.name}.activate-{uuid.uuid4().hex}") for path in desired}
    try:
        for path, data in desired.items():
            _write_fsynced(staged[path], data)
        for path in (ontology_path, derived_path):
            replace(staged[path], path)
        for path, data in desired.items():
            if path.read_bytes() != data:
                raise OntologyV2ActivationError(f"post-replace authority bytes differ: {path.name}")
        active = validate_v2_authority_pair(
            ontology_path.read_bytes(),
            derived_path.read_bytes(),
            expected_status="active",
        )
    except Exception as exc:
        restoration_errors: list[str] = []
        for path, data in originals.items():
            try:
                _restore_exact(path, data)
            except Exception as restore_exc:
                restoration_errors.append(f"{path.name}: {restore_exc}")
        restored = all(path.read_bytes() == data for path, data in originals.items())
        if restoration_errors or not restored:
            detail = "; ".join(restoration_errors) or "restored bytes differ"
            raise OntologyV2ActivationError(
                f"v2 pair switch failed and exact v1 restoration failed: {detail}"
            ) from exc
        raise OntologyV2ActivationError(
            f"v2 pair switch failed; exact v1 pair restored: {exc}"
        ) from exc
    finally:
        for path in staged.values():
            path.unlink(missing_ok=True)
    return {
        "before": {path.name: _sha256(data) for path, data in originals.items()},
        "after": {
            ontology_path.name: _sha256(ontology_path.read_bytes()),
            derived_path.name: _sha256(derived_path.read_bytes()),
        },
        "active": active,
    }


def rehearse_v2_authority_pair(
    *,
    active_ontology: Path | str = DEFAULT_ACTIVE_ONTOLOGY,
    active_derived: Path | str = DEFAULT_ACTIVE_DERIVED,
    inactive_ontology: Path | str = DEFAULT_ONTOLOGY_V2,
    inactive_derived: Path | str = DEFAULT_DERIVED_V2,
) -> dict[str, Any]:
    """Prove switch/rollback behavior on isolated copies and preserve active production v1."""
    active_ontology = Path(active_ontology)
    active_derived = Path(active_derived)
    inactive_ontology = Path(inactive_ontology)
    inactive_derived = Path(inactive_derived)
    source_before = {
        active_ontology: active_ontology.read_bytes(),
        active_derived: active_derived.read_bytes(),
    }
    _validate_active_v1(source_before[active_ontology], source_before[active_derived])
    if inactive_ontology.read_text(encoding="utf-8") != render_ontology_v2():
        raise OntologyV2ActivationError("inactive ontology_v2.yaml has generator drift")
    if inactive_derived.read_text(encoding="utf-8") != render_derived_v2():
        raise OntologyV2ActivationError("inactive derived_v2.yaml has generator drift")
    inactive = validate_v2_authority_pair(
        inactive_ontology.read_bytes(),
        inactive_derived.read_bytes(),
        expected_status="approved_design_not_active",
    )
    desired_ontology, desired_derived = render_active_v2_authority_pair()

    with tempfile.TemporaryDirectory(prefix="maskfactory-v2-authority-rehearsal-") as directory:
        root = Path(directory)
        rehearsal_ontology = root / "ontology.yaml"
        rehearsal_derived = root / "derived.yaml"
        _write_fsynced(rehearsal_ontology, source_before[active_ontology])
        _write_fsynced(rehearsal_derived, source_before[active_derived])
        success = _switch_pair_failure_atomic(
            rehearsal_ontology,
            rehearsal_derived,
            desired_ontology,
            desired_derived,
        )
        _restore_exact(rehearsal_ontology, source_before[active_ontology])
        _restore_exact(rehearsal_derived, source_before[active_derived])

        calls = 0

        def fail_second(source: Path, destination: Path) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("seeded second-file activation failure")
            os.replace(source, destination)

        try:
            _switch_pair_failure_atomic(
                rehearsal_ontology,
                rehearsal_derived,
                desired_ontology,
                desired_derived,
                replace=fail_second,
            )
        except OntologyV2ActivationError as exc:
            if "exact v1 pair restored" not in str(exc):
                raise
        else:
            raise OntologyV2ActivationError("seeded partial-write failure unexpectedly passed")
        if (
            rehearsal_ontology.read_bytes() != source_before[active_ontology]
            or rehearsal_derived.read_bytes() != source_before[active_derived]
        ):
            raise OntologyV2ActivationError("failure rehearsal did not restore exact v1 bytes")

    if any(path.read_bytes() != data for path, data in source_before.items()):
        raise OntologyV2ActivationError("rehearsal mutated an active production authority")
    from .ontology_v2_inactive_gates import (
        OntologyV2InactiveGateError,
        require_inactive_v2_authority,
    )

    try:
        require_inactive_v2_authority(
            {
                "activation_status": "approved_design_not_active",
                "ontology_version": "body_parts_v2",
                "active_runtime_ontology": "body_parts_v1",
                "production_activation_performed": False,
                "mapping_authority": False,
            }
        )
    except OntologyV2InactiveGateError as exc:
        raise OntologyV2ActivationError(str(exc)) from exc
    document = {
        "schema_version": "1.0.0",
        "mode": "isolated_copy_no_production_activation",
        "active_ontology_preserved": "body_parts_v1",
        "activation_status": "approved_design_not_active",
        "production_activation_performed": False,
        "inactive_drift_check": "pass",
        "inactive": inactive,
        "successful_pair_switch": success,
        "seeded_second_file_failure_restored_v1": True,
        "source_unchanged": True,
    }
    document["sha256"] = hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return document


def write_v2_authority_rehearsal_evidence(
    path: Path | str = DEFAULT_REHEARSAL_EVIDENCE,
    **kwargs: Any,
) -> Path:
    """Write the sealed rehearsal result without mutating either active authority."""
    output = Path(path)
    document = rehearse_v2_authority_pair(**kwargs)
    temporary = output.with_name(f".{output.name}.tmp-{uuid.uuid4().hex}")
    try:
        _write_fsynced(
            temporary,
            (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


__all__ = (
    "OntologyV2ActivationError",
    "DEFAULT_REHEARSAL_EVIDENCE",
    "REQUIRED_V2_DERIVED",
    "rehearse_v2_authority_pair",
    "render_active_v2_authority_pair",
    "validate_v2_authority_pair",
    "write_v2_authority_rehearsal_evidence",
)
