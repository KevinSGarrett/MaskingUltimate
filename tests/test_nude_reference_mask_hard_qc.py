from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.authority.operational_certificate import canonical_decoded_raster_sha256
from maskfactory.nude_box_mask_generation import generate_box_prompt_provider_batch
from maskfactory.nude_person_catalog import compare_person_proposal_catalogs
from maskfactory.nude_reference_mask_hard_qc import (
    NudeReferenceMaskHardQcError,
    build_reference_mask_hard_qc_stage_receipt,
    run_reference_person_mask_hard_qc,
    validate_reference_mask_hard_qc_stage_receipt,
    validate_reference_person_mask_hard_qc,
)
from maskfactory.nude_reference_strict_visual_review import (
    NudeReferenceStrictVisualReviewError,
    VisualReviewerIdentity,
    build_reference_strict_visual_stage_receipt,
    run_reference_person_strict_visual_review,
    validate_reference_person_strict_visual_review,
    validate_reference_strict_visual_stage_receipt,
)
from maskfactory.providers.contracts import MaskProposal, ProviderIdentity
from maskfactory.vlm.critic_authority import certificate_sha256
from maskfactory.vlm.critic_catalog import canonical_sha256, load_catalog
from maskfactory.vlm.target_contract import target_contract_sha256

NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)


