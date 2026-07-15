from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from maskfactory.providers.benchmark_policy import (
    SPECIALIST_ROLES,
    load_specialist_margin_manifest,
)
from maskfactory.providers.matrix_promotion import (
    CERTIFICATE_AUTHORITY,
    MatrixPromotionCertificateError,
    build_matrix_promotion_certificate,
    generate_matrix_promotion_signing_key,
    load_and_verify_matrix_promotion_bundle,
    verify_matrix_promotion_certificate,
)
from maskfactory.providers.provider_matrix import canonical_sha256
from maskfactory.providers.provider_matrix_metrics import build_report
from maskfactory.training.promotion_policy import load_custom_segmenter_margin_manifest
from maskfactory.validation import validate_document
from test_custom_segmenter_promotion_policy import _certificate as custom_certificate_fixture
from test_provider_benchmark_matrix_metrics import _manifest, _observations
from test_specialist_promotion import _valid_packet

ROOT = Path(__file__).resolve().parents[1]
ROLE_ARTIFACTS = {
    "chest_pelvic_segmentation": "densepose",
    "clothing_accessory_segmentation": "sam3_1",
    "foot_toe_segmentation": "sam2_1",
    "geometry_provider": "sam3d_body",
    "hair_matting": "vitmatte",
    "hand_finger_segmentation": "mediapipe_hands",
    "pose_provider": "dwpose_133",
    "repeated_instance_segmentation": "rfdetr",
    "silhouette_provider": "birefnet_general",
}


def _seal(document: dict) -> None:
    document["sha256"] = canonical_sha256(
        {key: value for key, value in document.items() if key != "sha256"}
    )


def _fixture(tmp_path: Path) -> dict:
    manifest = _manifest()
    observations = _observations(manifest)
    report = build_report(observations, manifest)
    specialist_manifest, expanded = load_specialist_margin_manifest()
    base, _ = _valid_packet()
    packets = {}
    for role in sorted(SPECIALIST_ROLES):
        packet = copy.deepcopy(base)
        artifact_key = ROLE_ARTIFACTS[role]
        candidate = artifact_key
        packet["candidate_key"] = candidate
        packet["target_role"] = role
        packet["identity_hashes"]["checkpoint_sha256"] = manifest["shared_identity"][
            "provider_artifact_sha256"
        ][artifact_key]
        results = packet["benchmark_results"]
        results["benchmark_id"] = f"pytest-{role}"
        results["role"] = role
        results["rows"] = [
            {
                "bucket": bucket,
                "observed_delta": 0.0,
                "noninferiority_margin": margin,
                "passed": True,
            }
            for bucket, margin in expanded[role].items()
        ]
        _seal(results)
        rollback = packet["rollback_evidence"]
        rollback.update(
            candidate_provider=candidate,
            incumbent_provider=f"{candidate}_incumbent",
            target_role=role,
            one_command=f"maskfactory providers rollback {role}",
            evidence_sha256=hashlib.sha256(f"rollback-{role}".encode()).hexdigest(),
        )
        _seal(packet)
        packets[role] = packet

    custom_manifest, custom_margins = load_custom_segmenter_margin_manifest()
    custom, identities = custom_certificate_fixture(custom_manifest, custom_margins)
    shared = manifest["shared_identity"]
    for identity_key, shared_key in (
        ("evaluation_set_sha256", "evaluation_set_sha256"),
        ("hardware_profile_sha256", "hardware_profile_sha256"),
        ("qa_config_sha256", "qa_sha256"),
    ):
        identities[identity_key] = shared[shared_key]
        custom["identity_hashes"][identity_key] = shared[shared_key]
        custom["benchmark_results"]["input_hashes"][identity_key] = shared[shared_key]
    _seal(custom["benchmark_results"])
    identities["benchmark_results_sha256"] = custom["benchmark_results"]["sha256"]
    custom["identity_hashes"]["benchmark_results_sha256"] = custom["benchmark_results"]["sha256"]
    _seal(custom)

    cells = [*manifest["screening_cells"], *manifest["enrichment_cells"]]
    used: set[str] = set()
    bindings = {}
    for role, artifact_key in sorted(ROLE_ARTIFACTS.items()):
        cell = next(
            cell
            for cell in cells
            if cell["cell_id"] not in used and artifact_key in cell["provider_artifact_keys"]
        )
        used.add(cell["cell_id"])
        bindings[role] = {
            "binding_mode": "candidate_artifact",
            "cell_id": cell["cell_id"],
            "provider_artifact_key": artifact_key,
        }
    context = next(cell for cell in cells if cell["cell_id"] not in used)
    bindings["custom_segmenter"] = {
        "binding_mode": "pipeline_context",
        "cell_id": context["cell_id"],
        "provider_artifact_key": None,
    }
    private_key = tmp_path / "private.pem"
    public_key = tmp_path / "public.pem"
    generate_matrix_promotion_signing_key(private_key, public_key)
    return {
        "reviewer": "pytest-governance",
        "private_key_path": private_key,
        "public_key_path": public_key,
        "matrix_report": report,
        "matrix_observations": observations,
        "matrix_manifest": manifest,
        "specialist_packets": packets,
        "custom_segmenter_certificate": custom,
        "custom_segmenter_expected_identity_hashes": identities,
        "role_matrix_bindings": bindings,
        "issued_at": datetime(2026, 7, 17, tzinfo=UTC),
    }


