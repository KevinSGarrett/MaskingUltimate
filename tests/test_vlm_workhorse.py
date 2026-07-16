import json
from pathlib import Path

import numpy as np
from PIL import Image

from maskfactory.io.png_strict import write_binary_mask, write_label_map
from maskfactory.qa.panels import render_workhorse_evidence
from maskfactory.vlm.client import VlmClientError
from maskfactory.vlm.eval import gate_fingerprint
from maskfactory.vlm.production import run_s11_production
from maskfactory.vlm.workhorse import (
    generate_correction_candidate,
    review_part_workhorse,
    verify_correction_candidate,
    write_workhorse_report,
)


def _evidence(tmp_path: Path):
    source = Image.new("RGB", (80, 60), "gray")
    mask = np.zeros((60, 80), dtype=bool)
    mask[15:45, 25:55] = True
    protected = np.zeros_like(mask)
    return (
        render_workhorse_evidence(source, mask, protected, tmp_path / "evidence"),
        mask,
        protected,
    )


def _response(tool="sam2_refine"):
    return {
        "verdict": "fail",
        "confidence": 0.96,
        "problems": ["boundary_too_loose"],
        "observations": {
            "full_context": "Target is centered inside the highlighted torso crop.",
            "source_crop": "Visible target occupies the center of the crop.",
            "mask": "Binary mask extends beyond the target on the right.",
            "overlay": "Red fill includes background right of the target.",
            "contour": "Cyan contour is displaced on the right edge.",
            "neighbor_overlap": "No protected-neighbor overlap is visible.",
        },
        "evidence": "Overlay includes background along the right edge.",
        "correction_instruction": "Tighten the right boundary around visible target pixels.",
        "correction_plan": {
            "tool": tool,
            "positive_points": [[40, 30]] if tool == "sam2_refine" else [],
            "negative_points": [[70, 30]] if tool == "sam2_refine" else [],
            "rationale": "One positive and one negative click bound SAM2 safely.",
        },
    }


def test_workhorse_evidence_preserves_six_independent_high_resolution_images(tmp_path: Path):
    evidence, _mask, _protected = _evidence(tmp_path)
    assert len(evidence.images) == 6 and evidence.source_size == (80, 60)
    assert [path.name for path in evidence.images] == [
        "full_context.png",
        "source_crop.png",
        "mask.png",
        "overlay.png",
        "contour.png",
        "neighbor_overlap.png",
    ]
    for path in evidence.images[1:]:
        with Image.open(path) as image:
            assert image.size == (1024, 1024)


def test_workhorse_audit_requires_per_image_observations_and_bounded_points(tmp_path: Path):
    evidence, _mask, _protected = _evidence(tmp_path)

    class Client:
        def generate(self, **kwargs):
            assert kwargs["images"] == evidence.images
            return json.dumps(_response())

    audit = review_part_workhorse(
        Client(),
        label="left_forearm",
        evidence=evidence,
        model="qwen2.5vl:7b",
        prompt_template="Audit <label>",
        prompt_version="workhorse-test",
        gpu_lock_path=tmp_path / "gpu.lock",
        generation_options={"temperature": 0, "seed": 1337},
    )
    assert audit.verdict == "fail" and audit.correction_plan.tool == "sam2_refine"
    assert audit.correction_plan.positive_points == ((40, 30),)


def test_workhorse_prompt_spells_out_atomic_foot_boundary(tmp_path: Path):
    evidence, _mask, _protected = _evidence(tmp_path)

    class Client:
        prompt = ""

        def generate(self, **kwargs):
            self.prompt = kwargs["prompt"]
            return json.dumps(_response())

    client = Client()
    review_part_workhorse(
        client,
        label="right_foot_base",
        evidence=evidence,
        model="qwen2.5vl:7b",
        prompt_template="Audit <label>",
        prompt_version="workhorse-test",
        gpu_lock_path=tmp_path / "gpu.lock",
        generation_options={},
    )

    assert "foot base excludes toes beginning at metatarsophalangeal line" in client.prompt
    assert "foot_base excludes visible toes" in client.prompt


