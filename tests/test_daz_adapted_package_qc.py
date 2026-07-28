from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from maskfactory.daz.package_qc import (  # noqa: E402
    AdaptedPackageQcError,
    load_adapted_package_qc_policy,
    run_adapted_package_qc,
    validate_adapted_package_qc_policy,
    validate_adapted_package_qc_report,
)
from maskfactory.daz.s00_adapter import adapt_accepted_scene  # noqa: E402
from test_daz_s00_adapter import _fixture as _adapter_fixture  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "configs" / "daz" / "adapted_package_qc.yaml"
ONTOLOGY = ROOT / "configs" / "ontology.yaml"


def _fixture(tmp_path: Path, owner_count: int = 2):
    adapter_inputs = _adapter_fixture(tmp_path / "adapter", owner_count)
    adapter_report, adapted_root, _published = adapt_accepted_scene(**adapter_inputs)
    return {
        "adapted_root": adapted_root,
        "adapter_report": adapter_report,
        "package_contract": adapter_inputs["package_contract"],
        "policy": load_adapted_package_qc_policy(POLICY),
        "ontology_source": ONTOLOGY,
        "output_root": tmp_path / "qc_reports",
    }


def _results(report: dict) -> dict[str, dict]:
    return {row["check_id"]: row for row in report["results"]}


def _tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.mark.parametrize("owner_count", [1, 2, 3, 4])
def test_clean_adapted_packages_pass_all_required_qc(tmp_path: Path, owner_count: int) -> None:
    fixture = _fixture(tmp_path, owner_count)
    before = _tree(fixture["adapted_root"])
    report, path, published = run_adapted_package_qc(**fixture)
    validate_adapted_package_qc_report(report)
    assert published is True and path.is_file()
    assert _tree(fixture["adapted_root"]) == before
    assert report["summary"] == {
        "passed": True,
        "required_count": 21,
        "required_pass_count": 21,
        "not_applicable_count": 3,
        "failed_count": 0,
        "existing_qc_count": 17,
        "daz_qc_count": 7,
        "freeze_eligible": True,
    }
    results = _results(report)
    assert set(results) == {
        "QC-001",
        "QC-002",
        "QC-003",
        "QC-004",
        "QC-005",
        "QC-006",
        "QC-007",
        "QC-008",
        "QC-009",
        "QC-010",
        "QC-011",
        "QC-012",
        "QC-013",
        "QC-035",
        "QC-036",
        "QC-037",
        "QC-038",
        *(f"DAZ-QC-{index:03d}" for index in range(1, 8)),
    }
    assert results["QC-008"]["status"] == "not_applicable"
    assert results["QC-010"]["status"] == "not_applicable"
    assert results["QC-037"]["status"] == "not_applicable"


def test_qc_publication_is_immutable_and_idempotent(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    first, path, published = run_adapted_package_qc(**fixture)
    second, same, republished = run_adapted_package_qc(**fixture)
    assert published is True and republished is False
    assert first == second and path == same
    path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(AdaptedPackageQcError, match="adapted_qc_publication_conflict"):
        run_adapted_package_qc(**fixture)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("existing_qc", "required"), ["QC-001"]),
        (("existing_qc", "not_applicable", "QC-037"), "always skip"),
        (("daz_qc", "required"), ["DAZ-QC-001"]),
        (("allowed_protected_ids",), [0, 50, 51]),
        (("publication", "failure_blocks_freeze"), False),
    ],
)
def test_qc_policy_cannot_drop_checks_or_weaken_freeze(path: tuple[str, ...], value) -> None:
    policy = load_adapted_package_qc_policy(POLICY)
    target = policy
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(AdaptedPackageQcError, match="adapted_qc_policy_identity_invalid"):
        validate_adapted_package_qc_policy(policy)


def test_source_byte_tamper_blocks_hash_and_freeze(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    path = fixture["adapted_root"] / "packages" / "p0" / "qa_report.json"
    path.write_bytes(path.read_bytes() + b" ")
    report, _path, _published = run_adapted_package_qc(**fixture)
    results = _results(report)
    assert results["QC-006"]["status"] == "fail"
    assert results["DAZ-QC-003"]["status"] == "fail"
    assert report["summary"]["freeze_eligible"] is False


def test_illegal_part_id_is_detected_by_existing_and_daz_checks(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    path = fixture["adapted_root"] / "packages" / "p0" / "indexed_part.png"
    with Image.open(path) as image:
        array = np.asarray(image).copy()
    array[np.nonzero(array)[0][0], np.nonzero(array)[1][0]] = 65535
    Image.fromarray(array.astype(np.uint16)).save(path, format="PNG")
    report, _path, _published = run_adapted_package_qc(**fixture)
    results = _results(report)
    assert results["QC-004"]["status"] == "fail"
    assert results["QC-006"]["status"] == "fail"
    assert report["summary"]["passed"] is False


def test_cross_person_overlap_and_bleed_block_multi_qc(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, 2)
    p0 = fixture["adapted_root"] / "packages" / "p0" / "full_body.png"
    p1 = fixture["adapted_root"] / "packages" / "p1" / "full_body.png"
    p1.write_bytes(p0.read_bytes())
    report, _path, _published = run_adapted_package_qc(**fixture)
    results = _results(report)
    assert results["QC-035"]["status"] == "fail"
    assert results["QC-036"]["status"] == "fail"
    assert report["summary"]["freeze_eligible"] is False


def test_manifest_truth_or_human_authority_tamper_blocks_qc(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    path = fixture["adapted_root"] / "packages" / "p0" / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["truth_partition"] = "holdout"
    manifest["reviewer_identity"] = "fabricated"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    report, _path, _published = run_adapted_package_qc(**fixture)
    results = _results(report)
    assert results["QC-005"]["status"] == "fail"
    assert results["DAZ-QC-005"]["status"] == "fail"
    assert results["DAZ-QC-006"]["status"] == "fail"


def test_contract_and_adapter_report_must_remain_hash_bound(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture["package_contract"]["image_id"] = "rebound_image"
    with pytest.raises(AdaptedPackageQcError, match="adapted_qc_contract_hash_invalid"):
        run_adapted_package_qc(**fixture)
    fixture = _fixture(tmp_path / "adapter")
    fixture["adapter_report"]["summary"]["package_count"] += 1
    with pytest.raises(ValueError):
        run_adapted_package_qc(**fixture)


def test_qc_report_hash_and_closed_result_schema_detect_tamper(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    report, _path, _published = run_adapted_package_qc(**fixture)
    tampered = copy.deepcopy(report)
    tampered["summary"]["required_pass_count"] -= 1
    with pytest.raises(AdaptedPackageQcError, match="adapted_qc_report_hash_invalid"):
        validate_adapted_package_qc_report(tampered)
    tampered = copy.deepcopy(report)
    tampered["results"][0]["status"] = "warn"
    with pytest.raises(ValueError):
        validate_adapted_package_qc_report(tampered)