def _build(inputs: dict) -> dict:
    arguments = {key: value for key, value in inputs.items() if key != "public_key_path"}
    return build_matrix_promotion_certificate(**arguments)


def _verify(certificate: dict, inputs: dict) -> dict:
    arguments = {
        key: value
        for key, value in inputs.items()
        if key not in {"private_key_path", "reviewer", "issued_at"}
    }
    return verify_matrix_promotion_certificate(certificate, **arguments)


def _bundle(tmp_path: Path, inputs: dict, certificate: dict) -> Path:
    root = tmp_path / "promotion_bundle"
    packet_root = root / "specialist_packets"
    packet_root.mkdir(parents=True)
    artifacts = {
        "certificate.json": certificate,
        "matrix_report.json": inputs["matrix_report"],
        "matrix_observations.json": inputs["matrix_observations"],
        "matrix_manifest.json": inputs["matrix_manifest"],
        "custom_segmenter_certificate.json": inputs["custom_segmenter_certificate"],
        "custom_segmenter_identities.json": inputs["custom_segmenter_expected_identity_hashes"],
        "role_matrix_bindings.json": inputs["role_matrix_bindings"],
    }
    for name, value in artifacts.items():
        (root / name).write_text(json.dumps(value), encoding="utf-8")
    for role, packet in inputs["specialist_packets"].items():
        (packet_root / f"{role}.json").write_text(json.dumps(packet), encoding="utf-8")
    (root / "public_key.pem").write_bytes(inputs["public_key_path"].read_bytes())
    return root