def test_workhorse_invalid_coordinates_fail_closed_after_retry(tmp_path: Path):
    evidence, _mask, _protected = _evidence(tmp_path)
    invalid = _response()
    invalid["correction_plan"]["positive_points"] = [[999, 999]]

    class Client:
        calls = 0
        prompts = []

        def generate(self, **kwargs):
            self.calls += 1
            self.prompts.append(kwargs["prompt"])
            return json.dumps(invalid)

    client = Client()
    audit = review_part_workhorse(
        client,
        label="left_forearm",
        evidence=evidence,
        model="qwen2.5vl:7b",
        prompt_template="Audit <label>",
        prompt_version="workhorse-test",
        gpu_lock_path=tmp_path / "gpu.lock",
        generation_options={},
    )
    assert client.calls == 2 and audit.verdict == "uncertain"
    assert audit.correction_plan.tool == "human_review"
    assert "outside source size width=80, height=60" in client.prompts[1]
    assert "Final contract error" in audit.correction_plan.rationale


def test_workhorse_transport_timeout_becomes_uncertain_vote(tmp_path: Path):
    evidence, _mask, _protected = _evidence(tmp_path)

    class Client:
        def generate(self, **kwargs):
            raise VlmClientError("timed out")

    audit = review_part_workhorse(
        Client(),
        label="right_toes",
        evidence=evidence,
        model="qwen2.5vl:7b",
        prompt_template="Audit <label>",
        prompt_version="workhorse-test",
        gpu_lock_path=tmp_path / "gpu.lock",
        generation_options={},
    )

    assert audit.verdict == "uncertain" and audit.confidence == 0
    assert audit.correction_plan.tool == "human_review"
    assert "Local reviewer unavailable" in audit.evidence


def test_workhorse_executes_sam2_candidate_but_never_overwrites_current_mask(tmp_path: Path):
    evidence, mask, protected = _evidence(tmp_path)

    class Client:
        def generate(self, **kwargs):
            return json.dumps(_response())

    audit = review_part_workhorse(
        Client(),
        label="left_forearm",
        evidence=evidence,
        model="qwen2.5vl:7b",
        prompt_template="Audit <label>",
        prompt_version="workhorse-test",
        gpu_lock_path=tmp_path / "gpu.lock",
        generation_options={},
    )
    before = mask.copy()

    def refiner(_source, _label, _clicks):
        candidate = mask.copy()
        candidate[:, 60:] = False
        return candidate

    result = generate_correction_candidate(
        audit,
        source=np.zeros((60, 80, 3), dtype=np.uint8),
        current_mask=mask,
        protected_neighbor=protected,
        refiner=refiner,
        output_path=tmp_path / "candidates/left_forearm.png",
    )
    assert result.status == "candidate_created"
    assert (tmp_path / "candidates/left_forearm.png").is_file()
    assert np.array_equal(mask, before)
    report = write_workhorse_report(
        tmp_path / "workhorse_report.json", audits=[audit], candidates=[result]
    )
    document = json.loads(report.read_text())
    assert document["authority"] == "candidate_proposals_only_no_direct_gold_authority"
    assert document["candidate_created_count"] == 1 and len(document["sha256"]) == 64
    assert document["candidates"][0]["candidate_path"] == "candidates/left_forearm.png"


def test_workhorse_rejects_candidate_that_crosses_protected_anatomy(tmp_path: Path):
    evidence, mask, protected = _evidence(tmp_path)
    protected[10:50, 56:75] = True

    class Client:
        def generate(self, **kwargs):
            return json.dumps(_response())

    audit = review_part_workhorse(
        Client(),
        label="left_forearm",
        evidence=evidence,
        model="qwen2.5vl:7b",
        prompt_template="Audit <label>",
        prompt_version="workhorse-test",
        gpu_lock_path=tmp_path / "gpu.lock",
        generation_options={},
    )
    result = generate_correction_candidate(
        audit,
        source=np.zeros((60, 80, 3), dtype=np.uint8),
        current_mask=mask,
        protected_neighbor=protected,
        refiner=lambda *_args: np.ones_like(mask),
        output_path=tmp_path / "rejected.png",
    )
    assert result.status == "candidate_rejected"
    assert not (tmp_path / "rejected.png").exists()


