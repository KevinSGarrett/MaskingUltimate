from __future__ import annotations

import json
import shutil
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image

from maskfactory.autonomy.package_semantic_alignment import (
    PackageSemanticAlignmentError,
    build_semantic_requalification_plan,
    deterministic_qa_sha256,
    execute_semantic_requalification_batch,
    final_mask_set_sha256,
    publish_semantic_relabel_versions,
    semantic_alignment_report_sha256,
    validate_package_semantic_alignment,
)
from maskfactory.io.hashing import sha256_file
from maskfactory.io.png_strict import write_label_map
from maskfactory.qa.checks import QcResult
from maskfactory.vlm.critic_authority import (
    certificate_sha256,
    evaluate_pass_quorum,
)
from maskfactory.vlm.critic_catalog import canonical_sha256, load_catalog

NOW = datetime(2026, 7, 22, 6, 0, tzinfo=UTC)


def _catalog() -> dict:
    catalog = deepcopy(load_catalog())
    for index, role in ((5, "primary_visual_critic"), (3, "independent_juror")):
        model = catalog["models"][index]
        model["lifecycle"] = "promoted"
        model["assigned_roles"] = [role]
        model["artifact_sha256"] = f"{index + 1:x}" * 64
        model["calibration"] = {
            "status": "pass",
            "report_sha256": f"{index + 7:x}" * 64,
        }
        model["private_endpoint"] = f"http://127.0.0.1:{19100 + index}"
    catalog["sha256"] = canonical_sha256(
        {key: value for key, value in catalog.items() if key != "sha256"}
    )
    return catalog


def _certificate(catalog: dict, index: int, role: str) -> dict:
    model = catalog["models"][index]
    certificate = {
        "schema_version": "1.0.0",
        "certificate_id": f"semantic-{model['model_id']}",
        "role_id": role,
        "model_id": model["model_id"],
        "family_id": model["family_id"],
        "catalog_sha256": catalog["sha256"],
        "revision": model["revision"],
        "artifact_sha256": model["artifact_sha256"],
        "calibration_report_sha256": model["calibration"]["report_sha256"],
        "prompt_sha256": "a" * 64,
        "runtime_sha256": "b" * 64,
        "issued_at": "2026-07-21T00:00:00Z",
        "qualified_until": "2026-08-21T00:00:00Z",
        "status": "pass",
    }
    certificate["certificate_sha256"] = certificate_sha256(certificate)
    return certificate


def _package(tmp_path: Path) -> tuple[Path, dict, tuple[QcResult, ...]]:
    package = tmp_path / "img_semantic" / "instances" / "p0"
    (package / "masks").mkdir(parents=True)
    Image.new("RGB", (12, 10), "gray").save(package / "source.png")
    part = np.zeros((10, 12), dtype=np.uint16)
    part[2:8, 3:9] = 18
    material = np.zeros((10, 12), dtype=np.uint8)
    write_label_map(package / "label_map_part.png", part, bits=16)
    write_label_map(package / "label_map_material.png", material, bits=8)
    Image.fromarray((part == 18).astype(np.uint8) * 255, mode="L").save(
        package / "masks" / "left_forearm.png"
    )
    (package / "qa_panels").mkdir()
    Image.new("RGB", (24, 10), "gray").save(package / "qa_panels" / "left_forearm.png")
    manifest = {
        "image_id": "img_semantic",
        "mask_ontology_version": "body_parts_v1",
        "parts": {
            "left_forearm": {
                "status": "draft_model_generated",
                "mask_file": "masks/left_forearm.png",
            }
        },
    }
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    results = (
        QcResult("QC-001", "dimensions_match_source", True, "all match", "BLOCK"),
        QcResult("QC-006", "hash_integrity", True, "all match", "BLOCK"),
    )
    return package, manifest, results


