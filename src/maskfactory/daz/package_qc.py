"""Independent MaskFactory and DAZ QC for certificate-bound adapted packages."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml
from PIL import Image

from ..synthetic_manifest import validate_synthetic_manifest
from ..validation import require_valid_document
from .mapping import build_v1_ontology_snapshot
from .render import decode_u16_png_exact
from .s00_adapter import validate_s00_adapter_report


class AdaptedPackageQcError(ValueError):
    """The QC policy, immutable input contract, or publication is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


EXISTING_REQUIRED = [
    "QC-001",
    "QC-002",
    "QC-003",
    "QC-004",
    "QC-005",
    "QC-006",
    "QC-007",
    "QC-009",
    "QC-011",
    "QC-012",
    "QC-013",
    "QC-035",
    "QC-036",
    "QC-038",
]
EXISTING_NOT_APPLICABLE = {
    "QC-008": "synthetic packages use exact indexed visibility truth, not review-state rows",
    "QC-010": "accepted DAZ packages are full-frame and contain no crop transforms",
    "QC-037": (
        "relationship reciprocity is certified upstream by DAZ V7 and no contact claim is emitted "
        "by this package boundary"
    ),
}
DAZ_REQUIRED = [f"DAZ-QC-{index:03d}" for index in range(1, 8)]


def load_adapted_package_qc_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_adapted_package_qc_policy(document)
    return document


def validate_adapted_package_qc_policy(policy: Mapping[str, Any]) -> None:
    if not isinstance(policy, Mapping) or set(policy) != {
        "schema_version",
        "policy_version",
        "active_ontology",
        "existing_qc",
        "daz_qc",
        "allowed_protected_ids",
        "publication",
    }:
        raise AdaptedPackageQcError("adapted_qc_policy_fields_invalid", str(policy))
    if (
        policy["schema_version"] != "1.0.0"
        or policy["policy_version"] != "1.0.0"
        or policy["active_ontology"] != "body_parts_v1"
        or policy["existing_qc"]
        != {"required": EXISTING_REQUIRED, "not_applicable": EXISTING_NOT_APPLICABLE}
        or policy["daz_qc"] != {"required": DAZ_REQUIRED}
        or policy["allowed_protected_ids"] != [0, 50]
        or policy["publication"]
        != {
            "immutable": True,
            "atomic": True,
            "source_read_only": True,
            "failure_blocks_freeze": True,
        }
    ):
        raise AdaptedPackageQcError("adapted_qc_policy_identity_invalid", str(policy))