def test_workhorse_before_after_comparison_is_strict_and_uses_all_twelve_images(tmp_path: Path):
    before, _mask, _protected = _evidence(tmp_path / "before")
    after, _mask, _protected = _evidence(tmp_path / "after")

    class Client:
        def generate(self, **kwargs):
            assert len(kwargs["images"]) == 12
            return json.dumps(
                {
                    "decision": "better",
                    "confidence": 0.91,
                    "fixed_problems": ["boundary_too_loose"],
                    "remaining_problems": [],
                    "before_observation": "Before contour extends beyond the right edge.",
                    "after_observation": "After contour follows the visible right edge.",
                    "evidence": "After removes background without losing target pixels.",
                }
            )

    result = verify_correction_candidate(
        Client(),
        label="left_forearm",
        before=before,
        after=after,
        model="qwen2.5vl:7b",
        prompt_template="Compare <label>",
        gpu_lock_path=tmp_path / "gpu.lock",
        generation_options={},
    )
    assert result.decision == "better" and result.confidence == 0.91


def test_s11_missing_calibration_runs_workhorse_as_non_authoritative_shadow(tmp_path: Path):
    source_path = tmp_path / "source.png"
    Image.new("RGB", (80, 60), "gray").save(source_path)
    part = np.zeros((60, 80), dtype=np.uint16)
    part[15:45, 25:55] = 18
    part_path = write_label_map(tmp_path / "part.png", part, bits=16)
    report = {
        "image_id": "img_a3f9c2e17b04",
        "run_id": "qa_20260712_0000_workhorse",
        "pipeline_version": "maskfactory 0.0.1",
        "created_at": "2026-07-12T00:00:00Z",
        "checks": [],
        "metrics_per_part": {},
        "consensus": {"method": "weighted_vote_v1", "sources": ["sam2"]},
        "vlm_review": {"model": "pending_s11", "verdicts": []},
        "overall": "pass",
        "score": 1.0,
    }
    report_path = tmp_path / "qa_report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    class Client:
        def generate(self, **kwargs):
            prompt = kwargs["prompt"]
            if "VISIBLE LABEL DIGEST" in prompt:
                return json.dumps(
                    {
                        "missing": [],
                        "mislabeled": [],
                        "lr_suspect": [],
                        "impossible_claims": [],
                        "notes": "Shadow whole-image review complete.",
                    }
                )
            if "twelve images" in prompt:
                return json.dumps(
                    {
                        "decision": "better",
                        "confidence": 0.9,
                        "fixed_problems": ["boundary_too_loose"],
                        "remaining_problems": [],
                        "before_observation": "Before extends outside the target.",
                        "after_observation": "After follows the target boundary.",
                        "evidence": "After removes the reported excess.",
                    }
                )
            return json.dumps(_response())

    status = run_s11_production(
        source_crop_path=source_path,
        part_map_path=part_path,
        s10_report_path=report_path,
        output_dir=tmp_path / "s11",
        gate_path=tmp_path / "missing_gate.json",
        client=Client(),
        workhorse_enabled=True,
        correction_refiner=lambda _image, _label, _clicks: part == 18,
    )
    assert status["enabled"] is False and status["shadow_enabled"] is True, json.dumps(status)
    assert status["workhorse"]["authority"] == "uncalibrated_shadow_candidate_proposals_only"
    assert status["autonomy"]["decision_count"] == 1
    assert status["autonomy"]["authority"] == "uncalibrated_shadow_candidate_proposals_only"
    assert status["autonomy"]["lifecycle_dir"] == "autonomy"
    assert not Path(status["workhorse"]["report"]).is_absolute()
    assert (tmp_path / "s11/correction_candidates/left_forearm.png").is_file()
    final = json.loads((tmp_path / "s11/qa_report.json").read_text())
    assert final["overall"] == "needs_human" and final["vlm_review"]["verdicts"] == []