def test_valid_certificate_binds_all_roles_but_grants_no_authority(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    certificate = _build(inputs)
    summary = _verify(certificate, inputs)

    assert not validate_document(certificate, "matrix_promotion_certificate")
    assert summary["role_count"] == 10
    assert [row["role"] for row in certificate["role_bindings"]] == sorted(
        {*SPECIALIST_ROLES, "custom_segmenter"}
    )
    assert len({row["matrix_cell_id"] for row in certificate["role_bindings"]}) == 10
    assert summary["authority"] == CERTIFICATE_AUTHORITY
    assert "no_role_promotion_serving_mask_or_gold_authority" in certificate["authority"]


def test_fixed_bundle_layout_recomputes_signature_and_rejects_packet_drift(
    tmp_path: Path,
) -> None:
    inputs = _fixture(tmp_path)
    certificate = _build(inputs)
    bundle = _bundle(tmp_path, inputs, certificate)
    loaded = load_and_verify_matrix_promotion_bundle(bundle)
    assert loaded["summary"]["certificate_sha256"] == certificate["certificate_sha256"]
    assert set(loaded["specialist_packets"]) == set(SPECIALIST_ROLES)

    packet = bundle / "specialist_packets" / f"{sorted(SPECIALIST_ROLES)[0]}.json"
    document = json.loads(packet.read_text(encoding="utf-8"))
    document["identity_hashes"]["checkpoint_sha256"] = "0" * 64
    packet.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(MatrixPromotionCertificateError):
        load_and_verify_matrix_promotion_bundle(bundle)


def test_fixed_bundle_layout_rejects_missing_or_unexpected_packet(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    bundle = _bundle(tmp_path, inputs, _build(inputs))
    packet_root = bundle / "specialist_packets"
    next(packet_root.glob("*.json")).unlink()
    (packet_root / "unexpected.json").write_text("{}", encoding="utf-8")
    with pytest.raises(MatrixPromotionCertificateError, match="filenames"):
        load_and_verify_matrix_promotion_bundle(bundle)


def test_missing_role_duplicate_cell_and_candidate_rebinding_fail_closed(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    missing = copy.deepcopy(inputs)
    missing["specialist_packets"].pop(next(iter(SPECIALIST_ROLES)))
    with pytest.raises(MatrixPromotionCertificateError, match="packet set is incomplete"):
        _build(missing)

    duplicate = copy.deepcopy(inputs)
    roles = sorted(SPECIALIST_ROLES)
    duplicate["role_matrix_bindings"][roles[1]]["cell_id"] = duplicate["role_matrix_bindings"][
        roles[0]
    ]["cell_id"]
    with pytest.raises(MatrixPromotionCertificateError, match="may not satisfy multiple"):
        _build(duplicate)

    rebound = copy.deepcopy(inputs)
    role = roles[0]
    rebound["specialist_packets"][role]["identity_hashes"]["checkpoint_sha256"] = "0" * 64
    _seal(rebound["specialist_packets"][role])
    with pytest.raises(MatrixPromotionCertificateError, match="artifact identity is stale"):
        _build(rebound)


def test_custom_shared_identity_and_matrix_recomputation_fail_closed(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    stale = copy.deepcopy(inputs)
    stale["custom_segmenter_expected_identity_hashes"]["evaluation_set_sha256"] = "0" * 64
    with pytest.raises(MatrixPromotionCertificateError, match="certificate identity is stale"):
        _build(stale)

    tampered = copy.deepcopy(inputs)
    tampered["matrix_report"]["cells"][0]["metrics"]["small_part_recall"] = 1.0
    tampered["matrix_report"]["sha256"] = canonical_sha256(
        {key: value for key, value in tampered["matrix_report"].items() if key != "sha256"}
    )
    with pytest.raises(MatrixPromotionCertificateError, match="recomputation"):
        _build(tampered)

    naive = copy.deepcopy(inputs)
    naive["issued_at"] = datetime(2026, 7, 17)
    with pytest.raises(MatrixPromotionCertificateError, match="timezone"):
        _build(naive)


def test_signature_payload_and_live_input_tampering_fail_closed(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    certificate = _build(inputs)
    signature = copy.deepcopy(certificate)
    signature["signature"] = "A" * 86 + "=="
    signature["certificate_sha256"] = canonical_sha256(
        {key: value for key, value in signature.items() if key != "certificate_sha256"}
    )
    with pytest.raises(MatrixPromotionCertificateError, match="signature is invalid"):
        _verify(signature, inputs)

    live = copy.deepcopy(inputs)
    role = sorted(SPECIALIST_ROLES)[0]
    live["specialist_packets"][role]["rollback_evidence"]["evidence_sha256"] = "f" * 64
    _seal(live["specialist_packets"][role])
    with pytest.raises(MatrixPromotionCertificateError):
        _verify(certificate, live)


def test_cli_builds_and_verifies_the_exact_bundle(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    paths = {}
    for name in ("matrix_manifest", "matrix_observations", "matrix_report"):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(inputs[name]), encoding="utf-8")
        paths[name] = path
    packet_dir = tmp_path / "specialists"
    packet_dir.mkdir()
    for role, packet in inputs["specialist_packets"].items():
        (packet_dir / f"{role}.json").write_text(json.dumps(packet), encoding="utf-8")
    for name in (
        "custom_segmenter_certificate",
        "custom_segmenter_expected_identity_hashes",
        "role_matrix_bindings",
    ):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(inputs[name]), encoding="utf-8")
        paths[name] = path
    output = tmp_path / "aggregate.json"
    common = [
        sys.executable,
        str(ROOT / "tools/certify_provider_role_promotions.py"),
        "--manifest",
        str(paths["matrix_manifest"]),
        "--observations",
        str(paths["matrix_observations"]),
        "--report",
        str(paths["matrix_report"]),
        "--specialist-packet-dir",
        str(packet_dir),
        "--custom-segmenter-certificate",
        str(paths["custom_segmenter_certificate"]),
        "--custom-segmenter-identities",
        str(paths["custom_segmenter_expected_identity_hashes"]),
        "--role-matrix-bindings",
        str(paths["role_matrix_bindings"]),
        "--output",
        str(output),
        "--issued-at",
        "2026-07-17T00:00:00Z",
    ]
    built = subprocess.run(
        [*common, "--private-key", str(inputs["private_key_path"])],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    verified = subprocess.run(
        [*common, "--public-key", str(inputs["public_key_path"]), "--verify"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert verified.returncode == 0, verified.stderr
