"""Measured champions path production glue: runs/ → audit → P5 → benchmark → promote."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from maskfactory.autonomy.controller import run_autonomous_correction_loop
from maskfactory.autonomy.corpus import (
    assemble_autonomous_verification_corpus,
    corpus_record_from_decision,
    scan_lifecycle_pool,
)
from maskfactory.autonomy.lifecycle import write_lifecycle_sidecar
from maskfactory.autonomy.production_audit import build_production_weekly_audit_queue
from maskfactory.autonomy.tournament import CandidateEvidence
from maskfactory.io.hashing import sha256_file
from maskfactory.io.png_strict import write_binary_mask
from maskfactory.models.benchmark import mark_benchmarked_candidate
from maskfactory.models.ontology_contract import (
    V1_ONTOLOGY_VERSION,
    V1_PART_CLASS_NAMES,
    class_names_sha256,
)
from maskfactory.models.registry import ModelRegistryError
from maskfactory.training.promotion_policy import (
    CERTIFICATE_AUTHORITY,
    REQUIRED_CERTIFICATE_IDENTITY_HASHES,
    REQUIRED_RESULT_INPUT_HASHES,
    load_custom_segmenter_margin_manifest,
)
from registry_helpers import ALLOWED_CONTENT, governed_file_model, governed_registry

LABEL = "torso"
CONTEXT = "solo"
PIPELINE_FP = "measured-champions-path-glue-fp-v1"


def _config() -> dict:
    return yaml.safe_load(Path("configs/autonomous_masks.yaml").read_text(encoding="utf-8"))


def _no_correction(**_kwargs):
    return ()


def _digest(value: str | bytes) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def _winner(mask_path: Path, mask_sha: str) -> CandidateEvidence:
    return CandidateEvidence(
        candidate_id="winner",
        mask_path=str(mask_path),
        mask_sha256=mask_sha,
        independent_sources=3,
        consensus_iou=0.98,
        boundary_agreement=0.98,
        pose_consistency=0.98,
        critic_pass_weight=0.96,
        critic_disagreement=False,
        protected_overlap=0.0,
        exclusive_overlap=0.0,
        component_count=1,
        ontology_max_components=1,
        format_valid=True,
        block_qc_ids=(),
        source_provider_keys=("fam_a", "fam_b", "fam_c"),
        source_model_families=("family_a", "family_b", "family_c"),
    )


def _image_id(index: int) -> str:
    digest = hashlib.sha256(f"glue:{index}".encode()).hexdigest()
    return f"img_{digest[:12]}"


def test_audit_queue_discovers_production_autonomy_layout(tmp_path: Path):
    """runs/<run>/S11/autonomy/*.json calibrated sidecars populate the audit queue."""
    from maskfactory.autonomy.calibration import build_autonomous_gold_certificate

    config = _config()
    machine_root = tmp_path / "runs"
    draft_root = tmp_path / "draft_machine"
    (draft_root / "lifecycle").mkdir(parents=True)
    (draft_root / "masks").mkdir()
    draft_mask = write_binary_mask(
        draft_root / "masks/d.png",
        np.pad(np.ones((8, 8), dtype=np.uint8) * 255, ((4, 4), (4, 4))),
    )
    draft_sha = sha256_file(draft_mask)
    records = []
    for index in range(600):
        result = run_autonomous_correction_loop(
            (_winner(draft_mask, draft_sha),),
            label=LABEL,
            context=CONTEXT,
            pipeline_fingerprint=PIPELINE_FP,
            config=config,
            correction_generator=_no_correction,
            certificate=None,
        )
        assert result.decision.status == "machine_verified_candidate"
        life = draft_root / "lifecycle" / f"d_{index:06d}.json"
        write_lifecycle_sidecar(
            life,
            image_id=_image_id(10_000 + index),
            instance_id="p0",
            pipeline_fingerprint=PIPELINE_FP,
            decision=result.decision,
        )
        records.append(
            {
                "record_id": f"rec{index:06d}",
                "image_id": _image_id(10_000 + index),
                "label": LABEL,
                "context": CONTEXT,
                "risk_bucket": CONTEXT,
                "pipeline_fingerprint": PIPELINE_FP,
                "machine_accepted": True,
                "independent_family_count": 3,
                "cross_family_disagreement": False,
                "serious_cross_family_disagreement": False,
                "candidate_stability_pass": True,
                "perturbation_stability_pass": True,
                "complete_map_hard_veto_pass": True,
                "machine_lifecycle_path": f"lifecycle/d_{index:06d}.json",
                "machine_lifecycle_sha256": sha256_file(life),
                "machine_mask_path": "masks/d.png",
                "machine_mask_sha256": draft_sha,
            }
        )
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "frozen": True,
                "image_disjoint": True,
                "records": records,
            }
        ),
        encoding="utf-8",
    )
    certificate = build_autonomous_gold_certificate(
        corpus_path,
        label=LABEL,
        context=CONTEXT,
        pipeline_fingerprint=PIPELINE_FP,
        machine_artifacts_root=draft_root,
    )
    assert certificate.get("passed") is True

    for index in range(30):
        stage = machine_root / f"run_{index:03d}" / "S11"
        autonomy = stage / "autonomy"
        autonomy.mkdir(parents=True, exist_ok=True)
        local_mask = write_binary_mask(
            stage / "winner.png",
            np.pad(np.ones((8, 8), dtype=np.uint8) * 255, ((4, 4), (4, 4))),
        )
        local_sha = sha256_file(local_mask)
        result = run_autonomous_correction_loop(
            (_winner(local_mask, local_sha),),
            label=LABEL,
            context=CONTEXT,
            pipeline_fingerprint=PIPELINE_FP,
            config=config,
            correction_generator=_no_correction,
            certificate=certificate,
            allow_autonomous_profile=True,
        )
        assert result.decision.status == "calibrated_auto_accepted"
        write_lifecycle_sidecar(
            autonomy / f"{LABEL}.json",
            image_id=_image_id(index),
            instance_id="p0",
            pipeline_fingerprint=PIPELINE_FP,
            decision=result.decision,
        )
        # Unrelated JSON under runs/ (outside autonomy/) must be ignored.
        (machine_root / f"run_{index:03d}" / "noise.json").write_text(
            json.dumps({"status": "complete", "not": "lifecycle"}), encoding="utf-8"
        )

    queue = build_production_weekly_audit_queue(
        machine_root,
        tmp_path / "queue.json",
        period_id="2026-W29",
        operations_policy=config["operations"],
    )
    assert queue["population_count"] == 30
    assert queue["outcomes_status"] == "pending"
    assert queue["selected_count"] >= 20


def test_corpus_envelope_and_assembly_from_production_layout(tmp_path: Path):
    config = _config()
    machine_root = tmp_path / "runs"
    stage = machine_root / "run_abc" / "S11"
    autonomy = stage / "autonomy"
    autonomy.mkdir(parents=True)
    mask = write_binary_mask(
        stage / "winner.png",
        np.pad(np.ones((8, 8), dtype=np.uint8) * 255, ((4, 4), (4, 4))),
    )
    mask_sha = sha256_file(mask)
    result = run_autonomous_correction_loop(
        (_winner(mask, mask_sha),),
        label=LABEL,
        context=CONTEXT,
        pipeline_fingerprint=PIPELINE_FP,
        config=config,
        correction_generator=_no_correction,
        certificate=None,
    )
    assert result.decision.status == "machine_verified_candidate"
    life = autonomy / f"{LABEL}.json"
    write_lifecycle_sidecar(
        life,
        image_id=_image_id(1),
        instance_id="p0",
        pipeline_fingerprint=PIPELINE_FP,
        decision=result.decision,
    )
    envelope = corpus_record_from_decision(
        life,
        machine_root=machine_root,
        image_id=_image_id(1),
        decision=result.decision,
        pipeline_fingerprint=PIPELINE_FP,
    )
    assert envelope is not None
    assert envelope["independent_family_count"] >= 3
    pool = scan_lifecycle_pool(machine_root)
    assert pool["machine_verified_candidate_count"] == 1
    assert pool["corpus_record_envelopes_seen"] == 1
    summary = assemble_autonomous_verification_corpus(
        machine_root, tmp_path / "corpus.json", label=LABEL, context=CONTEXT
    )
    assert summary["record_count"] == 1
    assert summary["max_independent_family_count"] >= 3


def test_mark_benchmarked_refuses_champions_and_requires_installed(tmp_path: Path):
    models_root = tmp_path / "models"
    models_root.mkdir()
    checkpoint = models_root / "cand.pth"
    config = models_root / "cand.py"
    checkpoint.write_bytes(b"cand-bytes")
    config.write_text("model = dict(type='cand')\n", encoding="utf-8")
    cand_hash = _digest(checkpoint.read_bytes())
    cfg_hash = _digest(config.read_bytes())
    candidate = governed_file_model(
        key="eomt_glue_candidate",
        role="challenger_bodypart",
        file="models/cand.pth",
        sha256=cand_hash,
        lifecycle_state="installed",
        inference_config="models/cand.py",
        inference_config_sha256=cfg_hash,
        ontology_version=V1_ONTOLOGY_VERSION,
        class_names=list(V1_PART_CLASS_NAMES),
        class_names_sha256=class_names_sha256(list(V1_PART_CLASS_NAMES)),
        artifact_hashes={
            "checkpoint_sha256": cand_hash,
            "inference_config_sha256": cfg_hash,
        },
    )
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps(governed_registry([candidate])), encoding="utf-8")

    manifest, margins = load_custom_segmenter_margin_manifest()
    input_hashes = {key: _digest(key) for key in REQUIRED_RESULT_INPUT_HASHES}
    results = {
        "schema_version": "1.0.0",
        "benchmark_id": "glue-benchmark-v1",
        "role": "custom_segmenter",
        "margin_manifest_sha256": manifest["sha256"],
        "results_opened_at": "2026-07-15T05:30:00Z",
        "input_hashes": input_hashes,
        "primary_objective_result": {
            "metric": manifest["role"]["primary_objective"]["metric"],
            "observed_improvement": 0.005,
            "minimum_improvement": manifest["role"]["primary_objective"]["minimum_improvement"],
            "passed": True,
        },
        "labor_objective_result": {
            "metric": manifest["role"]["labor_objective"]["metric"],
            "observed_improvement": 0.0,
            "minimum_improvement": manifest["role"]["labor_objective"]["minimum_improvement"],
            "passed": False,
        },
        "rows": [
            {
                "bucket": bucket,
                "observed_delta": 0.0,
                "noninferiority_margin": margin,
                "passed": True,
            }
            for bucket, margin in sorted(margins.items())
        ],
    }
    results["sha256"] = hashlib.sha256(
        json.dumps(results, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    identities = {key: _digest(key) for key in REQUIRED_CERTIFICATE_IDENTITY_HASHES}
    identities.update(input_hashes)
    identities["benchmark_results_sha256"] = results["sha256"]
    identities["checkpoint_sha256"] = cand_hash
    certificate = {
        "schema_version": "1.0.0",
        "authority": CERTIFICATE_AUTHORITY,
        "candidate_key": "eomt_glue_candidate",
        "target_role": "custom_segmenter",
        "lifecycle_state": "benchmarked",
        "identity_hashes": identities,
        "content_compatibility": dict(ALLOWED_CONTENT),
        "license_gate": {"verify_license": False, "checkpoint_decision": "allowed"},
        "benchmark_results": results,
        "rollback_evidence": {
            "candidate_provider": "eomt_glue_candidate",
            "incumbent_provider": "segformer_b2_fixture",
            "target_role": "custom_segmenter",
            "one_command": "maskfactory models rollback-custom-segmenter TRANSACTION_ID",
            "rollback_observed": True,
            "restore_observed": True,
            "result": "pass",
            "tested_at": "2026-07-15T05:45:00Z",
            "evidence_sha256": _digest("rollback"),
        },
    }
    certificate["sha256"] = hashlib.sha256(
        json.dumps(certificate, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    updated = mark_benchmarked_candidate(
        "eomt_glue_candidate",
        certificate=certificate,
        registry_path=registry,
        models_root=models_root,
    )
    assert updated["lifecycle_state"] == "benchmarked"
    assert updated["role"] == "challenger_bodypart"
    assert updated["benchmark_certificate"]["primary_win_or_labor_reduction"] is True
    assert (
        updated["artifact_hashes"]["custom_segmenter_certificate_sha256"] == certificate["sha256"]
    )

    with pytest.raises(ModelRegistryError, match="already lifecycle benchmarked"):
        mark_benchmarked_candidate(
            "eomt_glue_candidate",
            certificate=certificate,
            registry_path=registry,
            models_root=models_root,
        )
