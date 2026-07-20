"""Emit-path glue: tournament lifecycle sidecars + corpus envelopes under runs/."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
import yaml

from maskfactory.autonomy.controller import run_autonomous_correction_loop
from maskfactory.autonomy.corpus import (
    assemble_autonomous_verification_corpus,
    discover_corpus_records,
    scan_lifecycle_pool,
)
from maskfactory.autonomy.emit import (
    AutonomyEmitError,
    emit_lifecycle_and_corpus_record,
    repair_corpus_envelopes,
    resolve_production_machine_root,
)
from maskfactory.autonomy.tournament import CandidateEvidence
from maskfactory.io.hashing import sha256_file
from maskfactory.io.png_strict import write_binary_mask

LABEL = "torso"
CONTEXT = "solo"
PIPELINE_FP = "emit-path-glue-fp-v1"


def _config() -> dict:
    return yaml.safe_load(Path("configs/autonomous_masks.yaml").read_text(encoding="utf-8"))


def _no_correction(**_kwargs):
    return ()


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


def _image_id(seed: str) -> str:
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return f"img_{digest[:12]}"


def test_emit_writes_sidecar_and_envelope_resolvable_under_runs(tmp_path: Path):
    machine_root = tmp_path / "runs"
    batch = machine_root / "autonomous_gold_tournament_test"
    stage = batch / "img_emit_demo"
    autonomy = stage / "autonomy"
    autonomy.mkdir(parents=True)
    mask = write_binary_mask(
        stage / "masks" / "winner.png",
        np.pad(np.ones((8, 8), dtype=np.uint8) * 255, ((4, 4), (4, 4))),
    )
    mask_sha = sha256_file(mask)
    result = run_autonomous_correction_loop(
        (_winner(mask, mask_sha),),
        label=LABEL,
        context=CONTEXT,
        pipeline_fingerprint=PIPELINE_FP,
        config=_config(),
        correction_generator=_no_correction,
        certificate=None,
    )
    assert result.decision.status == "machine_verified_candidate"

    emit = emit_lifecycle_and_corpus_record(
        autonomy / f"{LABEL}.json",
        image_id=_image_id("emit-demo"),
        instance_id="p0",
        pipeline_fingerprint=PIPELINE_FP,
        decision=result.decision,
        machine_root=machine_root,
    )
    assert emit["corpus_envelope_written"] is True
    assert emit["lifecycle_relpath"].endswith("autonomy/torso.json")
    assert emit["lifecycle_relpath"].startswith("autonomous_gold_tournament_test/")
    assert Path(emit["lifecycle_path"]).is_file()
    assert Path(emit["corpus_envelope_path"]).is_file()

    pool = scan_lifecycle_pool(machine_root)
    assert pool["machine_verified_candidate_count"] == 1
    assert pool["corpus_record_envelopes_seen"] == 1

    records = discover_corpus_records(machine_root)
    assert len(records) == 1
    life = machine_root / records[0]["machine_lifecycle_path"]
    mask_bound = machine_root / records[0]["machine_mask_path"]
    assert life.is_file()
    assert mask_bound.is_file()

    summary = assemble_autonomous_verification_corpus(
        machine_root, tmp_path / "corpus.json", label=LABEL, context=CONTEXT
    )
    assert summary["record_count"] == 1


def test_emit_rejects_lifecycle_outside_production_machine_root(tmp_path: Path):
    outside = tmp_path / "outside" / "autonomy"
    outside.mkdir(parents=True)
    machine_root = tmp_path / "runs"
    machine_root.mkdir()
    mask = write_binary_mask(
        tmp_path / "outside" / "winner.png",
        np.pad(np.ones((8, 8), dtype=np.uint8) * 255, ((4, 4), (4, 4))),
    )
    mask_sha = sha256_file(mask)
    result = run_autonomous_correction_loop(
        (_winner(mask, mask_sha),),
        label=LABEL,
        context=CONTEXT,
        pipeline_fingerprint=PIPELINE_FP,
        config=_config(),
        correction_generator=_no_correction,
        certificate=None,
    )
    with pytest.raises(AutonomyEmitError, match="escapes production machine_root"):
        emit_lifecycle_and_corpus_record(
            outside / f"{LABEL}.json",
            image_id=_image_id("outside"),
            instance_id="p0",
            pipeline_fingerprint=PIPELINE_FP,
            decision=result.decision,
            machine_root=machine_root,
        )


def test_repair_rewrites_tournament_subdir_envelope_paths(tmp_path: Path):
    """Reproduce the live glue bug: envelope rooted at batch subdir, not runs/."""
    machine_root = tmp_path / "runs"
    batch = machine_root / "autonomous_gold_tournament_broken"
    stage = batch / "img_broken"
    autonomy = stage / "autonomy"
    autonomy.mkdir(parents=True)
    mask = write_binary_mask(
        stage / "masks" / "winner.png",
        np.pad(np.ones((8, 8), dtype=np.uint8) * 255, ((4, 4), (4, 4))),
    )
    mask_sha = sha256_file(mask)
    result = run_autonomous_correction_loop(
        (_winner(mask, mask_sha),),
        label=LABEL,
        context=CONTEXT,
        pipeline_fingerprint=PIPELINE_FP,
        config=_config(),
        correction_generator=_no_correction,
        certificate=None,
    )
    # Correct emit first, then deliberately break the envelope paths like the old bug.
    emit = emit_lifecycle_and_corpus_record(
        autonomy / f"{LABEL}.json",
        image_id=_image_id("broken"),
        instance_id="p0",
        pipeline_fingerprint=PIPELINE_FP,
        decision=result.decision,
        machine_root=machine_root,
    )
    envelope_path = Path(emit["corpus_envelope_path"])
    broken = dict(emit["corpus_record"])
    broken["machine_lifecycle_path"] = "img_broken/autonomy/torso.json"
    broken["machine_mask_path"] = "img_broken/masks/winner.png"
    envelope_path.write_text(
        __import__("json").dumps(broken, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert not (machine_root / broken["machine_lifecycle_path"]).is_file()

    report = repair_corpus_envelopes(machine_root)
    assert report["repaired"] == 1
    assert report["failed"] == 0
    records = discover_corpus_records(machine_root)
    assert (machine_root / records[0]["machine_lifecycle_path"]).is_file()
    assert (machine_root / records[0]["machine_mask_path"]).is_file()
    assert records[0]["machine_lifecycle_path"].startswith("autonomous_gold_tournament_broken/")


def test_resolve_production_machine_root_prefers_env(tmp_path: Path, monkeypatch):
    target = tmp_path / "custom_runs"
    target.mkdir()
    monkeypatch.setenv("MASKFACTORY_MACHINE_ROOT", str(target))
    assert resolve_production_machine_root() == target.resolve()