def run_adapted_package_qc(
    adapted_root: Path,
    adapter_report: Mapping[str, Any],
    package_contract: Mapping[str, Any],
    *,
    policy: Mapping[str, Any],
    ontology_source: Path,
    output_root: Path,
) -> tuple[dict[str, Any], Path, bool]:
    """Run every applicable existing and DAZ-specific check, then publish its report."""

    validate_adapted_package_qc_policy(policy)
    validate_s00_adapter_report(adapter_report)
    require_valid_document(package_contract, "daz_package_derivation_contract")
    _verify_contract_hash(package_contract)
    if (
        adapter_report["contract_id"] != package_contract["contract_id"]
        or adapter_report["contract_sha256"] != package_contract["contract_sha256"]
        or adapter_report["ontology_version"] != policy["active_ontology"]
    ):
        raise AdaptedPackageQcError("adapted_qc_input_binding_invalid", adapter_report["scene_id"])
    ontology = build_v1_ontology_snapshot(Path(ontology_source))
    if (
        ontology["canonical_sha256"] != adapter_report["ontology_sha256"]
        or ontology["canonical_sha256"] != package_contract["ontology_snapshot_sha256"]
    ):
        raise AdaptedPackageQcError("adapted_qc_ontology_invalid", adapter_report["scene_id"])

    root = Path(adapted_root).resolve(strict=True)
    before = _tree_digest(root)
    rows = {row["p_index"]: row for row in adapter_report["packages"]}
    expected_indices = [owner["p_index"] for owner in package_contract["owners"]]
    if list(rows) != expected_indices:
        raise AdaptedPackageQcError("adapted_qc_package_order_invalid", str(rows))
    inspections = [
        _inspect_package(
            root / rows[p_index]["relative_root"],
            rows[p_index],
            adapter_report,
            package_contract,
            policy,
            ontology,
        )
        for p_index in expected_indices
    ]
    results = _build_results(inspections, adapter_report, package_contract, policy)
    required = set(EXISTING_REQUIRED + DAZ_REQUIRED)
    required_pass = sum(row["check_id"] in required and row["status"] == "pass" for row in results)
    failed = sum(row["status"] == "fail" for row in results)
    content = {
        "policy_version": policy["policy_version"],
        "policy_sha256": _canonical_sha(policy),
        "adapter_report_id": adapter_report["report_id"],
        "adapter_report_sha256": adapter_report["report_sha256"],
        "contract_id": package_contract["contract_id"],
        "contract_sha256": package_contract["contract_sha256"],
        "scene_id": adapter_report["scene_id"],
        "image_id": adapter_report["image_id"],
        "scene_family_id": adapter_report["scene_family_id"],
        "ontology_version": adapter_report["ontology_version"],
        "ontology_sha256": adapter_report["ontology_sha256"],
        "package_count": len(inspections),
        "results": results,
        "summary": {
            "passed": failed == 0 and required_pass == len(required),
            "required_count": len(required),
            "required_pass_count": required_pass,
            "not_applicable_count": sum(row["status"] == "not_applicable" for row in results),
            "failed_count": failed,
            "existing_qc_count": sum(
                row["check_family"] == "existing_maskfactory" for row in results
            ),
            "daz_qc_count": sum(row["check_family"] == "daz_specific" for row in results),
            "freeze_eligible": failed == 0 and required_pass == len(required),
        },
    }
    digest = _canonical_sha(content)
    report = {
        "schema_version": "1.0.0",
        "report_id": f"daqc_{digest[:24]}",
        "report_sha256": digest,
        **content,
    }
    require_valid_document(report, "daz_adapted_package_qc_report")
    if _tree_digest(root) != before:
        raise AdaptedPackageQcError("adapted_qc_source_mutated", str(root))
    return _publish_report(report, Path(output_root))


def validate_adapted_package_qc_report(report: Mapping[str, Any]) -> None:
    require_valid_document(report, "daz_adapted_package_qc_report")
    content = {
        key: value
        for key, value in report.items()
        if key not in {"schema_version", "report_id", "report_sha256"}
    }
    digest = _canonical_sha(content)
    if report["report_sha256"] != digest or report["report_id"] != f"daqc_{digest[:24]}":
        raise AdaptedPackageQcError("adapted_qc_report_hash_invalid", str(report.get("report_id")))


