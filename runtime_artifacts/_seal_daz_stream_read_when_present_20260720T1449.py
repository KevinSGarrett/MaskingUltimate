"""Seal the 2026-07-20 DAZ validation/ops/coverage STATIC re-verification wave
executed while F:\\DAZ is present (read-when-present; 26 top-level entries).

Re-seals binders AFTER focused pytest to resist parallel-agent binder overwrite
races, then binds those final binder hashes into the consolidated seal.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path

from maskfactory.autonomy.gold_volume_sources import probe_gold_volume_sources

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
PRIOR_F_RESTORED = QA / "daz_stream_f_restored_reverify_20260720T1440Z.json"
GOLD_SLICE = QA / "_gold_volume_daz_present_20260720T1449.json"

FOCUSED_TESTS = [
    "tests/test_daz_validation_static_contracts.py",
    "tests/test_daz_ops_static_contracts.py",
    "tests/test_daz_coverage_planner_static.py",
    "tests/test_daz_procedural_primitive.py",
    "tests/test_daz_worker_isolation_static.py",
    "tests/test_daz_foundation.py",
]

OUTPUT = QA / "daz_stream_read_when_present_20260720T1449Z.json"


def _sha_body(document: dict) -> str:
    body = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jsonable(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _binder(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {
        "path": path.relative_to(REPO).as_posix(),
        "file_sha256": _file_sha(path),
        "report_id": doc.get("report_id"),
        "seal_sha256": doc.get("seal_sha256"),
        "proof_tier": doc.get("proof_tier"),
    }


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=str(REPO))


def main() -> int:
    daz_root = Path(r"F:\DAZ")
    if not daz_root.is_dir():
        raise SystemExit("missing_f_daz")

    entry_names = sorted(p.name for p in daz_root.iterdir())
    entry_count = len(entry_names)
    if entry_count != 26:
        raise SystemExit(f"unexpected_f_daz_entry_count:{entry_count}")

    if not PROC_PRIM.is_file():
        raise SystemExit(f"missing_evidence:{PROC_PRIM}")

    doctor_proc = _run([sys.executable, "tools/daz_status.py"])
    doctor = json.loads(doctor_proc.stdout)
    DAZ_DOCTOR.write_text(json.dumps(doctor, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    checks = {c.get("name"): c for c in doctor.get("checks", [])}
    storage = checks.get("storage_not_hard_blocked", {})
    storage_details = storage.get("details", {}) if isinstance(storage.get("details"), dict) else {}
    free_gib = storage_details.get("free_gib")
    storage_level = storage_details.get("level")
    root_identity = checks.get("root_identity", {}).get("details", {})
    failed_checks = [c.get("name") for c in doctor.get("checks", []) if not c.get("passed")]
    soft_capacity_only = (
        failed_checks == ["acquisition_pool_capacity_safe"] and storage_level == "soft"
    )
    doctor_passed = bool(doctor.get("passed"))
    doctor_acceptable_for_static = doctor_passed or soft_capacity_only
    if not doctor_acceptable_for_static:
        raise SystemExit(f"daz_foundation_doctor_unacceptable:{failed_checks}")

    probe = probe_gold_volume_sources()
    probe_dict = _jsonable(asdict(probe) if is_dataclass(probe) else probe.to_dict())
    daz_source = probe_dict["sources"]["daz"]
    gold_slice = {
        "map_id": probe_dict["map_id"],
        "removable_drive_letters_present": probe_dict["removable_drive_letters_present"],
        "daz": daz_source,
        "entry_count_f_daz": entry_count,
        "entry_names_f_daz": entry_names,
        "read_when_present_only": probe_dict["claim_boundary"]["read_when_present_only"],
    }
    GOLD_SLICE.write_text(json.dumps(gold_slice, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not (
        daz_source.get("present")
        and daz_source.get("selected_root") == r"F:\DAZ"
        and daz_source.get("candidates", [{}])[0].get("readable")
        and daz_source.get("candidates", [{}])[0].get("markers_ok")
    ):
        raise SystemExit("gold_volume_daz_not_present_readable")

    pytest = _run([sys.executable, "-m", "pytest", *FOCUSED_TESTS, "-q"])
    summary = [line for line in pytest.stdout.strip().splitlines() if line][-3:]
    if pytest.returncode != 0:
        print(pytest.stdout)
        print(pytest.stderr)
        raise SystemExit(f"pytest_failed:{pytest.returncode}")

    # Re-seal binders AFTER pytest so the consolidated seal binds the final bytes
    # even if parallel agents rewrite shared binder paths mid-wave.
    for cmd in (
        [
            sys.executable,
            "-m",
            "maskfactory.cli",
            "daz",
            "recipes",
            "seal-validation-static-contracts",
            "--output",
            str(VALIDATION),
        ],
        [
            sys.executable,
            "-m",
            "maskfactory.cli",
            "daz",
            "recipes",
            "seal-ops-static-contracts",
            "--output",
            str(OPS),
        ],
        [
            sys.executable,
            "-m",
            "maskfactory.cli",
            "daz",
            "recipes",
            "seal-coverage-planner-static",
            "--output",
            str(COVERAGE),
        ],
    ):
        sealed = _run(cmd)
        if sealed.returncode != 0:
            print(sealed.stdout)
            print(sealed.stderr)
            raise SystemExit(f"binder_seal_failed:{cmd[-1]}:{sealed.returncode}")

    binders = {
        "validation_static_contracts": _binder(VALIDATION),
        "ops_static_contracts": _binder(OPS),
        "coverage_planner_static": _binder(COVERAGE),
        "procedural_primitive_bundle": _binder(PROC_PRIM),
    }

    document = {
        "artifact_type": "daz_stream_static_reverify",
        "schema_version": "1.0.0",
        "proof_tier": "STATIC_PASS",
        "authority": "daz_validation_ops_coverage_static_reverify_host_only_read_when_present",
        "recorded_at": "2026-07-20T14:49:00Z",
        "stream": "daz_validation_ops_coverage",
        "result": "pass_daz_validation_ops_coverage_static_reverify_read_when_present",
        "f_daz_read_when_present": {
            "present": True,
            "root": r"F:\DAZ",
            "entry_count": entry_count,
            "entry_names": entry_names,
            "root_uuid": root_identity.get("root_uuid"),
            "volume_unique_id": root_identity.get("volume_unique_id"),
            "gold_volume_source": {
                "map_id": gold_slice["map_id"],
                "role": daz_source.get("role"),
                "selected_root": daz_source.get("selected_root"),
                "selected_media": daz_source.get("selected_media"),
                "present": daz_source.get("present"),
                "readable": daz_source.get("candidates", [{}])[0].get("readable"),
                "markers_ok": daz_source.get("candidates", [{}])[0].get("markers_ok"),
                "dataset_hints_present": daz_source.get("dataset_hints_present"),
            },
            "prior_f_restored_seal": (
                PRIOR_F_RESTORED.relative_to(REPO).as_posix()
                if PRIOR_F_RESTORED.is_file()
                else None
            ),
            "prior_f_restored_seal_sha256": (
                _file_sha(PRIOR_F_RESTORED) if PRIOR_F_RESTORED.is_file() else None
            ),
            "note": (
                "Removable F:\\DAZ present with exactly 26 top-level entries; "
                "gold_volume_sources daz candidate selected (read-when-present). "
                "Still removable USB — not a fixed second disk for Docker VHDX. "
                "Binders re-sealed after focused pytest to defeat parallel overwrite races."
            ),
        },
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
            "acceptable_for_static_reverify": doctor_acceptable_for_static,
            "soft_capacity_only": soft_capacity_only,
            "storage_level": storage_level,
            "root": r"F:\DAZ",
            "free_gib": free_gib,
            "failed_checks": failed_checks,
            "note": (
                "storage soft: acquisition_pool_capacity_safe refuses new_work; "
                "not a hard storage block. Static binders still valid."
                if soft_capacity_only
                else None
            ),
        },
        "binders": binders,
        "gold_volume_slice_path": GOLD_SLICE.relative_to(REPO).as_posix(),
        "gold_volume_slice_sha256": _file_sha(GOLD_SLICE),
        "focused_tests": FOCUSED_TESTS,
        "pytest_exit_code": pytest.returncode,
        "pytest_summary": summary,
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

    # Immediate post-write consistency check against binder files on disk.
    for key, path in (
        ("validation_static_contracts", VALIDATION),
        ("ops_static_contracts", OPS),
        ("coverage_planner_static", COVERAGE),
    ):
        live = _binder(path)
        if live["file_sha256"] != binders[key]["file_sha256"]:
            raise SystemExit(f"binder_race_after_seal:{key}")

    print(OUTPUT.relative_to(REPO).as_posix(), document["self_sha256"])
    print("pytest_exit_code", pytest.returncode)
    print("\n".join(summary))
    print(
        "binders",
        {k: v["report_id"] for k, v in binders.items() if v.get("report_id")},
    )
    print(
        "doctor",
        {
            "passed": doctor_passed,
            "soft_capacity_only": soft_capacity_only,
            "free_gib": free_gib,
            "failed_checks": failed_checks,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