def _report(
    package: Path,
    manifest: dict,
    results: tuple[QcResult, ...],
    catalog: dict,
    certificates: tuple[dict, ...],
) -> dict:
    quorum = evaluate_pass_quorum(certificates, catalog, now=NOW, deterministic_hard_veto=False)
    report = {
        "schema_version": "1.0.0",
        "status": "pass",
        "authority_claimed": False,
        "package_identity": {
            "image_id": "img_semantic",
            "instance_id": "p0",
            "ontology_version": "body_parts_v1",
            "source_sha256": sha256_file(package / "source.png"),
            "final_mask_set_sha256": final_mask_set_sha256(package, manifest),
        },
        "targets": [
            {
                "label_id": "left_forearm",
                "mask_sha256": sha256_file(package / "masks" / "left_forearm.png"),
                "verdict": "pass",
                "decision_sha256": "c" * 64,
            }
        ],
        "deterministic_hard_veto": False,
        "deterministic_qa_sha256": deterministic_qa_sha256(results),
        "panel_set_sha256": "d" * 64,
        "critic_decisions": [
            {
                "certificate_sha256": certificate["certificate_sha256"],
                "role_id": certificate["role_id"],
                "model_id": certificate["model_id"],
                "family_id": certificate["family_id"],
                "verdict": "pass",
                "cited_labels": ["left_forearm"],
                "decision_sha256": f"{index + 5:x}" * 64,
            }
            for index, certificate in enumerate(certificates)
        ],
        "quorum_sha256": quorum["quorum_sha256"],
    }
    report["report_sha256"] = semantic_alignment_report_sha256(report)
    return report


def test_exact_package_and_current_independent_quorum_pass(tmp_path: Path) -> None:
    package, manifest, results = _package(tmp_path)
    catalog = _catalog()
    certificates = (
        _certificate(catalog, 5, "primary_visual_critic"),
        _certificate(catalog, 3, "independent_juror"),
    )
    report = _report(package, manifest, results, catalog, certificates)
    result = validate_package_semantic_alignment(
        report,
        package_root=package,
        manifest=manifest,
        deterministic_results=results,
        critic_certificates=certificates,
        critic_catalog=catalog,
        now=NOW,
    )
    assert result["status"] == "pass"
    assert result["covered_labels"] == ["left_forearm"]
    assert result["report_sha256"] == report["report_sha256"]