def _sha(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class _Provider:
    def __init__(self, *, overlap: bool = False, collapsed: bool = False):
        self.identity = ProviderIdentity(
            "provider-a", "interactive_segmenter", "family-a", "a" * 40, "b" * 64
        )
        self.overlap = overlap
        self.collapsed = collapsed

    def embed(self, image):
        return np.asarray(image).shape[:2]

    def refine(self, embedding, *, prompt):
        height, width = embedding
        left, top, right, bottom = prompt["box_xyxy"]
        point_x, point_y = prompt["positive_points"][0]
        mask = np.zeros((height, width), dtype=bool)
        if self.collapsed:
            mask[point_y, point_x] = True
        else:
            inset = 0 if self.overlap else 1
            mask[top + 1 : bottom - 1, left + inset : right - inset] = True
            mask[point_y, point_x] = True
        return (MaskProposal(mask, 0.9, self.identity, "prompt"),)


class _Reviewer:
    def __init__(self, role: str, family: str, responses, *, model_id=None, runtime="b" * 64):
        self.identity = VisualReviewerIdentity(role, model_id or f"{family}-model", family, runtime)
        self.responses = list(responses)
        self.calls = []

    def review(self, *, prompt, images):
        self.calls.append((prompt, images))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _visual_response(verdict="pass", confidence=0.9, problems=None):
    return json.dumps(
        {
            "verdict": verdict,
            "confidence": confidence,
            "observations": {
                name: f"inspected {name}"
                for name in (
                    "full_context",
                    "source_crop",
                    "mask",
                    "overlay",
                    "contour",
                    "neighbor_overlap",
                )
            },
            "problems": problems or [],
            "evidence": "complete per-view inspection",
        }
    )


def _critic_authority(*, same_family=False):
    catalog = deepcopy(load_catalog())
    assignments = ((5, "primary_visual_critic"), (2 if same_family else 3, "independent_juror"))
    certificates = []
    for index, role in assignments:
        model = catalog["models"][index]
        if role not in model["candidate_roles"]:
            model["candidate_roles"].append(role)
        model["lifecycle"] = "promoted"
        model["assigned_roles"] = [role]
        model["artifact_sha256"] = f"{index + 1:x}" * 64
        model["calibration"] = {"status": "pass", "report_sha256": f"{index + 5:x}" * 64}
        model["private_endpoint"] = f"http://127.0.0.1:{18100 + index}"
    catalog["sha256"] = canonical_sha256(
        {key: value for key, value in catalog.items() if key != "sha256"}
    )
    for index, role in assignments:
        model = catalog["models"][index]
        certificate = {
            "schema_version": "1.0.0",
            "certificate_id": f"cert-{model['model_id']}",
            "role_id": role,
            "model_id": model["model_id"],
            "family_id": model["family_id"],
            "catalog_sha256": catalog["sha256"],
            "revision": model["revision"],
            "artifact_sha256": model["artifact_sha256"],
            "calibration_report_sha256": model["calibration"]["report_sha256"],
            "prompt_sha256": "a" * 64,
            "runtime_sha256": "b" * 64,
            "issued_at": "2026-07-20T00:00:00Z",
            "qualified_until": "2026-08-20T00:00:00Z",
            "status": "pass",
        }
        certificate["certificate_sha256"] = certificate_sha256(certificate)
        certificates.append(certificate)
    reviewers = [
        _Reviewer(
            cert["role_id"], cert["family_id"], [_visual_response()], model_id=cert["model_id"]
        )
        for cert in certificates
    ]
    return catalog, certificates, reviewers


def _target_contracts(source: Path, batch: dict) -> dict:
    with Image.open(source) as opened:
        pixels = np.asarray(opened.convert("RGB"))
    source_decoded = canonical_decoded_raster_sha256(pixels, channel_layout="RGB")
    result = {"sample-a": {}}
    identity = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    for candidate in batch["records"][0]["candidates"]:
        person_index = candidate["person_index"]
        contract = {
            "schema_version": "2.0.0",
            "contract_id": f"sample-a-p{person_index}-person",
            "source": {
                "image_id": "sample-a",
                "encoded_sha256": batch["records"][0]["source_sha256"],
                "decoded_pixel_sha256": source_decoded,
                "width": 32,
                "height": 24,
                "decoder": {
                    "name": "Pillow",
                    "version": "test",
                    "exif_orientation": "applied",
                    "color_policy": "RGB",
                    "icc_policy": "converted_srgb",
                    "alpha_policy": "discarded",
                },
            },
            "owner": {
                "person_index": person_index,
                "character_instance_id": f"sample-a-p{person_index}",
                "person_mask_sha256": candidate["mask_sha256"],
            },
            "target": {
                "label_id": "person",
                "ontology_version": "2.0.0",
                "ontology_sha256": "d" * 64,
                "label_scale": "whole_person",
                "laterality": "none",
                "perspective": "character_perspective",
                "visibility_policy": "visible_only",
                "expected_state": "present",
                "inclusions": ["complete visible owned person"],
                "exclusions": ["background and other people"],
                "allowed_roi_xyxy": [0, 0, 32, 24],
                "overlap_policy": {
                    "protected_overlap_max_pixels": 0,
                    "cross_person_overlap_max_pixels": 0,
                    "containment_rule": "inside_owner_proposal",
                },
                "topology_policy": {
                    "minimum_components": 1,
                    "maximum_components": 16,
                    "holes_allowed": True,
                    "thin_structures_expected": True,
                },
                "context": {
                    "truncated": False,
                    "contact": False,
                    "self_occluded": False,
                    "cross_person_occluded": False,
                    "crop_edge": False,
                    "out_of_frame": False,
                },
            },
            "candidate": {
                "encoded_sha256": candidate["artifact_sha256"],
                "decoded_pixel_sha256": candidate["mask_sha256"],
                "width": 32,
                "height": 24,
                "binary_values": [0, 255],
                "coordinate_space": "canonical_source_pixels",
            },
            "protected_regions": [],
            "transforms": {
                "coordinate_space": "canonical_source_pixels",
                "chain": [
                    {
                        "operation": "identity",
                        "from_space": "canonical_source_pixels",
                        "to_space": "canonical_source_pixels",
                        "matrix": identity,
                        "inverse_matrix": identity,
                    }
                ],
                "round_trip_sha256": "e" * 64,
            },
            "package": {"package_id": "sample-a", "revision": 1, "parent_revision": None},
        }
        contract["contract_sha256"] = target_contract_sha256(contract)
        result["sample-a"][person_index] = contract
    return result


def _strict_kwargs(source, root, batch, hard_qc, tmp_path, reviewers=None):
    catalog, certificates, default_reviewers = _critic_authority()
    return {
        "provider_batch": batch,
        "hard_qc": hard_qc,
        "output_root": root,
        "source_paths": {"sample-a": source},
        "evidence_root": tmp_path / "visual",
        "reviewers": reviewers or default_reviewers,
        "target_contracts": _target_contracts(source, batch),
        "critic_catalog": catalog,
        "critic_certificates": certificates,
        "now": NOW,
    }


def _catalog(source_sha256: str, *, two_people: bool = False):
    proposals_a = [[2, 2, 18, 22]]
    proposals_b = [[3, 3, 17, 21]]
    if two_people:
        proposals_a.append([16, 2, 31, 22])
        proposals_b.append([17, 3, 30, 21])
    providers = []
    for provider_id, family_id, boxes, artifact in (
        ("detector-a", "detector-family-a", proposals_a, "1" * 64),
        ("detector-b", "detector-family-b", proposals_b, "2" * 64),
    ):
        providers.append(
            {
                "provider_id": provider_id,
                "family_id": family_id,
                "revision": "r1",
                "artifact_sha256": artifact,
                "source_sha256": source_sha256,
                "proposals": [
                    {
                        "bbox_xyxy": box,
                        "confidence": 0.9,
                        "label": "person",
                        "authority": "proposal_only",
                    }
                    for box in boxes
                ],
            }
        )
    return compare_person_proposal_catalogs(
        sample_id="sample-a",
        source_sha256=source_sha256,
        image_size=[32, 24],
        provider_records=providers,
        iou_min=0.5,
    )


def _fixture(tmp_path: Path, *, provider=None, two_people: bool = False):
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "source.png"
    Image.new("RGB", (32, 24), (30, 40, 50)).save(source)
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    record = _catalog(source_sha, two_people=two_people)
    body = {
        "schema_version": "maskfactory.nude_person_catalog_batch.v1",
        "record_count": 1,
        "records": [record],
    }
    catalog = {**body, "self_sha256": _sha(body)}
    root = tmp_path / "masks"
    batch = generate_box_prompt_provider_batch(
        catalog_batch=catalog,
        source_paths={"sample-a": source},
        provider=provider or _Provider(),
        output_root=root,
    )
    return source, root, batch


def test_clean_candidate_passes_all_hard_vetoes_and_revalidates(tmp_path: Path):
    source, root, batch = _fixture(tmp_path)
    result = run_reference_person_mask_hard_qc(
        batch, output_root=root, source_paths={"sample-a": source}
    )
    assert result["status_counts"] == {"pass": 1}
    report = result["records"][0]["candidate_reports"][0]
    assert report["status"] == "pass"
    assert [check["check_id"] for check in report["checks"]] == [
        "NREF-QC-001",
        "NREF-QC-002",
        "NREF-QC-003",
        "NREF-QC-004",
        "NREF-QC-005",
        "NREF-QC-006",
        "NREF-QC-007",
        "NREF-QC-008",
    ]
    assert result["hard_qc_may_be_overridden"] is False
    assert result["strict_visual_review_complete"] is False
    assert (
        validate_reference_person_mask_hard_qc(
            result,
            provider_batch=batch,
            output_root=root,
            source_paths={"sample-a": source},
        )
        == result
    )


def test_collapsed_candidate_is_hard_blocked(tmp_path: Path):
    source, root, batch = _fixture(tmp_path, provider=_Provider(collapsed=True))
    result = run_reference_person_mask_hard_qc(
        batch, output_root=root, source_paths={"sample-a": source}
    )
    report = result["records"][0]["candidate_reports"][0]
    assert report["status"] == "fail"
    assert "NREF-QC-005" in report["blockers"]


def test_cross_person_overlap_is_hard_blocked(tmp_path: Path):
    source, root, batch = _fixture(tmp_path, provider=_Provider(overlap=True), two_people=True)
    result = run_reference_person_mask_hard_qc(
        batch, output_root=root, source_paths={"sample-a": source}
    )
    assert result["records"][0]["status"] == "fail"
    assert all(
        "NREF-QC-008" in report["blockers"] for report in result["records"][0]["candidate_reports"]
    )


def test_artifact_tamper_and_source_drift_fail_before_visual_review(tmp_path: Path):
    source, root, batch = _fixture(tmp_path)
    candidate = batch["records"][0]["candidates"][0]
    (root / candidate["artifact_relative_path"]).write_bytes(b"tampered")
    result = run_reference_person_mask_hard_qc(
        batch, output_root=root, source_paths={"sample-a": source}
    )
    assert result["records"][0]["status"] == "fail"
    assert "NREF-QC-001" in result["records"][0]["candidate_reports"][0]["blockers"]

    source, root, batch = _fixture(tmp_path / "other")
    source.write_bytes(b"drift")
    result = run_reference_person_mask_hard_qc(
        batch, output_root=root, source_paths={"sample-a": source}
    )
    assert result["records"][0]["status"] == "fail"
    assert result["records"][0]["blockers"] == ["NREF-QC-000"]


def test_policy_is_closed_and_cannot_weaken_overlap_below_zero(tmp_path: Path):
    source, root, batch = _fixture(tmp_path)
    with pytest.raises(NudeReferenceMaskHardQcError, match="policy_invalid"):
        run_reference_person_mask_hard_qc(
            batch,
            output_root=root,
            source_paths={"sample-a": source},
            policy={
                "minimum_mask_to_prompt_box_ratio": 0.05,
                "maximum_component_count": 16,
                "minimum_largest_component_fraction": 0.5,
                "maximum_cross_person_overlap_pixels": -1,
            },
        )


def test_hard_qc_stage_receipt_is_nonterminal_and_nonoverridable(tmp_path: Path):
    source, root, batch = _fixture(tmp_path)
    result = run_reference_person_mask_hard_qc(
        batch, output_root=root, source_paths={"sample-a": source}
    )
    receipt = build_reference_mask_hard_qc_stage_receipt(
        provider=result["provider"],
        provider_batch_sha256=result["provider_batch_sha256"],
        policy_sha256=result["policy_sha256"],
        record=result["records"][0],
    )
    assert receipt["stage"] == "reference_person_mask_hard_qc:provider-a"
    assert receipt["hard_qc_may_be_overridden"] is False
    assert receipt["production_mask_authority"] is False
    assert validate_reference_mask_hard_qc_stage_receipt(receipt) == receipt

    drifted = json.loads(json.dumps(receipt))
    drifted["blockers"] = ["invented"]
    with pytest.raises(NudeReferenceMaskHardQcError, match="status_blocker_mismatch"):
        validate_reference_mask_hard_qc_stage_receipt(drifted)

    with pytest.raises(NudeReferenceMaskHardQcError, match="policy_weakened"):
        run_reference_person_mask_hard_qc(
            batch,
            output_root=root,
            source_paths={"sample-a": source},
            policy={
                "minimum_mask_to_prompt_box_ratio": 0.01,
                "maximum_component_count": 16,
                "minimum_largest_component_fraction": 0.5,
                "maximum_cross_person_overlap_pixels": 0,
            },
        )


def test_strict_visual_review_requires_complete_independent_per_record_votes(tmp_path: Path):
    source, root, batch = _fixture(tmp_path)
    hard_qc = run_reference_person_mask_hard_qc(
        batch, output_root=root, source_paths={"sample-a": source}
    )
    kwargs = _strict_kwargs(source, root, batch, hard_qc, tmp_path)
    primary, juror = kwargs["reviewers"]
    juror.responses = [_visual_response(confidence=0.8)]
    result = run_reference_person_strict_visual_review(**kwargs)
    assert result["status_counts"] == {"pass": 1}
    report = result["records"][0]["candidate_reports"][0]
    assert report["status"] == "pass"
    assert len(report["evidence_files"]) == 6
    assert all(
        hashlib.sha256((tmp_path / "visual" / item["path"]).read_bytes()).hexdigest()
        == item["sha256"]
        for item in report["evidence_files"]
    )
    assert {vote["reviewer"]["model_family"] for vote in report["reviewer_verdicts"]} == {
        "qwen",
        "internvl",
    }
    assert result["source_images_are_pixel_truth"] is False
    assert result["production_mask_authority"] is False
    assert result["contact_sheet_approval_forbidden"] is True
    assert len(primary.calls[0][1]) == len(juror.calls[0][1]) == 6
    assert (
        validate_reference_person_strict_visual_review(result, evidence_root=tmp_path / "visual")
        == result
    )
    receipt = build_reference_strict_visual_stage_receipt(
        provider=batch["provider"],
        visual_review_sha256=result["self_sha256"],
        record=result["records"][0],
    )
    assert receipt["production_mask_authority"] is False
    assert validate_reference_strict_visual_stage_receipt(receipt) == receipt


def test_strict_visual_review_invalid_or_unavailable_reviewer_blocks(tmp_path: Path):
    source, root, batch = _fixture(tmp_path)
    hard_qc = run_reference_person_mask_hard_qc(
        batch, output_root=root, source_paths={"sample-a": source}
    )
    kwargs = _strict_kwargs(source, root, batch, hard_qc, tmp_path)
    primary = kwargs["reviewers"][0]
    primary.responses = ["bad", "still bad"]
    result = run_reference_person_strict_visual_review(**kwargs)
    assert result["records"][0]["status"] == "blocked"
    assert result["records"][0]["blockers"] == ["STRICT_VISUAL_CRITIC_BLOCKED"]
    assert result["operational_certificates_issued"] is False


def test_strict_visual_review_never_runs_on_hard_qc_failure(tmp_path: Path):
    source, root, batch = _fixture(tmp_path, provider=_Provider(collapsed=True))
    hard_qc = run_reference_person_mask_hard_qc(
        batch, output_root=root, source_paths={"sample-a": source}
    )
    kwargs = _strict_kwargs(source, root, batch, hard_qc, tmp_path)
    primary, juror = kwargs["reviewers"]
    result = run_reference_person_strict_visual_review(**kwargs)
    assert result["records"][0]["status"] == "upstream_rejected"
    assert not primary.calls and not juror.calls


def test_strict_visual_review_rejects_same_family_or_weak_threshold(tmp_path: Path):
    source, root, batch = _fixture(tmp_path)
    hard_qc = run_reference_person_mask_hard_qc(
        batch, output_root=root, source_paths={"sample-a": source}
    )
    catalog, certificates, reviewers = _critic_authority(same_family=True)
    with pytest.raises(NudeReferenceStrictVisualReviewError, match="not_independent"):
        run_reference_person_strict_visual_review(
            provider_batch=batch,
            hard_qc=hard_qc,
            output_root=root,
            source_paths={"sample-a": source},
            evidence_root=tmp_path / "visual",
            reviewers=reviewers,
            target_contracts=_target_contracts(source, batch),
            critic_catalog=catalog,
            critic_certificates=certificates,
            now=NOW,
        )
    kwargs = _strict_kwargs(source, root, batch, hard_qc, tmp_path)
    with pytest.raises(NudeReferenceStrictVisualReviewError, match="confidence_policy"):
        run_reference_person_strict_visual_review(
            **kwargs,
            minimum_pass_confidence=0.5,
        )


def test_strict_visual_review_requires_exact_v2_contract_before_any_call(tmp_path: Path):
    source, root, batch = _fixture(tmp_path)
    hard_qc = run_reference_person_mask_hard_qc(
        batch, output_root=root, source_paths={"sample-a": source}
    )
    kwargs = _strict_kwargs(source, root, batch, hard_qc, tmp_path)
    primary, juror = kwargs["reviewers"]
    kwargs["target_contracts"] = {"sample-a": {}}
    with pytest.raises(NudeReferenceStrictVisualReviewError, match="target_contract_missing"):
        run_reference_person_strict_visual_review(**kwargs)
    assert not primary.calls and not juror.calls


def test_strict_visual_review_rejects_stale_or_mismatched_role_authority(tmp_path: Path):
    source, root, batch = _fixture(tmp_path)
    hard_qc = run_reference_person_mask_hard_qc(
        batch, output_root=root, source_paths={"sample-a": source}
    )
    kwargs = _strict_kwargs(source, root, batch, hard_qc, tmp_path)
    stale = deepcopy(kwargs["critic_certificates"])
    stale[0]["qualified_until"] = "2026-07-22T11:59:59Z"
    stale[0]["certificate_sha256"] = certificate_sha256(stale[0])
    kwargs["critic_certificates"] = stale
    with pytest.raises(ValueError, match="not currently qualified"):
        run_reference_person_strict_visual_review(**kwargs)

    kwargs = _strict_kwargs(source, root, batch, hard_qc, tmp_path)
    kwargs["reviewers"][0].identity = VisualReviewerIdentity(
        "primary_visual_critic", "wrong-model", "qwen", "b" * 64
    )
    with pytest.raises(NudeReferenceStrictVisualReviewError, match="certificate_mismatch"):
        run_reference_person_strict_visual_review(**kwargs)
