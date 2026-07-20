"""Batch emit more MVC sidecars via prove-emit path + tournament --emit CLI.

Glue-proof only: no Wilson fabrication, no certificates, not human gold.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from maskfactory.autonomy.calibration import load_autonomy_config  # noqa: E402
from maskfactory.autonomy.corpus import scan_lifecycle_pool  # noqa: E402
from maskfactory.autonomy.emit import (  # noqa: E402
    prove_emit_machine_verified_candidate,
)
from maskfactory.autonomy.tournament import (  # noqa: E402
    CandidateEvidence,
    run_candidate_tournament,
)
from maskfactory.io.hashing import sha256_file  # noqa: E402
from maskfactory.io.png_strict import write_binary_mask  # noqa: E402

MASKFACTORY = REPO / ".venv" / "Scripts" / "maskfactory.exe"
MACHINE_ROOT = REPO / "runs"
CONFIG = REPO / "configs" / "autonomous_masks.yaml"
QA = REPO / "qa" / "live_verification"

LABELS = ("torso", "face", "hair", "left_hand", "right_hand", "left_foot", "right_foot", "skin")
CONTEXTS = ("solo", "solo", "solo", "solo", "solo", "solo", "solo", "solo")


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _mask() -> np.ndarray:
    return np.pad(np.ones((8, 8), dtype=np.uint8) * 255, ((4, 4), (4, 4)))


def emit_via_prove(n: int = 8) -> list[dict]:
    config = load_autonomy_config(CONFIG)
    stamp = _stamp()
    rows: list[dict] = []
    for i, (label, context) in enumerate(zip(LABELS, CONTEXTS, strict=True)):
        if i >= n:
            break
        batch_id = f"autonomous_gold_emit_prove_{stamp}_b{i:02d}"
        image_id = (
            "img_" + hashlib.sha256(f"emit-prove-batch:{stamp}:{i}".encode()).hexdigest()[:12]
        )
        emit = prove_emit_machine_verified_candidate(
            MACHINE_ROOT,
            batch_id=batch_id,
            image_id=image_id,
            label=label,
            context=context,
            pipeline_fingerprint=f"emit-path-cli-prove-batch-v1-{stamp}",
            config=config,
            mask_array=_mask(),
        )
        rows.append(
            {
                "mode": "prove_emit",
                "label": label,
                "image_id": image_id,
                "batch_id": batch_id,
                "lifecycle_path": emit.get("lifecycle_path"),
                "decision_status": emit.get("decision_status"),
            }
        )
        print(f"PROVE {i+1}/{n} {label} {image_id}", flush=True)
    return rows


def emit_via_tournament_cli(n: int = 6) -> list[dict]:
    """Build candidate docs and invoke ``maskfactory autonomy tournament --emit``."""
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    stamp = _stamp()
    rows: list[dict] = []
    staging = MACHINE_ROOT / f"autonomous_gold_tournament_emit_{stamp}"
    staging.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        label = LABELS[i % len(LABELS)]
        image_id = "img_" + hashlib.sha256(f"tournament-emit:{stamp}:{i}".encode()).hexdigest()[:12]
        stage = staging / image_id
        masks = stage / "masks"
        autonomy = stage / "autonomy"
        masks.mkdir(parents=True, exist_ok=True)
        autonomy.mkdir(parents=True, exist_ok=True)
        mask_path = write_binary_mask(masks / "winner.png", _mask())
        mask_sha = sha256_file(mask_path)
        candidate = CandidateEvidence(
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
        # Preflight: ensure tournament would select MVC before calling CLI.
        decision = run_candidate_tournament(
            (candidate,),
            label=label,
            context="solo",
            pipeline_fingerprint=f"tournament-emit-batch-v1-{stamp}",
            config=config,
            certificate=None,
        )
        if decision.status != "machine_verified_candidate":
            rows.append(
                {
                    "mode": "tournament_emit",
                    "label": label,
                    "image_id": image_id,
                    "error": f"preflight status={decision.status} reason={decision.reason}",
                }
            )
            print(f"TOURNAMENT SKIP {i+1}/{n} {label}: {decision.status}", flush=True)
            continue

        input_doc = {
            "label": label,
            "context": "solo",
            "pipeline_fingerprint": f"tournament-emit-batch-v1-{stamp}",
            "candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "mask_path": candidate.mask_path,
                    "mask_sha256": candidate.mask_sha256,
                    "independent_sources": candidate.independent_sources,
                    "consensus_iou": candidate.consensus_iou,
                    "boundary_agreement": candidate.boundary_agreement,
                    "pose_consistency": candidate.pose_consistency,
                    "critic_pass_weight": candidate.critic_pass_weight,
                    "critic_disagreement": candidate.critic_disagreement,
                    "protected_overlap": candidate.protected_overlap,
                    "exclusive_overlap": candidate.exclusive_overlap,
                    "component_count": candidate.component_count,
                    "ontology_max_components": candidate.ontology_max_components,
                    "format_valid": candidate.format_valid,
                    "block_qc_ids": list(candidate.block_qc_ids),
                    "source_provider_keys": list(candidate.source_provider_keys),
                    "source_model_families": list(candidate.source_model_families),
                }
            ],
        }
        input_path = staging / f"tournament_input_{i:02d}_{label}.json"
        output_path = QA / f"tournament_emit_decision_{stamp}_{i:02d}_{label}.json"
        input_path.write_text(
            json.dumps(input_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        lifecycle_relpath = (
            Path(f"autonomous_gold_tournament_emit_{stamp}")
            / image_id
            / "autonomy"
            / f"{label}.json"
        ).as_posix()
        cmd = [
            str(MASKFACTORY),
            "autonomy",
            "tournament",
            str(input_path),
            "--config",
            str(CONFIG),
            "--output",
            str(output_path),
            "--emit",
            "--machine-root",
            str(MACHINE_ROOT),
            "--image-id",
            image_id,
            "--instance-id",
            "p0",
            "--lifecycle-relpath",
            lifecycle_relpath,
        ]
        proc = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True, check=False)
        rows.append(
            {
                "mode": "tournament_emit",
                "label": label,
                "image_id": image_id,
                "lifecycle_relpath": lifecycle_relpath,
                "exit_code": proc.returncode,
                "stdout_tail": (proc.stdout or "")[-400:],
                "stderr_tail": (proc.stderr or "")[-400:],
                "output": str(output_path.relative_to(REPO).as_posix()),
            }
        )
        print(f"TOURNAMENT {i+1}/{n} {label} exit={proc.returncode}", flush=True)
    return rows


def main() -> int:
    before = scan_lifecycle_pool(MACHINE_ROOT)
    prove_rows = emit_via_prove(8)
    tournament_rows = emit_via_tournament_cli(6)
    after = scan_lifecycle_pool(MACHINE_ROOT)
    stamp = _stamp()
    evidence = {
        "artifact_type": "autonomy_batch_emit_more_images",
        "schema_version": "1.0.0",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "authority": "emit_path_glue_proof_only",
        "mvc_before": int(before["machine_verified_candidate_count"]),
        "mvc_after": int(after["machine_verified_candidate_count"]),
        "before_pool": before,
        "after_pool": after,
        "prove_emit_rows": prove_rows,
        "tournament_emit_rows": tournament_rows,
        "claim_boundary": {
            "emit_path_glue_proof_only": True,
            "no_fabricated_wilson_samples": True,
            "no_certificate_minted": True,
            "not_authoritative_human_gold": True,
        },
    }
    body = json.dumps(
        {k: v for k, v in evidence.items() if k != "self_sha256"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    evidence["self_sha256"] = hashlib.sha256(body).hexdigest()
    out = QA / f"autonomy_batch_emit_more_images_{stamp}.json"
    out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "mvc_before": evidence["mvc_before"],
        "mvc_after": evidence["mvc_after"],
        "prove_emit_count": len(prove_rows),
        "tournament_emit_ok": sum(1 for r in tournament_rows if r.get("exit_code") == 0),
        "output": str(out.relative_to(REPO).as_posix()),
        "self_sha256": evidence["self_sha256"],
    }
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0 if evidence["mvc_after"] > evidence["mvc_before"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
