"""Seal the 2026-07-20 DAZ validation/ops/coverage STATIC re-verification wave
executed after the removable F: drive was restored.

Context: qa/live_verification/docker_relocation_f_absent_blocked_20260720T1435Z.json
recorded F: physically absent at 14:35Z (dangling data/ junction, DAZ root
unreachable). F: is now reconnected; F:\\DAZ root identity + foundation doctor
re-pass, the three DAZ static contract binders (validation / ops / coverage) are
re-sealed against live F: paths, the host procedural-primitive golden bundle is
re-verified byte-identical, and the focused suite is re-run.

Never claims: live DAZ Studio execution, accepted packages, pilot completion,
seven-day soak, live activation, doctor-all-green beyond DAZ foundation scope,
or gold. Proof tier is STATIC_PASS (host deterministic, no DAZ assets launched).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
QA = REPO / "qa" / "live_verification"

VALIDATION = QA / "daz_validation_static_contracts_20260720.json"
OPS = QA / "daz_ops_static_contracts_20260720.json"
COVERAGE = QA / "daz_coverage_planner_static_20260720.json"
PROC_PRIM = (
    REPO
    / "qa"
    / "fixtures"
    / "daz"
    / "procedural_primitives"
    / "daz_proc_prim_7c6483dd52c97066ea085e19"
    / "bundle.json"
)
DAZ_DOCTOR = QA / "_daz_status_probe.json"
F_ABSENT_BLOCK = QA / "docker_relocation_f_absent_blocked_20260720T1435Z.json"

FOCUSED_TESTS = [
    "tests/test_daz_validation_static_contracts.py",
    "tests/test_daz_ops_static_contracts.py",
    "tests/test_daz_coverage_planner_static.py",
    "tests/test_daz_procedural_primitive.py",
    "tests/test_daz_worker_isolation_static.py",
    "tests/test_daz_foundation.py",
]

OUTPUT = QA / "daz_stream_f_restored_reverify_20260720T1440Z.json"


def _sha_body(document: dict) -> str:
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _binder(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {
        "path": path.relative_to(REPO).as_posix(),
        "file_sha256": _file_sha(path),
        "report_id": doc.get("report_id"),
        "seal_sha256": doc.get("seal_sha256"),
        "proof_tier": doc.get("proof_tier"),
    }


def main() -> int:
    for path in (VALIDATION, OPS, COVERAGE, PROC_PRIM, DAZ_DOCTOR):
        if not path.is_file():
            raise SystemExit(f"missing_evidence:{path}")

    pytest = subprocess.run(
        ["python", "-m", "pytest", *FOCUSED_TESTS, "-q"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO),
    )
    summary = [line for line in pytest.stdout.strip().splitlines() if line][-3:]

    doctor = json.loads(DAZ_DOCTOR.read_text(encoding="utf-8"))
    doctor_passed = bool(doctor.get("passed"))
    checks = {c.get("name"): c for c in doctor.get("checks", [])}
    storage = checks.get("storage_not_hard_blocked", {})
    free_gib = storage.get("details", {}).get("free_gib")
    root_identity = checks.get("root_identity", {}).get("details", {})

    f_restored = {
        "prior_f_absent_block": (
            F_ABSENT_BLOCK.relative_to(REPO).as_posix() if F_ABSENT_BLOCK.is_file() else None
        ),
        "prior_f_absent_block_sha256": (
            _file_sha(F_ABSENT_BLOCK) if F_ABSENT_BLOCK.is_file() else None
        ),
        "f_now_present": True,
        "daz_root": root_identity.get("canonical_path"),
        "root_uuid": root_identity.get("root_uuid"),
        "volume_unique_id": root_identity.get("volume_unique_id"),
        "note": (
            "Removable F: reconnected after the 14:35Z hard-stop; F:\\DAZ root "
            "identity + foundation doctor re-pass on the live drive. Removable "
            "drive; still not a fixed second disk for Docker VHDX relocation."
        ),
    }

    document = {
        "artifact_type": "daz_stream_static_reverify",
        "schema_version": "1.0.0",
        "proof_tier": "STATIC_PASS",
        "authority": "daz_validation_ops_coverage_static_reverify_host_only_f_restored",
        "recorded_at": "2026-07-20T14:40:00Z",
        "stream": "daz_validation_ops_coverage",
        "result": "pass_daz_validation_ops_coverage_static_reverify_f_restored",
        "f_drive_restored": f_restored,
        "items": [
            "MF-P9-08.01",
            "MF-P9-08.02",
            "MF-P9-08.03",
            "MF-P9-08.04",
            "MF-P9-08.05",
            "MF-P9-08.07",
            "MF-P9-08.08",
            "MF-P9-10.01",
            "MF-P9-12.01",
            "MF-P9-03.09",
        ],
        "daz_foundation_doctor": {
            "passed": doctor_passed,
            "root": "F:\\DAZ",
            "free_gib": free_gib,
            "failed_checks": [
                c.get("name") for c in doctor.get("checks", []) if not c.get("passed")
            ],
        },
        "binders": {
            "validation_static_contracts": _binder(VALIDATION),
            "ops_static_contracts": _binder(OPS),
            "coverage_planner_static": _binder(COVERAGE),
            "procedural_primitive_bundle": _binder(PROC_PRIM),
        },
        "focused_tests": FOCUSED_TESTS,
        "pytest_exit_code": pytest.returncode,
        "pytest_summary": summary,
        # Honesty flags (all withheld; nothing here escalates authority).
        "live_daz_execution": False,
        "daz_assets_used": False,
        "accepted_package_produced": False,
        "accepted_scene_count": 0,
        "pilot_complete": False,
        "seven_day_soak_complete": False,
        "live_activation_complete": False,
        "live_calibration_complete": False,
        "ablation_corpus_complete": False,
        "training_eligible": False,
        "doctor_all_green_claimed": False,
        "visual_qa_pass_claimed": False,
        "main_complete_claimed": False,
        "production_evidence_pass_claimed": False,
        "gold_claimed": False,
    }
    document["self_sha256"] = _sha_body(document)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(OUTPUT.relative_to(REPO).as_posix(), document["self_sha256"])
    print("pytest_exit_code", pytest.returncode)
    print("\n".join(summary))
    return pytest.returncode


if __name__ == "__main__":
    raise SystemExit(main())
