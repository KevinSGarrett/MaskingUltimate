import copy
import hashlib
import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from maskfactory.external_supervision_evidence import (
    CANONICAL_REQUIRED_GATES_BY_SOURCE,
    GATE_ARTIFACT_TYPES,
    seal_payload,
)
from maskfactory.external_supervision_qualification import (
    verify_external_qualification_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "configs" / "maskedwarehouse_inventory.json"
PROVENANCE = ROOT / "configs" / "maskedwarehouse_provenance.yaml"
EVIDENCE_SCHEMA = (
    ROOT
    / "src"
    / "maskfactory"
    / "schemas"
    / "external_supervision_qualification_evidence.schema.json"
)


def _load_inventory() -> dict:
    return json.loads(INVENTORY.read_text(encoding="utf-8"))


def _load_provenance() -> dict:
    return yaml.safe_load(PROVENANCE.read_text(encoding="utf-8"))


def _sealed(value: dict) -> dict:
    value["seal_sha256"] = seal_payload(value)
    return value


def _evidence_bundle(tmp_path: Path, source: str) -> dict:
    records = []
    for gate in CANONICAL_REQUIRED_GATES_BY_SOURCE[source]:
        artifact_type = GATE_ARTIFACT_TYPES[gate]
        artifact = _sealed(
            {
                "schema_version": "1.0.0",
                "artifact_type": artifact_type,
                "source": source,
                "gate": gate,
                "status": "PASS",
            }
        )
        path = tmp_path / source / f"{gate}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(artifact, sort_keys=True).encode("utf-8")
        path.write_bytes(payload)
        records.append(
            {
                "gate": gate,
                "artifact_type": artifact_type,
                "artifact_path": path.relative_to(tmp_path).as_posix(),
                "artifact_sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return _sealed(
        {
            "schema_version": "1.0.0",
            "artifact_type": "external_supervision_qualification_evidence_bundle",
            "source": source,
            "gates": records,
        }
    )


def test_admission_is_deterministic_with_complete_gate_set(tmp_path: Path):
    provenance = _load_provenance()
    inventory = _load_inventory()

    bundle = _evidence_bundle(tmp_path, "lv_mhp_v1")
    decision_a = verify_external_qualification_evidence(
        provenance,
        inventory,
        source="lv_mhp_v1",
        evidence_bundle=bundle,
        project_root=tmp_path,
    )
    decision_b = verify_external_qualification_evidence(
        provenance,
        inventory,
        source="lv_mhp_v1",
        evidence_bundle=bundle,
        project_root=tmp_path,
    )

    assert decision_a == decision_b
    assert decision_a.admitted is True
    assert decision_a.unmet_gates == ()
    assert decision_a.evidence_tokens == ()


def test_evidence_bundle_schema_accepts_complete_fixture(tmp_path: Path):
    schema = json.loads(EVIDENCE_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_evidence_bundle(tmp_path, "lv_mhp_v1"))


def test_missing_gate_fails_closed_with_unmet_gate(tmp_path: Path):
    provenance = _load_provenance()
    inventory = _load_inventory()

    bundle = _evidence_bundle(tmp_path, "lapa")
    bundle["gates"] = [
        record for record in bundle["gates"] if record["gate"] != "split_dedup_passed"
    ]
    bundle["seal_sha256"] = seal_payload(bundle)
    decision = verify_external_qualification_evidence(
        provenance,
        inventory,
        source="lapa",
        evidence_bundle=bundle,
        project_root=tmp_path,
    )

    assert decision.legally_eligible is True
    assert decision.technically_qualified is False
    assert decision.admitted is False
    assert decision.unmet_gates == ("split_dedup_passed",)
    assert "canonical_gate_set_mismatch" in decision.evidence_tokens


def test_unknown_source_fails_closed():
    decision = verify_external_qualification_evidence(
        _load_provenance(),
        _load_inventory(),
        source="not_a_real_source",
    )

    assert decision.admitted is False
    assert "unknown_external_source" in decision.evidence_tokens


def test_registry_source_set_drift_fails_closed():
    provenance = _load_provenance()
    inventory = _load_inventory()

    inventory["sources"] = [source for source in inventory["sources"] if source["source"] != "lapa"]
    decision = verify_external_qualification_evidence(
        provenance,
        inventory,
        source="lv_mhp_v1",
    )

    assert decision.admitted is False
    assert "source_set_drift_detected" in decision.evidence_tokens


def test_authority_drift_fails_closed():
    provenance = copy.deepcopy(_load_provenance())
    inventory = _load_inventory()

    provenance["sources"]["celebamask_hq"]["training_admission"]["holdout_eligible"] = True
    required = set(provenance["sources"]["celebamask_hq"]["training_admission"]["required_gates"])
    decision = verify_external_qualification_evidence(
        provenance,
        inventory,
        source="celebamask_hq",
        completed_gates=required,
    )

    assert decision.admitted is False
    assert "holdout_authority_drift" in decision.evidence_tokens


def test_blocked_source_never_becomes_eligible():
    decision = verify_external_qualification_evidence(
        _load_provenance(),
        _load_inventory(),
        source="swimsuit_preview",
        completed_gates={"compatible_derivative_and_training_rights"},
    )

    assert decision.legally_eligible is False
    assert decision.admitted is False
    assert "blocked_by_registry_status" in decision.evidence_tokens


def test_unbound_gate_names_are_ignored_and_fail_closed():
    provenance = _load_provenance()
    required = set(provenance["sources"]["lapa"]["training_admission"]["required_gates"])
    decision = verify_external_qualification_evidence(
        provenance,
        _load_inventory(),
        source="lapa",
        completed_gates=required,
    )

    assert decision.admitted is False
    assert set(decision.unmet_gates) == required
    assert "unbound_completed_gates_ignored" in decision.evidence_tokens


def test_gate_artifact_hash_drift_fails_closed(tmp_path: Path):
    bundle = _evidence_bundle(tmp_path, "lapa")
    target = next(
        record for record in bundle["gates"] if record["gate"] == "source_hash_manifested"
    )
    (tmp_path / target["artifact_path"]).write_text("{}", encoding="utf-8")
    decision = verify_external_qualification_evidence(
        _load_provenance(),
        _load_inventory(),
        source="lapa",
        evidence_bundle=bundle,
        project_root=tmp_path,
    )

    assert decision.admitted is False
    assert decision.unmet_gates == ("source_hash_manifested",)
    assert "gate_artifact_hash_mismatch:source_hash_manifested" in decision.evidence_tokens


def test_bundle_cannot_escape_project_root(tmp_path: Path):
    bundle = _evidence_bundle(tmp_path, "celebamask_hq")
    bundle["gates"][0]["artifact_path"] = "../outside.json"
    bundle["seal_sha256"] = seal_payload(bundle)
    decision = verify_external_qualification_evidence(
        _load_provenance(),
        _load_inventory(),
        source="celebamask_hq",
        evidence_bundle=bundle,
        project_root=tmp_path,
    )

    assert decision.admitted is False
    assert "gate_artifact_path_unsafe:official_license_recorded" in decision.evidence_tokens


def test_registry_cannot_silently_remove_a_canonical_gate(tmp_path: Path):
    provenance = copy.deepcopy(_load_provenance())
    provenance["sources"]["lv_mhp_v1"]["training_admission"]["required_gates"].remove(
        "instance_identity_validated"
    )
    decision = verify_external_qualification_evidence(
        provenance,
        _load_inventory(),
        source="lv_mhp_v1",
        evidence_bundle=_evidence_bundle(tmp_path, "lv_mhp_v1"),
        project_root=tmp_path,
    )

    assert decision.admitted is False
    assert "canonical_gate_contract_drift" in decision.evidence_tokens
