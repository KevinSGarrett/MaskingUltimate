"""Independent D8 identity, exclusivity, and cross-person bleed validation."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml
from PIL import Image, UnidentifiedImageError

from ..validation import require_valid_document
from .render import decode_u16_png_exact
from .scenes import PIndexAssignmentError, validate_p_index_assignment


class MultiPersonIdentityValidationError(ValueError):
    """A V7 policy, bound input, raster, package, or report is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


VALIDATORS = (
    ("DAZ-V7-001", "assignment_lineage_exact"),
    ("DAZ-V7-002", "construction_instance_remap_exact"),
    ("DAZ-V7-003", "target_owner_identity_exact"),
    ("DAZ-V7-004", "target_ownership_exclusive"),
    ("DAZ-V7-005", "target_ownership_complete"),
    ("DAZ-V7-006", "target_other_complements_exact"),
    ("DAZ-V7-007", "package_hashes_and_shared_rgb_exact"),
    ("DAZ-V7-008", "scene_image_family_grouping_exact"),
)


def load_multi_person_identity_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_multi_person_identity_policy(document)
    return document


def validate_multi_person_identity_policy(policy: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "policy_version",
        "validator_set_version",
        "scope",
        "maximum_people",
        "required_validators",
        "requirements",
        "publication",
    }
    if not isinstance(policy, Mapping) or set(policy) != expected:
        raise MultiPersonIdentityValidationError(
            "multi_identity_policy_fields_invalid", str(policy)
        )
    if (
        policy["schema_version"] != "1.0.0"
        or policy["policy_version"] != "1.0.0"
        or policy["validator_set_version"] != "1.0.0"
        or policy["scope"] != "d8_multi_person_identity_exclusivity_bleed"
        or policy["maximum_people"] != 4
        or policy["required_validators"] != [row[0] for row in VALIDATORS]
        or policy["requirements"]
        != {
            "accepted_p_index_assignment": True,
            "exact_construction_to_instance_remap": True,
            "exact_target_owner_masks": True,
            "pairwise_exclusive_targets": True,
            "complete_visible_target_union": True,
            "exact_target_other_complements": True,
            "exact_package_hashes_and_shared_rgb": True,
            "exact_scene_image_family_grouping": True,
            "vectorized_full_image_checks": True,
            "source_read_only": True,
        }
        or policy["publication"]
        != {"immutable": True, "atomic": True, "failure_blocks_acceptance": True}
    ):
        raise MultiPersonIdentityValidationError(
            "multi_identity_policy_identity_invalid", str(policy)
        )