def _inspect_package(
    package: Path,
    row: Mapping[str, Any],
    adapter: Mapping[str, Any],
    contract: Mapping[str, Any],
    policy: Mapping[str, Any],
    ontology: Mapping[str, Any],
) -> dict[str, Any]:
    evidence: dict[str, Any] = {"p_index": row["p_index"], "errors": []}
    try:
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        evidence["manifest_schema"] = not validate_synthetic_manifest(manifest)
        expected_names = {entry["path"] for entry in manifest.get("files", {}).values()}
        actual_names = {path.name for path in package.iterdir() if path.is_file()}
        evidence["file_set"] = actual_names == expected_names | {"manifest.json"}
        evidence["file_hashes"] = all(
            (package / entry["path"]).is_file()
            and _file_sha(package / entry["path"]) == entry["sha256"]
            for entry in manifest.get("files", {}).values()
        )
        evidence["tree_hash"] = _tree_digest(package) == row["output_tree_sha256"]
        with Image.open(package / "source_rgb.png") as image:
            evidence["rgb_codec"] = image.format == "PNG" and image.mode in {"RGB", "RGBA"}
            source_size = image.size
        target = _binary(package / "full_body.png")
        other = _binary(package / "other_person.png")
        part, _part_codec = decode_u16_png_exact(package / "indexed_part.png")
        material, _material_codec = decode_u16_png_exact(package / "material.png")
        protected, _protected_codec = decode_u16_png_exact(package / "protected.png")
        evidence["dimensions"] = all(
            array.shape == (source_size[1], source_size[0])
            for array in (target, other, part, material, protected)
        )
        evidence["binary_values"] = True
        evidence["png_codecs"] = evidence["rgb_codec"]
        active_parts = {row_["id"] for row_ in ontology["part_labels"] if row_["enabled"]}
        evidence["namespaces"] = (
            set(int(value) for value in np.unique(part)) <= active_parts
            and set(int(value) for value in np.unique(material))
            <= set(contract["active_material_ids"])
            and set(int(value) for value in np.unique(protected))
            <= set(policy["allowed_protected_ids"])
        )
        evidence["indexed_consistency"] = bool(
            np.array_equal(part > 0, target) and np.array_equal(material > 0, target)
        )
        evidence["protected_consistency"] = bool(
            np.array_equal(protected == 50, other) and not np.any(target & (protected != 0))
        )
        evidence["target_nonempty"] = bool(target.any())
        evidence["target"] = target
        evidence["other"] = other
        authority = manifest.get("mask_authority", {})
        lineage = manifest.get("synthetic_lineage", {})
        evidence["authority"] = (
            authority.get("certificate_sha256") == adapter["certificate_sha256"]
            and authority.get("ontology_sha256") == adapter["ontology_sha256"]
            and authority.get("package_revision") == contract["contract_id"]
            and authority.get("owner") == "maskfactory"
            and authority.get("access_mode") == "mode_a_approved_package"
        )
        evidence["lineage"] = (
            manifest.get("scene_id") == adapter["scene_id"]
            and manifest.get("image_id") == adapter["image_id"]
            and manifest.get("scene_family_id") == adapter["scene_family_id"]
            and lineage.get("instance_mapping", {}).get("promoted_person_id") == row["p_index"]
            and lineage.get("instance_mapping", {}).get("instance_id") == row["instance_id"]
        )
        evidence["truth"] = (
            manifest.get("truth_tier") == "weighted_pseudo_label"
            and manifest.get("truth_partition") == "train"
            and manifest.get("train_eligible") is True
            and manifest.get("evaluation_eligible") is False
            and lineage.get("counts_as_human_anchor_gold") is False
            and lineage.get("counts_as_autonomous_certified_gold") is False
        )
        construction = manifest.get("person_construction", {})
        evidence["adult_no_human"] = (
            construction.get("anatomy_configuration") in {"adult_male", "adult_female"}
            and str(construction.get("age_appearance_category", "")).startswith("adult_")
            and evidence["manifest_schema"]
        )
    except Exception as exc:  # noqa: BLE001 - defects become deterministic QC failures
        evidence["errors"].append(f"{type(exc).__name__}:{exc}")
    return evidence


