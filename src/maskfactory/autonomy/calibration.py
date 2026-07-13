"""Statistical certificates for label/context-specific autonomous mask acceptance."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import NormalDist
from typing import Any, Mapping

import yaml


class AutonomyCalibrationError(RuntimeError):
    """Audit evidence cannot support an autonomous-acceptance decision."""


def build_autonomy_pipeline_fingerprint(
    gate_fingerprint: str,
    *,
    components: Mapping[str, Path],
) -> str:
    """Hash every code/config/model identity input that scopes an autonomy certificate."""
    if not isinstance(gate_fingerprint, str) or not gate_fingerprint.strip():
        raise AutonomyCalibrationError("autonomy gate fingerprint is empty")
    if not components:
        raise AutonomyCalibrationError("autonomy pipeline fingerprint has no components")
    records: list[dict[str, str]] = []
    for name, raw_path in sorted(components.items()):
        if not isinstance(name, str) or not name.strip():
            raise AutonomyCalibrationError("autonomy fingerprint component name is empty")
        path = Path(raw_path)
        if path.is_file():
            records.append({"name": name, "sha256": _sha256_file(path)})
            continue
        if not path.is_dir():
            raise AutonomyCalibrationError(
                f"autonomy fingerprint component is missing: {name}={path}"
            )
        files = [
            candidate
            for candidate in sorted(path.rglob("*"))
            if candidate.is_file()
            and "__pycache__" not in candidate.parts
            and candidate.suffix not in {".pyc", ".pyo"}
        ]
        if not files:
            raise AutonomyCalibrationError(
                f"autonomy fingerprint component directory is empty: {name}={path}"
            )
        records.extend(
            {
                "name": f"{name}/{candidate.relative_to(path).as_posix()}",
                "sha256": _sha256_file(candidate),
            }
            for candidate in files
        )
    payload = {
        "schema_version": "1.0.0",
        "gate_fingerprint": gate_fingerprint,
        "components": records,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def load_autonomy_config(path: Path = Path("configs/autonomous_masks.yaml")) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or set(document) != {
        "schema_version",
        "enabled",
        "mode",
        "tournament",
        "calibration",
        "operations",
        "retraining",
    }:
        raise AutonomyCalibrationError("autonomy config has the wrong top-level contract")
    if document["schema_version"] != "1.0.0" or document["enabled"] is not True:
        raise AutonomyCalibrationError("autonomy config must be enabled schema 1.0.0")
    if document["mode"] != "calibrated_progressive_autonomy":
        raise AutonomyCalibrationError("autonomy mode is invalid")
    weights = document["tournament"]["weights"]
    if abs(sum(float(value) for value in weights.values()) - 1.0) > 1e-9:
        raise AutonomyCalibrationError("autonomy tournament weights must sum to one")
    calibration = document["calibration"]
    if not 0.95 <= float(calibration["confidence_level"]) < 1:
        raise AutonomyCalibrationError("autonomy confidence must be at least 95 percent")
    operations = document["operations"]
    if (
        operations["calibrated_status_is_human_gold"] is not False
        or operations["holdout_may_use_machine_labels"] is not False
        or float(operations["pseudo_label_loss_weight"])
        >= float(operations["human_gold_loss_weight"])
    ):
        raise AutonomyCalibrationError("autonomy truth/training authority boundary is invalid")
    retraining = document["retraining"]
    if (
        int(retraining["minimum_new_human_corrections"]) < 1
        or int(retraining["minimum_audit_failures"]) < 1
        or retraining["require_frozen_human_holdout_evaluation"] is not True
    ):
        raise AutonomyCalibrationError("autonomy retraining boundary is invalid")
    return document


def build_autonomy_certificate(
    audit_path: Path,
    *,
    label: str,
    context: str,
    pipeline_fingerprint: str,
    policy: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a hash-bound certificate from frozen human truth for autoaccepted cases."""
    raw = Path(audit_path).read_bytes()
    document = json.loads(raw)
    if set(document) != {"schema_version", "frozen", "image_disjoint", "records"}:
        raise AutonomyCalibrationError("autonomy audit corpus has the wrong top-level shape")
    if document["schema_version"] != "1.0.0" or document["frozen"] is not True:
        raise AutonomyCalibrationError("autonomy audit corpus must be schema 1.0.0 and frozen")
    if policy["require_image_disjoint_holdout"] is True and document["image_disjoint"] is not True:
        raise AutonomyCalibrationError("autonomy audit corpus is not image-disjoint")
    records = [
        record
        for record in document["records"]
        if record.get("label") == label
        and record.get("context") == context
        and record.get("machine_accepted") is True
    ]
    required = {
        "record_id",
        "image_id",
        "label",
        "context",
        "machine_accepted",
        "human_defect",
        "serious_defect",
        "pipeline_fingerprint",
    }
    if any(not isinstance(record, dict) or set(record) != required for record in records):
        raise AutonomyCalibrationError("autonomy audit record has the wrong shape")
    if len({record["record_id"] for record in records}) != len(records):
        raise AutonomyCalibrationError("autonomy audit record IDs are not unique")
    if len({record["image_id"] for record in records}) != len(records):
        raise AutonomyCalibrationError("autonomy audit images are not disjoint")
    if policy["require_exact_pipeline_fingerprint"] is True and any(
        record["pipeline_fingerprint"] != pipeline_fingerprint for record in records
    ):
        raise AutonomyCalibrationError("autonomy audit pipeline fingerprint mismatch")
    sample_count = len(records)
    false_accepts = sum(record["human_defect"] is True for record in records)
    serious_false_accepts = sum(record["serious_defect"] is True for record in records)
    confidence = float(policy["confidence_level"])
    false_upper = _wilson_upper(false_accepts, sample_count, confidence)
    serious_upper = _wilson_upper(serious_false_accepts, sample_count, confidence)
    failures = []
    if sample_count < int(policy["minimum_autoaccepted_audits_per_label_context"]):
        failures.append("insufficient_autoaccepted_audits")
    if false_upper > float(policy["maximum_false_accept_upper_bound"]):
        failures.append("false_accept_upper_bound_exceeded")
    if serious_upper > float(policy["maximum_serious_false_accept_upper_bound"]):
        failures.append("serious_false_accept_upper_bound_exceeded")
    issued = (now or datetime.now(UTC)).astimezone(UTC)
    expires = issued + timedelta(days=int(policy["maximum_certificate_age_days"]))
    certificate = {
        "schema_version": "1.0.0",
        "label": label,
        "context": context,
        "pipeline_fingerprint": pipeline_fingerprint,
        "audit_sha256": hashlib.sha256(raw).hexdigest(),
        "sample_count": sample_count,
        "false_accept_count": false_accepts,
        "serious_false_accept_count": serious_false_accepts,
        "confidence_level": confidence,
        "false_accept_upper_bound": false_upper,
        "serious_false_accept_upper_bound": serious_upper,
        "issued_at": issued.isoformat().replace("+00:00", "Z"),
        "expires_at": expires.isoformat().replace("+00:00", "Z"),
        "passed": not failures,
        "failures": failures,
    }
    certificate["sha256"] = hashlib.sha256(
        json.dumps(certificate, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return certificate


def verify_autonomy_certificate(
    certificate: dict[str, Any] | None,
    *,
    label: str,
    context: str,
    pipeline_fingerprint: str,
    now: datetime | None = None,
) -> tuple[bool, str]:
    if not certificate or certificate.get("passed") is not True:
        return False, "certificate_absent_or_failed"
    claimed = certificate.get("sha256")
    payload = {key: value for key, value in certificate.items() if key != "sha256"}
    actual = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if claimed != actual:
        return False, "certificate_hash_mismatch"
    if (
        certificate.get("label") != label
        or certificate.get("context") != context
        or certificate.get("pipeline_fingerprint") != pipeline_fingerprint
    ):
        return False, "certificate_scope_mismatch"
    current = (now or datetime.now(UTC)).astimezone(UTC)
    expires = datetime.fromisoformat(str(certificate["expires_at"]).replace("Z", "+00:00"))
    if current >= expires:
        return False, "certificate_expired"
    return True, "certificate_valid"


def _wilson_upper(defects: int, total: int, confidence: float) -> float:
    if total <= 0 or defects < 0 or defects > total or not 0.5 < confidence < 1:
        return 1.0
    z = NormalDist().inv_cdf(confidence)
    rate = defects / total
    denominator = 1 + z * z / total
    center = rate + z * z / (2 * total)
    radius = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total))
    return min(1.0, (center + radius) / denominator)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "AutonomyCalibrationError",
    "build_autonomy_certificate",
    "build_autonomy_pipeline_fingerprint",
    "load_autonomy_config",
    "verify_autonomy_certificate",
]