def test_workhorse_gate_fingerprint_covers_audit_and_compare_prompts(tmp_path: Path):
    workhorse = tmp_path / "p_workhorse.txt"
    compare = tmp_path / "p_compare.txt"
    workhorse.write_text("audit-v1", encoding="utf-8")
    compare.write_text("compare-v1", encoding="utf-8")
    first = gate_fingerprint(model="qwen2.5vl:7b", prompt_version="v1", prompt_path=workhorse)
    compare.write_text("compare-v2", encoding="utf-8")
    second = gate_fingerprint(model="qwen2.5vl:7b", prompt_version="v1", prompt_path=workhorse)
    assert first != second


def test_workhorse_evidence_exposes_specialist_contour_metrics_and_metadata(tmp_path: Path):
    source = Image.new("RGB", (80, 60), "gray")
    target = np.zeros((60, 80), dtype=bool)
    target[15:45, 25:55] = True
    specialist = target.copy()
    specialist[:, 50:55] = False
    evidence = render_workhorse_evidence(
        source,
        target,
        np.zeros_like(target),
        tmp_path / "specialist",
        specialist_candidate=specialist,
        specialist_metadata={"detectors": "hand_detailer", "authority": "proposal_only"},
    )
    metrics = dict(evidence.metrics)
    context = np.asarray(Image.open(evidence.images[0]))
    assert metrics["specialist_disagreement_fraction"] > 0
    assert dict(evidence.specialist_metadata)["detectors"] == "hand_detailer"
    assert np.any(np.all(context == (0, 255, 80), axis=2))


