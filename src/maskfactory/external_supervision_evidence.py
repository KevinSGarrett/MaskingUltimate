"""Hash-bound evidence bundles for external-supervision qualification gates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

CANONICAL_REQUIRED_GATES_BY_SOURCE: dict[str, tuple[str, ...]] = {
    "celebamask_hq": (
        "official_license_recorded",
        "deterministic_remap_tested",
        "source_hash_manifested",
        "visual_alignment_qa_passed",
        "split_dedup_passed",
    ),
    "lapa": (
        "official_license_recorded",
        "deterministic_remap_tested",
        "source_hash_manifested",
        "visual_alignment_qa_passed",
        "split_dedup_passed",
    ),
    "lv_mhp_v1": (
        "official_license_recorded",
        "deterministic_remap_tested",
        "source_hash_manifested",
        "visual_alignment_qa_passed",
        "instance_identity_validated",
        "split_dedup_passed",
    ),
}

GATE_ARTIFACT_TYPES: dict[str, str] = {
    "official_license_recorded": "external_supervision_license_evidence",
    "deterministic_remap_tested": "external_supervision_remap_evidence",
    "source_hash_manifested": "external_supervision_source_hash_manifest",
    "visual_alignment_qa_passed": "external_supervision_alignment_evidence",
    "instance_identity_validated": "external_supervision_identity_evidence",
    "split_dedup_passed": "external_supervision_split_dedup_evidence",
}


@dataclass(frozen=True)
class EvidenceBundleVerification:
    """Result of validating one source's complete qualification evidence bundle."""

    source: str
    passed: bool
    completed_gates: tuple[str, ...]
    bundle_sha256: str | None
    evidence_tokens: tuple[str, ...]


def canonical_json_sha256(value: Mapping[str, Any]) -> str:
    """Return SHA-256 of compact, key-sorted UTF-8 JSON."""

    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def seal_payload(value: Mapping[str, Any]) -> str:
    """Return the deterministic self-seal for a mapping, excluding its seal field."""

    return canonical_json_sha256({key: item for key, item in value.items() if key != "seal_sha256"})


def verify_qualification_evidence_bundle(
    bundle: Mapping[str, Any],
    *,
    source: str,
    project_root: Path,
) -> EvidenceBundleVerification:
    """Verify a sealed bundle and every gate artifact without trusting path strings."""

    tokens: list[str] = []
    expected_gates = CANONICAL_REQUIRED_GATES_BY_SOURCE.get(source)
    if expected_gates is None:
        return EvidenceBundleVerification(
            source, False, (), None, ("canonical_gate_contract_missing",)
        )
    if bundle.get("schema_version") != "1.0.0" or bundle.get("artifact_type") != (
        "external_supervision_qualification_evidence_bundle"
    ):
        tokens.append("evidence_bundle_contract_invalid")
    if bundle.get("source") != source:
        tokens.append("evidence_bundle_source_mismatch")
    if bundle.get("seal_sha256") != seal_payload(bundle):
        tokens.append("evidence_bundle_seal_invalid")

    raw_records = bundle.get("gates")
    if not isinstance(raw_records, list):
        tokens.append("evidence_bundle_gates_malformed")
        return EvidenceBundleVerification(source, False, (), None, tuple(tokens))
    records: dict[str, Mapping[str, Any]] = {}
    for record in raw_records:
        if not isinstance(record, Mapping):
            tokens.append("evidence_bundle_gates_malformed")
            continue
        gate = record.get("gate")
        if not isinstance(gate, str) or gate in records:
            tokens.append("evidence_bundle_gates_malformed")
            continue
        records[gate] = record
    if set(records) != set(expected_gates):
        tokens.append("canonical_gate_set_mismatch")

    root = Path(project_root).resolve(strict=True)
    completed: list[str] = []
    for gate in expected_gates:
        record = records.get(gate)
        if record is None:
            continue
        if _verify_gate_record(record, source=source, gate=gate, root=root, tokens=tokens):
            completed.append(gate)

    bundle_sha = canonical_json_sha256(bundle)
    passed = not tokens and tuple(completed) == expected_gates
    return EvidenceBundleVerification(
        source=source,
        passed=passed,
        completed_gates=tuple(completed),
        bundle_sha256=bundle_sha,
        evidence_tokens=tuple(tokens),
    )


def _verify_gate_record(
    record: Mapping[str, Any],
    *,
    source: str,
    gate: str,
    root: Path,
    tokens: list[str],
) -> bool:
    expected_type = GATE_ARTIFACT_TYPES[gate]
    if record.get("artifact_type") != expected_type:
        tokens.append(f"gate_artifact_type_mismatch:{gate}")
        return False
    raw_path = record.get("artifact_path")
    expected_hash = record.get("artifact_sha256")
    if not isinstance(raw_path, str) or not raw_path or not _is_sha256(expected_hash):
        tokens.append(f"gate_artifact_binding_malformed:{gate}")
        return False
    relative = Path(raw_path)
    if relative.is_absolute():
        tokens.append(f"gate_artifact_path_unsafe:{gate}")
        return False
    try:
        artifact_path = (root / relative).resolve(strict=True)
        artifact_path.relative_to(root)
    except (FileNotFoundError, OSError, ValueError):
        tokens.append(f"gate_artifact_path_unsafe:{gate}")
        return False
    if not artifact_path.is_file():
        tokens.append(f"gate_artifact_missing:{gate}")
        return False
    raw_bytes = artifact_path.read_bytes()
    if hashlib.sha256(raw_bytes).hexdigest() != expected_hash:
        tokens.append(f"gate_artifact_hash_mismatch:{gate}")
        return False
    try:
        artifact = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        tokens.append(f"gate_artifact_json_invalid:{gate}")
        return False
    if not isinstance(artifact, Mapping):
        tokens.append(f"gate_artifact_contract_invalid:{gate}")
        return False
    if (
        artifact.get("schema_version") != "1.0.0"
        or artifact.get("artifact_type") != expected_type
        or artifact.get("source") != source
        or artifact.get("gate") != gate
        or artifact.get("status") != "PASS"
    ):
        tokens.append(f"gate_artifact_contract_invalid:{gate}")
        return False
    if artifact.get("seal_sha256") != seal_payload(artifact):
        tokens.append(f"gate_artifact_seal_invalid:{gate}")
        return False
    return True


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return value == value.lower()


__all__ = [
    "CANONICAL_REQUIRED_GATES_BY_SOURCE",
    "EvidenceBundleVerification",
    "GATE_ARTIFACT_TYPES",
    "canonical_json_sha256",
    "seal_payload",
    "verify_qualification_evidence_bundle",
]