def _build_results(
    rows: list[dict[str, Any]],
    adapter: Mapping[str, Any],
    contract: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> list[dict[str, Any]]:
    def every(field: str) -> bool:
        return all(row.get(field) is True for row in rows)

    targets = [row.get("target") for row in rows]
    usable = all(isinstance(value, np.ndarray) for value in targets)
    disjoint = usable and not np.any(np.stack(targets).sum(axis=0) > 1)
    visible = np.logical_or.reduce(targets) if usable else None
    complements = usable and all(
        np.array_equal(row.get("other"), visible & ~row["target"]) for row in rows
    )
    checks = {
        "QC-001": every("dimensions"),
        "QC-002": every("binary_values"),
        "QC-003": every("png_codecs"),
        "QC-004": every("namespaces"),
        "QC-005": every("manifest_schema"),
        "QC-006": every("file_set") and every("file_hashes") and every("tree_hash"),
        "QC-007": every("indexed_consistency"),
        "QC-009": complements and every("protected_consistency"),
        "QC-011": every("indexed_consistency"),
        "QC-012": every("indexed_consistency"),
        "QC-013": every("protected_consistency"),
        "QC-035": disjoint,
        "QC-036": disjoint and complements,
        "QC-038": len(rows) == len(contract["owners"]) and 1 <= len(rows) <= 4,
        "DAZ-QC-001": adapter["invariants"]["certificate_replayed"] is True,
        "DAZ-QC-002": every("authority"),
        "DAZ-QC-003": every("file_set") and every("file_hashes") and every("tree_hash"),
        "DAZ-QC-004": every("lineage"),
        "DAZ-QC-005": every("truth"),
        "DAZ-QC-006": every("adult_no_human"),
        "DAZ-QC-007": all(adapter["invariants"].values()),
    }
    errors = [error for row in rows for error in row.get("errors", [])]
    results = [
        _result(check_id, checks[check_id], errors, "existing_maskfactory")
        for check_id in EXISTING_REQUIRED
    ]
    results.extend(
        _not_applicable(check_id, reason)
        for check_id, reason in policy["existing_qc"]["not_applicable"].items()
    )
    results.extend(
        _result(check_id, checks[check_id], errors, "daz_specific") for check_id in DAZ_REQUIRED
    )
    return results


def _result(check_id: str, passed: bool, errors: list[str], family: str) -> dict[str, Any]:
    detail = "verified" if passed else ("; ".join(errors) or "invariant failed")
    content = {"check_id": check_id, "passed": bool(passed), "detail": detail}
    return {
        "check_id": check_id,
        "check_family": family,
        "scope": "scene",
        "p_index": None,
        "status": "pass" if passed else "fail",
        "severity": "BLOCK",
        "reason_code": "VERIFIED" if passed else "QC_INVARIANT_FAILED",
        "detail": detail,
        "evidence_sha256": _canonical_sha(content),
    }


def _not_applicable(check_id: str, reason: str) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "check_family": "existing_maskfactory",
        "scope": "scene",
        "p_index": None,
        "status": "not_applicable",
        "severity": "INFO",
        "reason_code": "SYNTHETIC_CONTRACT_NOT_APPLICABLE",
        "detail": reason,
        "evidence_sha256": _canonical_sha({"check_id": check_id, "reason": reason}),
    }


def _publish_report(report: dict[str, Any], output_root: Path) -> tuple[dict[str, Any], Path, bool]:
    output_root.mkdir(parents=True, exist_ok=True)
    target = output_root / f"{report['report_id']}.json"
    payload = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise AdaptedPackageQcError("adapted_qc_publication_conflict", str(target))
        return report, target, False
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".adapted_qc.", suffix=".json", dir=output_root
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(payload, encoding="utf-8", newline="\n")
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return report, target, True


def _binary(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        if image.format != "PNG" or image.mode != "L":
            raise AdaptedPackageQcError("adapted_qc_binary_codec_invalid", str(path))
        array = np.asarray(image)
    if set(int(value) for value in np.unique(array)) > {0, 255}:
        raise AdaptedPackageQcError("adapted_qc_binary_values_invalid", str(path))
    return array == 255


def _verify_contract_hash(contract: Mapping[str, Any]) -> None:
    content = {
        key: value
        for key, value in contract.items()
        if key not in {"schema_version", "contract_id", "contract_sha256"}
    }
    digest = _canonical_sha(content)
    if contract["contract_sha256"] != digest or contract["contract_id"] != f"dpdc_{digest[:24]}":
        raise AdaptedPackageQcError(
            "adapted_qc_contract_hash_invalid", str(contract.get("contract_id"))
        )


def _tree_digest(root: Path) -> str:
    records = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": _file_sha(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(Path(root).rglob("*"))
        if path.is_file()
    ]
    if not records:
        raise AdaptedPackageQcError("adapted_qc_tree_empty", str(root))
    return _canonical_sha(records)


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha(document: Any) -> str:
    payload = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