def test_s11_routes_specialist_disagreement_and_registers_raw_tournament_candidate(
    tmp_path: Path,
):
    source = tmp_path / "source.png"
    Image.new("RGB", (80, 60), "gray").save(source)
    part = np.zeros((60, 80), dtype=np.uint16)
    part_path = write_label_map(tmp_path / "part.png", part, bits=16)
    report = {
        "image_id": "img_0123456789ab",
        "run_id": "qa_20260713_1200_fixture",
        "pipeline_version": "maskfactory test",
        "created_at": "2026-07-13T12:00:00Z",
        "checks": [],
        "metrics_per_part": {},
        "consensus": {"method": "weighted_vote_v1", "sources": ["sam2", "geometry"]},
        "vlm_review": {"model": "pending", "verdicts": []},
        "overall": "pass",
        "score": 1.0,
    }
    report_path = tmp_path / "s10.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    auxiliary = tmp_path / "auxiliary"
    specialist = np.zeros((60, 80), dtype=bool)
    specialist[15:45, 25:45] = True
    protected = np.zeros_like(specialist)
    protected[20:22, 30:32] = True
    candidate_path = write_binary_mask(
        auxiliary / "normalized/part_candidate/left_forearm.png", specialist
    )
    protected_path = write_binary_mask(auxiliary / "normalized/protected/nails.png", protected)
    (auxiliary / "auxiliary_predictions.json").write_text(
        json.dumps(
            {
                "authority": "proposal_only",
                "may_write_final_maps": False,
                "source_size": [80, 60],
                "normalized": [
                    candidate_path.relative_to(auxiliary).as_posix(),
                    protected_path.relative_to(auxiliary).as_posix(),
                ],
                "detectors": [
                    {
                        "key": "limb_specialist",
                        "checkpoint_sha256": "a" * 64,
                        "effective_mode": "assist",
                        "detections": [
                            {
                                "kind": "part_candidate",
                                "target": "left_forearm",
                                "class_name": "forearm",
                                "confidence": 0.9,
                                "bbox_xyxy": [25, 15, 45, 45],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    class Client:
        def generate(self, **kwargs):
            if "VISIBLE LABEL DIGEST" in kwargs["prompt"]:
                return json.dumps(
                    {
                        "missing": [],
                        "mislabeled": [],
                        "lr_suspect": [],
                        "impossible_claims": [],
                        "notes": "complete",
                    }
                )
            response = _response(tool="human_review")
            response["verdict"] = "uncertain"
            response["confidence"] = 0.5
            response["problems"] = []
            return json.dumps(response)

    output = tmp_path / "s11"
    status = run_s11_production(
        source_crop_path=source,
        part_map_path=part_path,
        s10_report_path=report_path,
        output_dir=output,
        gate_path=tmp_path / "gate.json",
        client=Client(),
        gate_checker=lambda *args, **kwargs: {"fingerprint": "fixture"},
        workhorse_enabled=True,
        auxiliary_dir=auxiliary,
    )
    route = status["routes"]["left_forearm"]
    assert route["queue"] == "careful" and route["specialist_disagreement_fraction"] == 1.0
    lifecycle = json.loads((output / "autonomy/left_forearm.json").read_text())
    assert any(item["candidate_id"] == "civitai_specialist_raw" for item in lifecycle["ranking"])
    assert not np.asarray(
        Image.open(output / "autonomy_candidates/left_forearm/s09_baseline.png")
    ).any()
    assert dict(json.loads((output / "workhorse_report.json").read_text())["audits"][0])[
        "deterministic_overrides"
    ] == ["autoqa_aux_s11_001"]


def test_deterministic_component_veto_overrides_false_vlm_pass_and_creates_cleanup(
    tmp_path: Path,
):
    source = Image.new("RGB", (80, 60), "gray")
    mask = np.zeros((60, 80), dtype=bool)
    mask[15:45, 25:55] = True
    mask[50:53, 70:74] = True
    protected = np.zeros_like(mask)
    evidence = render_workhorse_evidence(source, mask, protected, tmp_path / "fragmented")
    response = {
        "verdict": "pass",
        "confidence": 1.0,
        "problems": [],
        "observations": {
            "full_context": "The crop contains the target.",
            "source_crop": "The source target is visible.",
            "mask": "The mask appears correct.",
            "overlay": "The overlay appears correct.",
            "contour": "The contour appears correct.",
            "neighbor_overlap": "No overlap is visible.",
        },
        "evidence": "The model claims the mask is correct.",
        "correction_instruction": "",
        "correction_plan": {
            "tool": "none",
            "positive_points": [],
            "negative_points": [],
            "rationale": "No correction claimed.",
        },
    }

    class Client:
        def generate(self, **kwargs):
            return json.dumps(response)

    audit = review_part_workhorse(
        Client(),
        label="left_forearm",
        evidence=evidence,
        model="qwen2.5vl:7b",
        prompt_template="Audit <label>",
        prompt_version="workhorse-test",
        gpu_lock_path=tmp_path / "gpu.lock",
        generation_options={},
    )
    assert audit.verdict == "fail" and audit.correction_plan.tool == "remove_small_components"
    result = generate_correction_candidate(
        audit,
        source=np.zeros((60, 80, 3), dtype=np.uint8),
        current_mask=mask,
        protected_neighbor=protected,
        refiner=None,
        output_path=tmp_path / "cleaned.png",
    )
    assert result.status == "candidate_created"
    cleaned = np.asarray(Image.open(tmp_path / "cleaned.png")) != 0
    assert cleaned[20, 30] and not cleaned[51, 71]


def test_label_specific_autoqa_block_overrides_false_vlm_pass(tmp_path: Path):
    source = Image.new("RGB", (80, 60), "gray")
    mask = np.zeros((60, 80), dtype=bool)
    mask[15:45, 25:55] = True
    evidence = render_workhorse_evidence(source, mask, np.zeros_like(mask), tmp_path / "evidence")
    response = {
        "verdict": "pass",
        "confidence": 1.0,
        "problems": [],
        "observations": {
            key: "Specific visible observation."
            for key in {
                "full_context",
                "source_crop",
                "mask",
                "overlay",
                "contour",
                "neighbor_overlap",
            }
        },
        "evidence": "The model claims a clean pass.",
        "correction_instruction": "",
        "correction_plan": {
            "tool": "none",
            "positive_points": [],
            "negative_points": [],
            "rationale": "pass",
        },
    }

    class Client:
        def generate(self, **kwargs):
            return json.dumps(response)

    audit = review_part_workhorse(
        Client(),
        label="left_forearm",
        evidence=evidence,
        model="test",
        prompt_template="Audit <label>",
        prompt_version="test",
        gpu_lock_path=tmp_path / "gpu.lock",
        generation_options={},
        qa_findings=(
            {
                "id": "QC-014",
                "name": "left_right_consistency",
                "result": "fail",
                "severity": "BLOCK",
                "message": "wrong=['left_forearm']; metrics=" + "x" * 500,
            },
        ),
    )
    assert audit.model_verdict == "pass" and audit.model_confidence == 1.0
    assert audit.verdict == "fail" and audit.correction_plan.tool == "human_review"
    assert audit.deterministic_overrides == ("autoqa_qc_014",)
    assert len(audit.evidence) <= 240 and audit.evidence.endswith("...")


def test_unrelated_autoqa_finding_does_not_change_part_audit(tmp_path: Path):
    source = Image.new("RGB", (80, 60), "gray")
    mask = np.zeros((60, 80), dtype=bool)
    mask[15:45, 25:55] = True
    evidence = render_workhorse_evidence(source, mask, np.zeros_like(mask), tmp_path / "evidence")
    response = {
        "verdict": "pass",
        "confidence": 0.8,
        "problems": [],
        "observations": {
            key: "Specific visible observation."
            for key in {
                "full_context",
                "source_crop",
                "mask",
                "overlay",
                "contour",
                "neighbor_overlap",
            }
        },
        "evidence": "The model claims a clean pass.",
        "correction_instruction": "",
        "correction_plan": {
            "tool": "none",
            "positive_points": [],
            "negative_points": [],
            "rationale": "pass",
        },
    }

    class Client:
        def generate(self, **kwargs):
            return json.dumps(response)

    audit = review_part_workhorse(
        Client(),
        label="left_forearm",
        evidence=evidence,
        model="test",
        prompt_template="Audit <label>",
        prompt_version="test",
        gpu_lock_path=tmp_path / "gpu.lock",
        generation_options={},
        qa_findings=(
            {
                "id": "QC-014",
                "name": "left_right_consistency",
                "result": "fail",
                "severity": "BLOCK",
                "message": "wrong=['right_calf']",
            },
        ),
    )
    assert audit.verdict == "pass" and audit.deterministic_overrides == ()


def test_route_only_autoqa_finding_is_advisory_to_independent_reviewer(tmp_path: Path):
    source = Image.new("RGB", (80, 60), "gray")
    mask = np.zeros((60, 80), dtype=bool)
    mask[15:45, 25:55] = True
    evidence = render_workhorse_evidence(source, mask, np.zeros_like(mask), tmp_path / "evidence")
    response = {
        "verdict": "pass",
        "confidence": 0.99,
        "problems": [],
        "observations": {
            key: "Specific visible observation."
            for key in {
                "full_context",
                "source_crop",
                "mask",
                "overlay",
                "contour",
                "neighbor_overlap",
            }
        },
        "evidence": "Independent visual evidence supports the exact candidate.",
        "correction_instruction": "",
        "correction_plan": {
            "tool": "none",
            "positive_points": [],
            "negative_points": [],
            "rationale": "pass",
        },
    }

    class Client:
        def generate(self, **kwargs):
            return json.dumps(response)

    audit = review_part_workhorse(
        Client(),
        label="left_forearm",
        evidence=evidence,
        model="test",
        prompt_template="Audit <label>",
        prompt_version="test",
        gpu_lock_path=tmp_path / "gpu.lock",
        generation_options={},
        qa_findings=(
            {
                "id": "QC-031",
                "name": "model_disagreement",
                "result": "route",
                "severity": "ROUTE",
                "message": "high_parts={'left_forearm': 0.8}",
            },
        ),
    )
    assert audit.verdict == "pass" and audit.deterministic_overrides == ()
