"""Certificate-bound complete-map hard veto aggregation.

The existing QA engines execute the pixel and package checks.  This module
turns their typed :class:`QcResult` values into one canonical, hash-bound
report and independently verifies certificate subject, owner, visibility,
and transform bindings.  A critic score is retained for audit only and can
never change a failed deterministic category into a pass.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

from maskfactory.qa.checks import QcResult
from maskfactory.validation import canonical_json_bytes

_BASE_QC = {
    "format": ("QC-002", "QC-003"),
    "ontology": ("QC-004",),
    "dimensions": ("QC-001",),
    "visibility": ("QC-016",),
    "exclusivity": ("QC-011",),
    "protected_regions": ("QC-013",),
    "left_right": ("QC-014",),
    "transform_integrity": ("QC-018",),
}
_MULTI_QC = {
    "instance_ownership": ("QC-035",),
    "cross_instance_bleed": ("QC-036",),
    "contact": ("QC-037",),
}
_CERTIFICATE_GATE_CATEGORIES = {
    "schema_conformance": ("format", "dimensions", "visibility", "exclusivity"),
    "ontology_label": ("ontology",),
    "left_right_semantics": ("left_right",),
    "subject_assignment": ("subject_assignment",),
    "ownership_isolation": ("exclusivity", "instance_ownership", "cross_instance_bleed"),
    "contact_occlusion": ("contact",),
    "protected_region": ("protected_regions",),
    "transform_replay": ("transform_integrity",),
    "output_identity": ("format", "dimensions", "visibility", "subject_assignment"),
}


class CompleteMapHardVetoError(ValueError):
    """Raised when complete-map evidence is incomplete or internally invalid."""


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _qc_category(
    category: str,
    required_ids: tuple[str, ...],
    by_id: Mapping[str, QcResult],
) -> dict[str, Any]:
    missing = [qc_id for qc_id in required_ids if qc_id not in by_id]
    checks = [by_id[qc_id] for qc_id in required_ids if qc_id in by_id]
    failed = [check.qc_id for check in checks if not check.passed]
    record = {
        "category": category,
        "status": "pass" if not missing and not failed else "fail",
        "required_qc_ids": list(required_ids),
        "missing_qc_ids": missing,
        "failed_qc_ids": failed,
        "checks": [
            {
                "qc_id": check.qc_id,
                "name": check.name,
                "passed": check.passed,
                "severity": check.severity,
                "detail": check.detail,
            }
            for check in checks
        ],
    }
    record["evidence_sha256"] = _sha(record)
    return record


def _binding_category(category: str, *, passed: bool, details: Mapping[str, Any]) -> dict[str, Any]:
    record = {
        "category": category,
        "status": "pass" if passed else "fail",
        "required_qc_ids": [],
        "missing_qc_ids": [],
        "failed_qc_ids": [] if passed else [f"BINDING:{category}"],
        "checks": [
            {
                "qc_id": f"BINDING:{category}",
                "name": category,
                "passed": passed,
                "severity": "BLOCK",
                "detail": dict(details),
            }
        ],
    }
    record["evidence_sha256"] = _sha(record)
    return record


def _combine_qc_and_binding_category(
    qc_record: Mapping[str, Any], *, passed: bool, details: Mapping[str, Any]
) -> dict[str, Any]:
    category = str(qc_record["category"])
    qc_failed = qc_record.get("status") != "pass"
    record = {
        "category": category,
        "status": "pass" if passed and not qc_failed else "fail",
        "required_qc_ids": list(qc_record.get("required_qc_ids", ())),
        "missing_qc_ids": list(qc_record.get("missing_qc_ids", ())),
        "failed_qc_ids": [
            *qc_record.get("failed_qc_ids", ()),
            *(() if passed else (f"BINDING:{category}",)),
        ],
        "checks": [
            *qc_record.get("checks", ()),
            {
                "qc_id": f"BINDING:{category}",
                "name": f"{category}_binding",
                "passed": passed,
                "severity": "BLOCK",
                "detail": dict(details),
            },
        ],
    }
    record["evidence_sha256"] = _sha(record)
    return record


def _not_applicable_category(category: str, reason: str) -> dict[str, Any]:
    record = {
        "category": category,
        "status": "not_applicable",
        "required_qc_ids": [],
        "missing_qc_ids": [],
        "failed_qc_ids": [],
        "checks": [],
        "reason": reason,
    }
    record["evidence_sha256"] = _sha(record)
    return record


def _subject_assignment(
    subject_binding: Mapping[str, Any], artifacts: Sequence[Mapping[str, Any]]
) -> tuple[bool, dict[str, Any]]:
    expected = {
        "entity_id": subject_binding.get("character_id"),
        "scene_instance_id": subject_binding.get("scene_instance_id"),
        "canonical_person_id": subject_binding.get("canonical_person_id"),
        "person_index": subject_binding.get("person_index"),
    }
    failures: list[dict[str, Any]] = []
    for artifact in artifacts:
        observed = {key: artifact.get(key) for key in expected}
        if artifact.get("owner_kind") != "character_instance" or observed != expected:
            failures.append(
                {
                    "artifact_id": artifact.get("artifact_id"),
                    "owner_kind": artifact.get("owner_kind"),
                    "expected": expected,
                    "observed": observed,
                }
            )
    return not failures and bool(artifacts), {
        "subject_binding_sha256": _sha(subject_binding),
        "artifact_owner_binding_sha256": _sha(
            [
                {
                    "artifact_id": artifact.get("artifact_id"),
                    "owner_kind": artifact.get("owner_kind"),
                    **{key: artifact.get(key) for key in expected},
                }
                for artifact in artifacts
            ]
        ),
        "failures": failures,
    }


def _artifact_visibility(artifacts: Sequence[Mapping[str, Any]]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for artifact in artifacts:
        summary = artifact.get("content_summary")
        visibility = artifact.get("visibility")
        empty_semantics = artifact.get("empty_semantics")
        is_empty = summary.get("is_empty") if isinstance(summary, Mapping) else None
        if (
            visibility not in {"visible", "occluded_inferred", "complete_map"}
            or not isinstance(is_empty, bool)
            or (is_empty and empty_semantics == "forbidden")
            or (not is_empty and empty_semantics == "allowed_explicit_absence")
        ):
            failures.append(str(artifact.get("artifact_id")))
    return not failures, failures


def _transform_binding(
    source_binding: Mapping[str, Any],
    coordinate_binding: Mapping[str, Any],
    artifacts: Sequence[Mapping[str, Any]],
) -> tuple[bool, dict[str, Any]]:
    failures: list[str] = []
    if coordinate_binding.get("source_width") != source_binding.get(
        "width"
    ) or coordinate_binding.get("source_height") != source_binding.get("height"):
        failures.append("source_dimensions")
    if coordinate_binding.get("roundtrip_checked") is not True:
        failures.append("roundtrip_not_checked")
    if coordinate_binding.get("roundtrip_passed") is not True:
        failures.append("roundtrip_failed")
    for artifact in artifacts:
        if (
            artifact.get("width") != coordinate_binding.get("output_width")
            or artifact.get("height") != coordinate_binding.get("output_height")
            or artifact.get("coordinate_space") != coordinate_binding.get("output_coordinate_space")
            or artifact.get("transform_chain_sha256")
            != coordinate_binding.get("transform_chain_sha256")
        ):
            failures.append(f"artifact:{artifact.get('artifact_id')}")
    return not failures, {
        "coordinate_binding_sha256": _sha(coordinate_binding),
        "source_binding_sha256": _sha(source_binding),
        "failures": failures,
    }


def build_complete_map_hard_veto_report(
    qc_results: Iterable[QcResult],
    *,
    instance_context: str,
    source_binding: Mapping[str, Any],
    subject_binding: Mapping[str, Any],
    coordinate_binding: Mapping[str, Any],
    artifacts: Sequence[Mapping[str, Any]],
    critic_confidence: float,
    evaluator_id: str,
    evaluator_sha256: str,
) -> dict[str, Any]:
    """Build the canonical complete-map report from executed QA results and bindings."""
    if instance_context not in {"solo", "duo", "small_group"}:
        raise CompleteMapHardVetoError("invalid instance context")
    if not 0.0 <= critic_confidence <= 1.0:
        raise CompleteMapHardVetoError("critic confidence must be in 0..1")
    if not evaluator_id or len(evaluator_sha256) != 64:
        raise CompleteMapHardVetoError("evaluator identity is incomplete")
    results = tuple(qc_results)
    counts = Counter(result.qc_id for result in results)
    duplicates = sorted(qc_id for qc_id, count in counts.items() if count != 1)
    if duplicates:
        raise CompleteMapHardVetoError(f"duplicate QA result IDs: {duplicates}")
    by_id = {result.qc_id: result for result in results}
    categories = {
        category: _qc_category(category, required_ids, by_id)
        for category, required_ids in _BASE_QC.items()
    }

    visibility_passed, visibility_failures = _artifact_visibility(artifacts)
    if not visibility_passed:
        categories["visibility"] = _binding_category(
            "visibility",
            passed=False,
            details={"artifact_visibility_failures": visibility_failures},
        )
    subject_passed, subject_details = _subject_assignment(subject_binding, artifacts)
    categories["subject_assignment"] = _binding_category(
        "subject_assignment", passed=subject_passed, details=subject_details
    )
    transform_passed, transform_details = _transform_binding(
        source_binding, coordinate_binding, artifacts
    )
    transform_qc = categories["transform_integrity"]
    transform_qc_passed = transform_qc["status"] == "pass"
    categories["transform_integrity"] = _combine_qc_and_binding_category(
        transform_qc,
        passed=transform_passed and transform_qc_passed,
        details={
            **transform_details,
            "qc_018_passed": transform_qc_passed,
            "qc_018_evidence_sha256": transform_qc["evidence_sha256"],
        },
    )

    if instance_context == "solo":
        categories["instance_ownership"] = _binding_category(
            "instance_ownership", passed=subject_passed, details=subject_details
        )
        categories["cross_instance_bleed"] = _not_applicable_category(
            "cross_instance_bleed", "solo instance context"
        )
        categories["contact"] = _not_applicable_category("contact", "solo instance context")
    else:
        categories.update(
            {
                category: _qc_category(category, required_ids, by_id)
                for category, required_ids in _MULTI_QC.items()
            }
        )
        if not subject_passed:
            categories["instance_ownership"] = _binding_category(
                "instance_ownership", passed=False, details=subject_details
            )

    ordered = [categories[key] for key in sorted(categories)]
    blocking = [row["category"] for row in ordered if row["status"] == "fail"]
    report = {
        "report_kind": "maskfactory_complete_map_hard_veto",
        "report_version": "1.0.0",
        "instance_context": instance_context,
        "evaluator_id": evaluator_id,
        "evaluator_sha256": evaluator_sha256,
        "source_binding_sha256": _sha(source_binding),
        "subject_binding_sha256": _sha(subject_binding),
        "coordinate_binding_sha256": _sha(coordinate_binding),
        "artifact_set_binding_sha256": _sha(list(artifacts)),
        "critic_confidence_observed": critic_confidence,
        "critic_can_override": False,
        "categories": ordered,
        "blocking_categories": blocking,
        "all_blocking_gates_passed": not blocking,
        "status": "pass" if not blocking else "fail",
    }
    gate_evidence: dict[str, str] = {}
    category_by_name = {row["category"]: row for row in ordered}
    for gate_id, names in _CERTIFICATE_GATE_CATEGORIES.items():
        gate_evidence[gate_id] = _sha([category_by_name[name] for name in names])
    gate_evidence["deterministic_quality"] = _sha(report)
    report["certificate_gate_evidence_sha256s"] = gate_evidence
    return report


def complete_map_hard_veto_report_sha256(report: Mapping[str, Any]) -> str:
    """Return the exact report digest used by the certificate QA binding."""
    return _sha(report)


def bind_complete_map_report(
    unsigned_certificate: Mapping[str, Any], report: Mapping[str, Any]
) -> dict[str, Any]:
    """Return a certificate body whose deterministic QA fields bind ``report``."""
    import copy

    document = copy.deepcopy(dict(unsigned_certificate))
    qa = document["qa_evidence"]
    qa["deterministic_report_sha256"] = complete_map_hard_veto_report_sha256(report)
    evidence = report.get("certificate_gate_evidence_sha256s", {})
    for gate in qa["gate_results"]:
        gate_id = gate.get("gate_id")
        if gate_id in evidence:
            gate["evidence_sha256"] = evidence[gate_id]
    return document


def validate_complete_map_report_binding(
    report: Mapping[str, Any],
    certificate: Mapping[str, Any],
    *,
    trusted_evaluators: Mapping[str, str],
) -> tuple[str, ...]:
    """Validate report integrity and its exact binding to a certificate candidate."""
    codes: list[str] = []
    if report.get("report_kind") != "maskfactory_complete_map_hard_veto":
        codes.append("complete_map_report_kind")
    if report.get("report_version") != "1.0.0":
        codes.append("complete_map_report_version")
    evaluator_id = report.get("evaluator_id")
    evaluator_sha256 = report.get("evaluator_sha256")
    if (
        not isinstance(evaluator_id, str)
        or trusted_evaluators.get(evaluator_id) != evaluator_sha256
    ):
        codes.append("complete_map_evaluator_untrusted")
    for field, value in (
        ("source_binding_sha256", certificate.get("source_binding", {})),
        ("subject_binding_sha256", certificate.get("subject_binding", {})),
        ("coordinate_binding_sha256", certificate.get("coordinate_binding", {})),
        ("artifact_set_binding_sha256", list(certificate.get("bound_artifacts", ()))),
    ):
        if report.get(field) != _sha(value):
            codes.append(f"complete_map_{field}")
    categories = report.get("categories")
    if not isinstance(categories, list):
        categories = []
        codes.append("complete_map_categories_missing")
    expected_names = {
        *_BASE_QC,
        *_MULTI_QC,
        "subject_assignment",
    }
    category_by_name = {row.get("category"): row for row in categories if isinstance(row, Mapping)}
    observed_names = set(category_by_name)
    if observed_names != expected_names:
        codes.append("complete_map_category_set")
    derived_blocking: list[str] = []
    for name, row in category_by_name.items():
        evidence_sha256 = row.get("evidence_sha256")
        unsigned_row = {key: value for key, value in row.items() if key != "evidence_sha256"}
        if evidence_sha256 != _sha(unsigned_row):
            codes.append(f"complete_map_category_hash:{name}")
        status = row.get("status")
        if status not in {"pass", "fail", "not_applicable"}:
            codes.append(f"complete_map_category_status:{name}")
            continue
        missing = row.get("missing_qc_ids")
        failed = row.get("failed_qc_ids")
        checks = row.get("checks")
        if (
            not isinstance(missing, list)
            or not isinstance(failed, list)
            or not isinstance(checks, list)
        ):
            codes.append(f"complete_map_category_shape:{name}")
            continue
        check_failed = any(
            not check.get("passed") for check in checks if isinstance(check, Mapping)
        )
        derived_status = "fail" if missing or failed or check_failed else "pass"
        if status == "not_applicable":
            if checks or missing or failed or not row.get("reason"):
                codes.append(f"complete_map_not_applicable_invalid:{name}")
        elif status != derived_status:
            codes.append(f"complete_map_category_outcome:{name}")
        if status == "fail":
            derived_blocking.append(str(name))
    for name, required_ids in _BASE_QC.items():
        row = category_by_name.get(name, {})
        observed_required = row.get("required_qc_ids")
        check_ids = {
            check.get("qc_id") for check in row.get("checks", ()) if isinstance(check, Mapping)
        }
        if observed_required != list(required_ids) or not set(required_ids).issubset(check_ids):
            codes.append(f"complete_map_required_qc:{name}")
    instance_context = report.get("instance_context")
    for name, required_ids in _MULTI_QC.items():
        row = category_by_name.get(name, {})
        if instance_context == "solo" and name in {"cross_instance_bleed", "contact"}:
            if row.get("status") != "not_applicable":
                codes.append(f"complete_map_solo_applicability:{name}")
            continue
        if instance_context == "solo" and name == "instance_ownership":
            if row.get("status") != "pass":
                codes.append("complete_map_solo_ownership")
            continue
        observed_required = row.get("required_qc_ids")
        check_ids = {
            check.get("qc_id") for check in row.get("checks", ()) if isinstance(check, Mapping)
        }
        if (
            observed_required != list(required_ids)
            or not set(required_ids).issubset(check_ids)
            or row.get("status") == "not_applicable"
        ):
            codes.append(f"complete_map_required_qc:{name}")
    derived_blocking.sort()
    if report.get("blocking_categories") != derived_blocking:
        codes.append("complete_map_blocker_derivation")
    derived_pass = not derived_blocking
    if report.get("status") != ("pass" if derived_pass else "fail"):
        codes.append("complete_map_status_derivation")
    if report.get("all_blocking_gates_passed") is not derived_pass:
        codes.append("complete_map_pass_derivation")
    if report.get("status") != "pass" or report.get("all_blocking_gates_passed") is not True:
        codes.append("complete_map_hard_veto_failed")
    if report.get("blocking_categories") != []:
        codes.append("complete_map_blockers_present")
    if report.get("critic_can_override") is not False:
        codes.append("complete_map_critic_override_enabled")
    route_scope = certificate.get("qualified_route_scope")
    if not isinstance(route_scope, Mapping) or report.get("instance_context") not in set(
        route_scope.get("contexts") or ()
    ):
        codes.append("complete_map_instance_context_scope")

    qa = certificate.get("qa_evidence")
    if not isinstance(qa, Mapping):
        return tuple(sorted(set((*codes, "complete_map_qa_binding_missing"))))
    if qa.get("deterministic_report_sha256") != complete_map_hard_veto_report_sha256(report):
        codes.append("complete_map_report_hash_mismatch")
    expected_evidence = report.get("certificate_gate_evidence_sha256s")
    if not isinstance(expected_evidence, Mapping):
        codes.append("complete_map_gate_evidence_missing")
    else:
        derived_gate_evidence = {
            gate_id: _sha([category_by_name[name] for name in names])
            for gate_id, names in _CERTIFICATE_GATE_CATEGORIES.items()
            if all(name in category_by_name for name in names)
        }
        core_report = {
            key: value
            for key, value in report.items()
            if key != "certificate_gate_evidence_sha256s"
        }
        derived_gate_evidence["deterministic_quality"] = _sha(core_report)
        if dict(expected_evidence) != derived_gate_evidence:
            codes.append("complete_map_gate_evidence_derivation")
        gate_rows = {
            row.get("gate_id"): row
            for row in qa.get("gate_results", ())
            if isinstance(row, Mapping)
        }
        for gate_id, evidence_sha256 in expected_evidence.items():
            if gate_rows.get(gate_id, {}).get("evidence_sha256") != evidence_sha256:
                codes.append(f"complete_map_gate_binding:{gate_id}")

    # Re-run the binding-only predicates against the candidate being signed.
    subject_passed, _ = _subject_assignment(
        certificate.get("subject_binding", {}), certificate.get("bound_artifacts", ())
    )
    transform_passed, transform_details = _transform_binding(
        certificate.get("source_binding", {}),
        certificate.get("coordinate_binding", {}),
        certificate.get("bound_artifacts", ()),
    )
    _, subject_details = _subject_assignment(
        certificate.get("subject_binding", {}), certificate.get("bound_artifacts", ())
    )
    subject_row = category_by_name.get("subject_assignment", {})
    subject_checks = subject_row.get("checks", ())
    subject_binding_check = next(
        (
            check
            for check in subject_checks
            if isinstance(check, Mapping) and check.get("qc_id") == "BINDING:subject_assignment"
        ),
        None,
    )
    subject_report_details = (
        subject_binding_check.get("detail") if isinstance(subject_binding_check, Mapping) else None
    )
    transform_row = category_by_name.get("transform_integrity", {})
    transform_checks = transform_row.get("checks", ())
    transform_binding_check = next(
        (
            check
            for check in transform_checks
            if isinstance(check, Mapping) and check.get("qc_id") == "BINDING:transform_integrity"
        ),
        None,
    )
    transform_report_details = (
        transform_binding_check.get("detail")
        if isinstance(transform_binding_check, Mapping)
        else None
    )
    if not isinstance(subject_report_details, Mapping) or any(
        subject_report_details.get(field) != subject_details.get(field)
        for field in ("subject_binding_sha256", "artifact_owner_binding_sha256")
    ):
        codes.append("complete_map_subject_report_binding")
    if not isinstance(transform_report_details, Mapping) or any(
        transform_report_details.get(field) != transform_details.get(field)
        for field in ("coordinate_binding_sha256", "source_binding_sha256")
    ):
        codes.append("complete_map_transform_report_binding")
    if not subject_passed:
        codes.append("complete_map_subject_binding_failed")
    if not transform_passed:
        codes.append("complete_map_transform_binding_failed")
    return tuple(sorted(set(codes)))


__all__ = [
    "CompleteMapHardVetoError",
    "bind_complete_map_report",
    "build_complete_map_hard_veto_report",
    "complete_map_hard_veto_report_sha256",
    "validate_complete_map_report_binding",
]