def evaluate_multi_person_identity(
    contract: Mapping[str, Any],
    derivation_report: Mapping[str, Any],
    assignment: Mapping[str, Any],
    *,
    construction_map_path: Path,
    instance_map_path: Path,
    derived_scene_root: Path,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute full-image identity, exclusivity, completeness, and bleed evidence."""

    validate_multi_person_identity_policy(policy)
    require_valid_document(contract, "daz_package_derivation_contract")
    _verify_hashed_document(contract, "contract_id", "contract_sha256", "dpdc")
    require_valid_document(derivation_report, "daz_package_derivation_report")
    _verify_hashed_document(derivation_report, "report_id", "report_sha256", "dpdr")
    try:
        validate_p_index_assignment(assignment)
    except PIndexAssignmentError as exc:
        raise MultiPersonIdentityValidationError(
            "multi_identity_assignment_invalid", exc.reason
        ) from exc
    binding = contract.get("p_index_assignment")
    if not isinstance(binding, Mapping):
        raise MultiPersonIdentityValidationError(
            "multi_identity_assignment_binding_missing", contract["contract_id"]
        )
    if not 2 <= len(contract["owners"]) <= policy["maximum_people"]:
        raise MultiPersonIdentityValidationError(
            "multi_identity_people_count_invalid", str(len(contract["owners"]))
        )
    root = Path(derived_scene_root).resolve(strict=True)
    before = _tree_digest(root)
    construction_path = Path(construction_map_path)
    instance_path = Path(instance_map_path)
    construction_payload = construction_path.read_bytes()
    instance_payload = instance_path.read_bytes()
    construction, construction_codec = decode_u16_png_exact(construction_path)
    instance, instance_codec = decode_u16_png_exact(instance_path)
    expected_shape = (contract["resolution"][1], contract["resolution"][0])
    if construction.shape != expected_shape or instance.shape != expected_shape:
        raise MultiPersonIdentityValidationError(
            "multi_identity_source_resolution_invalid",
            str((construction.shape, instance.shape, expected_shape)),
        )

    assignment_mapping = [
        {
            "slot_id": row["slot_id"],
            "construction_id": row["construction_id"],
            "source_instance_id": next(
                person["source_instance_id"]
                for person in assignment["persons"]
                if person["construction_id"] == row["construction_id"]
            ),
            "p_index": row["p_index"],
            "instance_id": row["instance_id"],
        }
        for row in assignment["mapping"]
    ]
    lineage_exact = (
        assignment["summary"]["accepted"] is True
        and binding["assignment_id"] == assignment["assignment_id"]
        and binding["assignment_sha256"] == assignment["assignment_sha256"]
        and binding["assignment_policy_sha256"] == assignment["policy_sha256"]
        and binding["duo_selection_id"] == assignment["lineage"]["duo_selection_id"]
        and binding["duo_selection_sha256"] == assignment["lineage"]["duo_selection_sha256"]
        and binding["mapping"] == assignment_mapping
        and derivation_report.get("p_index_assignment") == binding
        and derivation_report["contract_id"] == contract["contract_id"]
        and derivation_report["contract_sha256"] == contract["contract_sha256"]
    )
    source_hashes_exact = (
        hashlib.sha256(construction_payload).hexdigest() == binding["construction_map_sha256"]
        and len(construction_payload) == binding["construction_map_bytes"]
        and hashlib.sha256(instance_payload).hexdigest()
        == contract["source_file_sha256s"]["instance"]
        and len(instance_payload) == contract["source_file_bytes"]["instance"]
        and construction_codec["resolution"] == contract["resolution"]
        and instance_codec["resolution"] == contract["resolution"]
    )
    remapped = np.zeros_like(construction, dtype=np.uint16)
    for row in binding["mapping"]:
        remapped[construction == row["source_instance_id"]] = row["instance_id"]
    source_ids = {int(value) for value in np.unique(construction)} - {0}
    expected_source_ids = {row["source_instance_id"] for row in binding["mapping"]}
    remap_exact = (
        source_hashes_exact
        and source_ids == expected_source_ids
        and np.array_equal(remapped, instance)
    )

    target_masks: list[np.ndarray] = []
    other_masks: list[np.ndarray] = []
    package_hash_failures = 0
    shared_rgb_failures = 0
    package_identity_exact = True
    package_records = {row["p_index"]: row for row in derivation_report["packages"]}
    expected_indices = [owner["p_index"] for owner in contract["owners"]]
    if list(package_records) != expected_indices:
        package_identity_exact = False
    for owner in contract["owners"]:
        p_index = owner["p_index"]
        record = package_records.get(p_index)
        if record is None:
            package_identity_exact = False
            target_masks.append(np.zeros(expected_shape, dtype=bool))
            other_masks.append(np.zeros(expected_shape, dtype=bool))
            continue
        package_root = root / record["relative_root"]
        try:
            target = _binary_mask(package_root / "full_body.png", expected_shape)
            other = _binary_mask(package_root / "other_person.png", expected_shape)
            if (
                record["instance_id"] != owner["instance_id"]
                or record["package_id"] == ""
                or record["relative_root"] != f"packages/{p_index}"
            ):
                package_identity_exact = False
            for name, expected_sha256 in record["file_hashes"].items():
                path = package_root / name
                if not path.is_file() or _file_sha(path) != expected_sha256:
                    package_hash_failures += 1
            if _file_sha(package_root / "source_rgb.png") != contract["source_file_sha256s"]["rgb"]:
                shared_rgb_failures += 1
            target_masks.append(target)
            other_masks.append(other)
        except (OSError, ValueError, UnidentifiedImageError):
            package_identity_exact = False
            target_masks.append(np.zeros(expected_shape, dtype=bool))
            other_masks.append(np.zeros(expected_shape, dtype=bool))
            package_hash_failures += 1

    targets = np.stack(target_masks)
    visible = instance > 0
    target_sum = targets.sum(axis=0)
    duplicate_pixels = int(np.count_nonzero(target_sum > 1))
    missing_pixels = int(np.count_nonzero(visible & (target_sum == 0)))
    extra_pixels = int(np.count_nonzero(~visible & (target_sum > 0)))
    identity_bleed_pixels = 0
    complement_mismatch_pixels = 0
    nonempty = True
    for index, owner in enumerate(contract["owners"]):
        expected_target = instance == owner["instance_id"]
        identity_bleed_pixels += int(np.count_nonzero(targets[index] != expected_target))
        complement_mismatch_pixels += int(
            np.count_nonzero(other_masks[index] != (visible & ~targets[index]))
        )
        nonempty = nonempty and bool(targets[index].any())
    grouping_exact = (
        derivation_report["scene_id"] == contract["scene_id"]
        and derivation_report["image_id"] == contract["image_id"]
        and derivation_report["scene_family_id"] == contract["scene_family_id"]
        and derivation_report["summary"]["package_count"] == len(contract["owners"])
        and package_identity_exact
    )
    checks = {
        "assignment_lineage_exact": lineage_exact,
        "construction_instance_remap_exact": remap_exact,
        "target_owner_identity_exact": identity_bleed_pixels == 0 and nonempty,
        "target_ownership_exclusive": duplicate_pixels == 0,
        "target_ownership_complete": missing_pixels == 0 and extra_pixels == 0,
        "target_other_complements_exact": complement_mismatch_pixels == 0,
        "package_hashes_and_shared_rgb_exact": package_hash_failures == 0
        and shared_rgb_failures == 0,
        "scene_image_family_grouping_exact": grouping_exact,
    }
    metrics = {
        "person_count": len(contract["owners"]),
        "visible_person_pixels": int(np.count_nonzero(visible)),
        "duplicate_ownership_pixels": duplicate_pixels,
        "missing_ownership_pixels": missing_pixels,
        "extra_ownership_pixels": extra_pixels,
        "identity_bleed_pixels": identity_bleed_pixels,
        "complement_mismatch_pixels": complement_mismatch_pixels,
        "package_hash_failures": package_hash_failures,
        "shared_rgb_failures": shared_rgb_failures,
    }
    results = [
        _result(validator_id, name, checks[name], metrics) for validator_id, name in VALIDATORS
    ]
    passed = all(row["status"] == "pass" for row in results)
    content = {
        "policy_version": policy["policy_version"],
        "policy_sha256": _canonical_sha(policy),
        "validator_set_version": policy["validator_set_version"],
        "scene_id": contract["scene_id"],
        "image_id": contract["image_id"],
        "scene_family_id": contract["scene_family_id"],
        "contract_id": contract["contract_id"],
        "contract_sha256": contract["contract_sha256"],
        "derivation_report_id": derivation_report["report_id"],
        "derivation_report_sha256": derivation_report["report_sha256"],
        "assignment_id": assignment["assignment_id"],
        "assignment_sha256": assignment["assignment_sha256"],
        "source_sha256s": {
            "construction": hashlib.sha256(construction_payload).hexdigest(),
            "instance": hashlib.sha256(instance_payload).hexdigest(),
            "derived_scene_tree": before,
        },
        "results": results,
        "metrics": metrics,
        "summary": {
            "passed": passed,
            "acceptance_eligible": passed,
            "required_count": len(VALIDATORS),
            "passed_count": sum(row["status"] == "pass" for row in results),
            "failed_count": sum(row["status"] == "fail" for row in results),
        },
    }
    digest = _canonical_sha(content)
    report = {
        "schema_version": "1.0.0",
        "report_id": f"dmiv_{digest[:24]}",
        "report_sha256": digest,
        **content,
    }
    require_valid_document(report, "daz_multi_person_identity_report")
    if _tree_digest(root) != before:
        raise MultiPersonIdentityValidationError("multi_identity_source_mutated", str(root))
    return report


def validate_multi_person_identity_report(report: Mapping[str, Any]) -> None:
    require_valid_document(report, "daz_multi_person_identity_report")
    _verify_hashed_document(report, "report_id", "report_sha256", "dmiv")
    results = report["results"]
    expected_ids = [row[0] for row in VALIDATORS]
    passed_count = sum(row["status"] == "pass" for row in results)
    failed_count = sum(row["status"] == "fail" for row in results)
    passed = failed_count == 0 and passed_count == len(VALIDATORS)
    if (
        [row["validator_id"] for row in results] != expected_ids
        or len({row["name"] for row in results}) != len(VALIDATORS)
        or report["summary"]
        != {
            "passed": passed,
            "acceptance_eligible": passed,
            "required_count": len(VALIDATORS),
            "passed_count": passed_count,
            "failed_count": failed_count,
        }
    ):
        raise MultiPersonIdentityValidationError(
            "multi_identity_report_summary_invalid", report["report_id"]
        )


def publish_multi_person_identity_report(
    report: Mapping[str, Any], output_root: Path
) -> tuple[Path, bool]:
    validate_multi_person_identity_report(report)
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{report['report_id']}.json"
    payload = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise MultiPersonIdentityValidationError(
                "multi_identity_publication_conflict", str(target)
            )
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


def _result(
    validator_id: str, name: str, passed: bool, metrics: Mapping[str, int]
) -> dict[str, Any]:
    relevant = {
        key: value
        for key, value in metrics.items()
        if key
        in {
            "duplicate_ownership_pixels",
            "missing_ownership_pixels",
            "extra_ownership_pixels",
            "identity_bleed_pixels",
            "complement_mismatch_pixels",
            "package_hash_failures",
            "shared_rgb_failures",
        }
    }
    return {
        "validator_id": validator_id,
        "validator_version": "1.0.0",
        "name": name,
        "status": "pass" if passed else "fail",
        "severity": "BLOCK",
        "reason_code": "VERIFIED" if passed else f"MULTI_{name.upper()}",
        "observed": relevant,
        "retryability": "none",
    }


def _binary_mask(path: Path, shape: tuple[int, int]) -> np.ndarray:
    with Image.open(path) as image:
        image.load()
        array = np.asarray(image)
        if image.format != "PNG" or image.mode != "L" or array.shape != shape:
            raise ValueError(f"binary codec mismatch: {path}")
    values = {int(value) for value in np.unique(array)}
    if not values <= {0, 255}:
        raise ValueError(f"binary values invalid: {path}")
    return array == 255


def _tree_digest(root: Path) -> str:
    rows = [
        {"path": path.relative_to(root).as_posix(), "sha256": _file_sha(path)}
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]
    return _canonical_sha(rows)


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_hashed_document(
    document: Mapping[str, Any], id_field: str, hash_field: str, prefix: str
) -> None:
    content = {
        key: value
        for key, value in document.items()
        if key not in {"schema_version", id_field, hash_field}
    }
    digest = _canonical_sha(content)
    if document[hash_field] != digest or document[id_field] != f"{prefix}_{digest[:24]}":
        raise MultiPersonIdentityValidationError(
            "multi_identity_document_hash_invalid", str(document.get(id_field))
        )


def _canonical_sha(value: Any) -> str:
    try:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MultiPersonIdentityValidationError(
            "multi_identity_noncanonical_value", str(exc)
        ) from exc
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "MultiPersonIdentityValidationError",
    "evaluate_multi_person_identity",
    "load_multi_person_identity_policy",
    "publish_multi_person_identity_report",
    "validate_multi_person_identity_policy",
    "validate_multi_person_identity_report",
]