def test_bulk_plan_batches_all_valid_cases_and_reports_only_exceptions(
    tmp_path: Path,
) -> None:
    from maskfactory.autonomy.package_semantic_alignment import (
        build_semantic_requalification_plan,
    )

    fixture, _, _ = _package(tmp_path / "fixture")
    packages = tmp_path / "packages"
    for index in range(3):
        target = packages / f"img_{index:02d}"
        shutil.copytree(fixture.parents[1], target)
        manifest_path = target / "instances" / "p0" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["image_id"] = f"img_{index:02d}"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (packages / "img_02" / "instances" / "p0" / "qa_panels" / "left_forearm.png").unlink()

    first = build_semantic_requalification_plan(packages, batch_size=2)
    second = build_semantic_requalification_plan(packages, batch_size=2)

    assert first == second
    assert first["execution_mode"] == "bulk_by_default"
    assert first["operator_interruption_policy"] == "compact_exception_report_only"
    assert first["human_review_policy"] == "optional_exception_path_not_default_throughput"
    assert first["case_count"] == 2
    assert first["exception_count"] == 1
    assert len(first["batches"]) == 1
    assert first["batches"][0]["required_roles"] == [
        "primary_visual_critic",
        "independent_juror",
    ]
    assert first["exceptions"][0]["action"] == "abstain_and_report"

    from maskfactory.cli import main

    output = tmp_path / "bulk_plan.json"
    result = CliRunner().invoke(
        main,
        [
            "autonomous-semantic-requalification-plan",
            "--root",
            str(packages),
            "--output",
            str(output),
            "--batch-size",
            "2",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(output.read_text(encoding="utf-8")) == first
    summary = json.loads(result.output)
    assert summary["exception_count"] == 1
    assert summary["contact_sheet_count"] == 1
    contact_root = tmp_path / "bulk_plan_contact_sheets"
    contact_manifest = json.loads(
        (contact_root / "contact_sheet_manifest.json").read_text(encoding="utf-8")
    )
    assert contact_manifest["plan_sha256"] == first["plan_sha256"]
    assert contact_manifest["sheets"][0]["case_ids"] == first["batches"][0]["case_ids"]
    assert (contact_root / contact_manifest["sheets"][0]["file"]).is_file()


def _batch_review(
    plan: dict,
    batch: dict,
    certificate: dict,
    *,
    verdict: str,
    proposed_label_id: str | None = None,
) -> dict:
    decisions = []
    cases = {case["case_id"]: case for case in plan["cases"]}
    for case_id in batch["case_ids"]:
        targets = [
            {
                "label_id": target["label_id"],
                "mask_sha256": target["mask_sha256"],
                "panel_sha256": target["panel_sha256"],
                "verdict": verdict,
                "proposed_label_id": proposed_label_id if verdict == "relabel" else None,
            }
            for target in cases[case_id]["targets"]
        ]
        decision = {"case_id": case_id, "targets": targets}
        from maskfactory.vlm.critic_catalog import canonical_sha256

        decision["decision_sha256"] = canonical_sha256(decision)
        decisions.append(decision)
    review = {
        "schema_version": "1.0.0",
        "plan_sha256": plan["plan_sha256"],
        "batch_sha256": batch["batch_sha256"],
        "role_id": certificate["role_id"],
        "certificate_sha256": certificate["certificate_sha256"],
        "model_id": certificate["model_id"],
        "family_id": certificate["family_id"],
        "case_decisions": decisions,
    }
    review["review_sha256"] = canonical_sha256(review)
    return review


def test_bulk_executor_accepts_exact_quorum_without_mutating_packages(tmp_path: Path) -> None:
    fixture, _, _ = _package(tmp_path / "fixture")
    packages = tmp_path / "packages"
    target = packages / "img_00"
    shutil.copytree(fixture.parents[1], target)
    plan = build_semantic_requalification_plan(packages, batch_size=1)
    catalog = _catalog()
    certificates = (
        _certificate(catalog, 5, "primary_visual_critic"),
        _certificate(catalog, 3, "independent_juror"),
    )
    batch = plan["batches"][0]
    reviews = tuple(
        _batch_review(plan, batch, certificate, verdict="pass") for certificate in certificates
    )
    before = (target / "instances" / "p0" / "manifest.json").read_bytes()
    result = execute_semantic_requalification_batch(
        plan,
        batch_index=0,
        critic_reviews=reviews,
        critic_certificates=certificates,
        critic_catalog=catalog,
        packages_root=packages,
        now=NOW,
    )
    assert result["counts"]["accept_exact_label"] == 1
    assert result["mutation_performed"] is False
    assert result["exceptions"] == []
    assert (target / "instances" / "p0" / "manifest.json").read_bytes() == before

    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    review_paths = []
    certificate_paths = []
    for index, (review, certificate) in enumerate(zip(reviews, certificates, strict=True)):
        review_path = tmp_path / f"review_{index}.json"
        certificate_path = tmp_path / f"certificate_{index}.json"
        review_path.write_text(json.dumps(review), encoding="utf-8")
        certificate_path.write_text(json.dumps(certificate), encoding="utf-8")
        review_paths.append(review_path)
        certificate_paths.append(certificate_path)
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    output = tmp_path / "resolved.json"
    from maskfactory.cli import main

    arguments = [
        "autonomous-semantic-requalification-execute",
        "--plan",
        str(plan_path),
        "--batch-index",
        "0",
        "--catalog",
        str(catalog_path),
        "--root",
        str(packages),
        "--output",
        str(output),
        "--as-of",
        NOW.isoformat(),
    ]
    for review_path in review_paths:
        arguments.extend(("--review", str(review_path)))
    for certificate_path in certificate_paths:
        arguments.extend(("--critic-certificate", str(certificate_path)))
    cli_result = CliRunner().invoke(main, arguments)
    assert cli_result.exit_code == 0, cli_result.output
    assert (
        json.loads(output.read_text(encoding="utf-8"))["result_sha256"] == result["result_sha256"]
    )
    assert json.loads(cli_result.output)["exception_count"] == 0


def test_bulk_executor_emits_consensus_relabel_proposal_without_rewriting(
    tmp_path: Path,
) -> None:
    fixture, _, _ = _package(tmp_path / "fixture")
    packages = tmp_path / "packages"
    target = packages / "img_00"
    shutil.copytree(fixture.parents[1], target)
    plan = build_semantic_requalification_plan(packages, batch_size=1)
    catalog = _catalog()
    certificates = (
        _certificate(catalog, 5, "primary_visual_critic"),
        _certificate(catalog, 3, "independent_juror"),
    )
    batch = plan["batches"][0]
    reviews = tuple(
        _batch_review(
            plan,
            batch,
            certificate,
            verdict="relabel",
            proposed_label_id="right_upper_arm",
        )
        for certificate in certificates
    )
    result = execute_semantic_requalification_batch(
        plan,
        batch_index=0,
        critic_reviews=reviews,
        critic_certificates=certificates,
        critic_catalog=catalog,
        packages_root=packages,
        now=NOW,
    )
    assert result["counts"]["relabel_new_immutable_version"] == 1
    assert result["outcomes"][0]["relabel_map"] == {"left_forearm": "right_upper_arm"}
    assert result["mutation_performed"] is False


def test_bulk_relabel_publisher_creates_immutable_candidate_and_preserves_parent(
    tmp_path: Path,
) -> None:
    fixture, _, _ = _package(tmp_path / "fixture")
    packages = tmp_path / "packages"
    parent = packages / "img_00"
    shutil.copytree(fixture.parents[1], parent)
    plan = build_semantic_requalification_plan(packages, batch_size=1)
    catalog = _catalog()
    certificates = (
        _certificate(catalog, 5, "primary_visual_critic"),
        _certificate(catalog, 3, "independent_juror"),
    )
    batch = plan["batches"][0]
    reviews = tuple(
        _batch_review(
            plan,
            batch,
            certificate,
            verdict="relabel",
            proposed_label_id="right_upper_arm",
        )
        for certificate in certificates
    )
    result = execute_semantic_requalification_batch(
        plan,
        batch_index=0,
        critic_reviews=reviews,
        critic_certificates=certificates,
        critic_catalog=catalog,
        packages_root=packages,
        now=NOW,
    )
    parent_package = parent / "instances" / "p0"
    before = {
        path.relative_to(parent_package): path.read_bytes()
        for path in parent_package.rglob("*")
        if path.is_file()
    }
    publication = publish_semantic_relabel_versions(
        plan,
        result,
        packages_root=packages,
        publication_root=tmp_path / "published",
        ontology_path=Path("configs/ontology.yaml"),
        now=NOW,
    )
    assert publication["published_count"] == 1
    published = Path(publication["published"][0]["package"])
    manifest = json.loads((published / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["workflow_status"] == "machine_candidate"
    assert manifest["truth_tier"] == "machine_candidate"
    assert "left_forearm" not in manifest["parts"]
    assert manifest["parts"]["right_upper_arm"]["mask_file"] == "masks/right_upper_arm.png"
    assert (published / "masks" / "right_upper_arm.png").read_bytes() == before[
        Path("masks/left_forearm.png")
    ]
    assert (published / "source.png").read_bytes() == before[Path("source.png")]
    assert set(np.unique(np.asarray(Image.open(published / "label_map_part.png")))) == {0, 15}
    assert (
        json.loads((published / ".maskfactory_frozen.json").read_text(encoding="utf-8"))[
            "authority_claimed"
        ]
        is False
    )
    assert {
        path.relative_to(parent_package): path.read_bytes()
        for path in parent_package.rglob("*")
        if path.is_file()
    } == before

    repeated = publish_semantic_relabel_versions(
        plan,
        result,
        packages_root=packages,
        publication_root=tmp_path / "published",
        ontology_path=Path("configs/ontology.yaml"),
        now=NOW,
    )
    assert repeated == publication

    plan_path = tmp_path / "publish_plan.json"
    result_path = tmp_path / "publish_result.json"
    receipt_path = tmp_path / "publish_receipt.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    result_path.write_text(json.dumps(result), encoding="utf-8")
    from maskfactory.cli import main

    cli_result = CliRunner().invoke(
        main,
        [
            "autonomous-semantic-requalification-publish",
            "--plan",
            str(plan_path),
            "--result",
            str(result_path),
            "--root",
            str(packages),
            "--publication-root",
            str(tmp_path / "published_cli"),
            "--ontology",
            "configs/ontology.yaml",
            "--output",
            str(receipt_path),
            "--as-of",
            NOW.isoformat(),
        ],
    )
    assert cli_result.exit_code == 0, cli_result.output
    assert json.loads(cli_result.output)["requires_recertification"] is True
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["published_count"] == 1

    (published / "source.png").write_bytes(b"drift")
    with pytest.raises(PackageSemanticAlignmentError, match="immutable revision drifted"):
        publish_semantic_relabel_versions(
            plan,
            result,
            packages_root=packages,
            publication_root=tmp_path / "published",
            ontology_path=Path("configs/ontology.yaml"),
            now=NOW,
        )


def test_bulk_relabel_publisher_rejects_unknown_label_and_parent_drift(tmp_path: Path) -> None:
    fixture, _, _ = _package(tmp_path / "fixture")
    packages = tmp_path / "packages"
    shutil.copytree(fixture.parents[1], packages / "img_00")
    plan = build_semantic_requalification_plan(packages, batch_size=1)
    catalog = _catalog()
    certificates = (
        _certificate(catalog, 5, "primary_visual_critic"),
        _certificate(catalog, 3, "independent_juror"),
    )
    batch = plan["batches"][0]
    reviews = tuple(
        _batch_review(plan, batch, certificate, verdict="relabel", proposed_label_id="not_real")
        for certificate in certificates
    )
    result = execute_semantic_requalification_batch(
        plan,
        batch_index=0,
        critic_reviews=reviews,
        critic_certificates=certificates,
        critic_catalog=catalog,
        packages_root=packages,
        now=NOW,
    )
    with pytest.raises(PackageSemanticAlignmentError, match="unknown ontology label"):
        publish_semantic_relabel_versions(
            plan,
            result,
            packages_root=packages,
            publication_root=tmp_path / "published",
            ontology_path=Path("configs/ontology.yaml"),
            now=NOW,
        )
    (packages / "img_00" / "instances" / "p0" / "manifest.json").write_text("{}")
    with pytest.raises(PackageSemanticAlignmentError, match="parent manifest drifted"):
        publish_semantic_relabel_versions(
            plan,
            result,
            packages_root=packages,
            publication_root=tmp_path / "published",
            ontology_path=Path("configs/ontology.yaml"),
            now=NOW,
        )


def test_bulk_executor_abstains_one_drifted_case_and_continues(tmp_path: Path) -> None:
    fixture, _, _ = _package(tmp_path / "fixture")
    packages = tmp_path / "packages"
    for index in range(2):
        shutil.copytree(fixture.parents[1], packages / f"img_{index:02d}")
    plan = build_semantic_requalification_plan(packages, batch_size=2)
    catalog = _catalog()
    certificates = (
        _certificate(catalog, 5, "primary_visual_critic"),
        _certificate(catalog, 3, "independent_juror"),
    )
    batch = plan["batches"][0]
    reviews = tuple(
        _batch_review(plan, batch, certificate, verdict="pass") for certificate in certificates
    )
    Image.new("RGB", (12, 10), "red").save(packages / "img_00" / "instances" / "p0" / "source.png")
    result = execute_semantic_requalification_batch(
        plan,
        batch_index=0,
        critic_reviews=reviews,
        critic_certificates=certificates,
        critic_catalog=catalog,
        packages_root=packages,
        now=NOW,
    )
    assert len(result["outcomes"]) == 1
    assert result["counts"]["accept_exact_label"] == 1
    assert len(result["exceptions"]) == 1
    assert result["exceptions"][0]["action"] == "abstain_and_report"


@pytest.mark.parametrize(
    ("primary_verdict", "independent_verdict", "expected"),
    [
        ("pass", "relabel", "abstain"),
        ("pass", "reject", "reject"),
        ("pass", "abstain", "abstain"),
    ],
)
def test_bulk_executor_resolves_disagreement_fail_closed(
    tmp_path: Path,
    primary_verdict: str,
    independent_verdict: str,
    expected: str,
) -> None:
    fixture, _, _ = _package(tmp_path / "fixture")
    packages = tmp_path / "packages"
    shutil.copytree(fixture.parents[1], packages / "img_00")
    plan = build_semantic_requalification_plan(packages, batch_size=1)
    catalog = _catalog()
    certificates = (
        _certificate(catalog, 5, "primary_visual_critic"),
        _certificate(catalog, 3, "independent_juror"),
    )
    batch = plan["batches"][0]
    reviews = (
        _batch_review(plan, batch, certificates[0], verdict=primary_verdict),
        _batch_review(
            plan,
            batch,
            certificates[1],
            verdict=independent_verdict,
            proposed_label_id=("right_upper_arm" if independent_verdict == "relabel" else None),
        ),
    )
    result = execute_semantic_requalification_batch(
        plan,
        batch_index=0,
        critic_reviews=reviews,
        critic_certificates=certificates,
        critic_catalog=catalog,
        packages_root=packages,
        now=NOW,
    )
    assert result["counts"][expected] == 1
    assert result["mutation_performed"] is False


def test_bulk_executor_rejects_review_hash_drift_before_case_resolution(
    tmp_path: Path,
) -> None:
    fixture, _, _ = _package(tmp_path / "fixture")
    packages = tmp_path / "packages"
    shutil.copytree(fixture.parents[1], packages / "img_00")
    plan = build_semantic_requalification_plan(packages, batch_size=1)
    catalog = _catalog()
    certificates = (
        _certificate(catalog, 5, "primary_visual_critic"),
        _certificate(catalog, 3, "independent_juror"),
    )
    batch = plan["batches"][0]
    reviews = [
        _batch_review(plan, batch, certificate, verdict="pass") for certificate in certificates
    ]
    reviews[0]["case_decisions"][0]["targets"][0]["verdict"] = "reject"
    with pytest.raises(PackageSemanticAlignmentError, match="review hash mismatch"):
        execute_semantic_requalification_batch(
            plan,
            batch_index=0,
            critic_reviews=reviews,
            critic_certificates=certificates,
            critic_catalog=catalog,
            packages_root=packages,
            now=NOW,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("mask_hash", "mask hash drifted"),
        ("target_defect", "target did not pass"),
        ("missing_critic", "independent critic quorum"),
        ("hard_veto", "cannot clear a hard veto"),
    ],
)
def test_semantic_alignment_fails_closed_on_authority_or_pixel_drift(
    tmp_path: Path, mutation: str, message: str
) -> None:
    package, manifest, results = _package(tmp_path)
    catalog = _catalog()
    certificates = (
        _certificate(catalog, 5, "primary_visual_critic"),
        _certificate(catalog, 3, "independent_juror"),
    )
    report = _report(package, manifest, results, catalog, certificates)
    active_certificates = certificates
    if mutation == "mask_hash":
        report["targets"][0]["mask_sha256"] = "0" * 64
    elif mutation == "target_defect":
        report["targets"][0]["verdict"] = "defect"
    elif mutation == "missing_critic":
        active_certificates = certificates[:1]
    else:
        report["deterministic_hard_veto"] = True
    report["report_sha256"] = semantic_alignment_report_sha256(report)

    with pytest.raises(PackageSemanticAlignmentError, match=message):
        validate_package_semantic_alignment(
            report,
            package_root=package,
            manifest=manifest,
            deterministic_results=results,
            critic_certificates=active_certificates,
            critic_catalog=catalog,
            now=NOW,
        )
