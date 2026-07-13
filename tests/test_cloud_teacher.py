import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
import yaml
from click.testing import CliRunner
from PIL import Image

from maskfactory.autonomy.review_draft import CandidateQaOutcome
from maskfactory.cli import main
from maskfactory.io.hashing import sha256_file
from maskfactory.io.png_strict import write_binary_mask, write_label_map
from maskfactory.qa.panels import render_workhorse_evidence
from maskfactory.vlm.cloud_budget import CloudBudgetError, DailyBudgetLedger
from maskfactory.vlm.cloud_eval import CloudTeacherEvalError, evaluate_cloud_teacher_corpus
from maskfactory.vlm.cloud_providers import (
    AnthropicTeacherProvider,
    GeminiTeacherProvider,
    OpenAITeacherProvider,
    credential_present,
)
from maskfactory.vlm.cloud_teacher import (
    CloudTeacherError,
    TeacherRequest,
    TeacherUsage,
    build_teacher_distillation_manifest,
    harvest_human_teacher_resolution,
    load_cloud_teacher_config,
    materialize_teacher_candidate,
    parse_teacher_judgment,
    run_teacher_cascade,
    should_escalate_to_cloud,
    verify_cloud_eligibility,
)
from maskfactory.vlm.production import run_s11_production
from maskfactory.vlm.workhorse import CorrectionPlan, WorkhorseAudit


def _benchmark_case(
    case_id: str,
    *,
    human: str,
    severity: str,
    local: str,
    teacher: str,
    useful: bool | None,
):
    return {
        "case_id": case_id,
        "image_id": f"image_{case_id}",
        "label": "left_forearm",
        "severity": severity,
        "human_verdict": human,
        "local_verdict": local,
        "teacher_verdict": teacher,
        "correction_useful": useful,
        "cost_usd": 0.02,
    }


def _fixture(tmp_path: Path, *, verdict="fail"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    source_path = tmp_path / "source.png"
    source = Image.new("RGB", (80, 60), "gray")
    source.save(source_path)
    mask = np.zeros((60, 80), dtype=bool)
    mask[15:45, 25:55] = True
    protected = np.zeros_like(mask)
    evidence = render_workhorse_evidence(source, mask, protected, tmp_path / "evidence")
    audit = WorkhorseAudit(
        "left_forearm",
        verdict,
        0.9,
        verdict,
        0.9,
        ("boundary_too_loose",) if verdict == "fail" else (),
        {
            key: "localized observation"
            for key in {
                "full_context",
                "source_crop",
                "mask",
                "overlay",
                "contour",
                "neighbor_overlap",
            }
        },
        "localized evidence",
        "fix it" if verdict == "fail" else "",
        CorrectionPlan("human_review" if verdict == "fail" else "none", (), (), "test"),
        "qwen2.5vl:7b",
        "test",
        10,
        (),
    )
    return (
        TeacherRequest("img_0123456789ab", "p0", "left_forearm", source_path, evidence, audit, ()),
        mask,
        protected,
    )


def _teacher_response(*, verdict="fail", tool="points"):
    return {
        "verdict": verdict,
        "confidence": 0.92,
        "defects": ["boundary_too_loose"] if verdict == "fail" else [],
        "observations": {
            "full_context": "The highlighted crop is on the left arm.",
            "source_crop": "The visible forearm is centered.",
            "mask": "The binary target extends beyond the forearm.",
            "overlay": "Red includes pixels beyond the right boundary.",
            "contour": "The cyan edge is displaced on the right.",
            "neighbor_overlap": "No protected overlap is visible.",
        },
        "evidence": "The right edge is loose.",
        "correction": {
            "tool": tool if verdict == "fail" else "none",
            "polygon": (
                [[300, 250], [700, 250], [700, 750], [300, 750]] if tool == "polygon" else []
            ),
            "positive_points": [[500, 500]] if tool == "points" else [],
            "negative_points": [[900, 500]] if tool == "points" else [],
            "rationale": "Bound the visible target." if verdict == "fail" else "No correction.",
        },
    }


def test_cloud_teacher_config_is_authorized_shadow_only_and_capped_at_fifteen_dollars():
    config = load_cloud_teacher_config()
    assert config["enabled"] is True and config["mode"] == "shadow_only"
    assert config["budget"]["hard_limit_usd"] == 15
    assert config["budget"]["hard_limit_usd"] + config["budget"]["emergency_reserve_usd"] <= 15
    assert not config["governance"]["may_approve_gold"]
    assert not config["governance"]["may_clear_blocks"]
    assert not config["governance"]["may_write_authoritative_masks"]
    assert all(settings["enabled"] is True for settings in config["providers"].values())


def test_budget_reserves_before_call_reconciles_and_enforces_hard_limit(tmp_path: Path):
    def now():
        return datetime(2026, 7, 12, 18, tzinfo=UTC)

    ledger = DailyBudgetLedger(
        tmp_path / "costs.jsonl", timezone_name="America/Chicago", hard_limit_usd="1.00", now=now
    )
    reserved = ledger.reserve(
        request_id="r1",
        provider="gemini",
        model="m",
        image_id="img_a",
        label="hair",
        maximum_cost_usd="0.80",
    )
    assert float(reserved.reserved_usd) == pytest.approx(0.8)
    with pytest.raises(CloudBudgetError, match="hard limit"):
        ledger.reserve(
            request_id="r2",
            provider="openai",
            model="m",
            image_id="img_a",
            label="hair",
            maximum_cost_usd="0.21",
        )
    committed = ledger.commit("r1", actual_cost_usd="0.12", input_tokens=1000, output_tokens=100)
    assert float(committed.committed_usd) == pytest.approx(0.12) and committed.reserved_usd == 0
    ledger.reserve(
        request_id="r3",
        provider="anthropic",
        model="m",
        image_id="img_a",
        label="hair",
        maximum_cost_usd="0.30",
    )
    released = ledger.release("r3", error="timeout")
    assert float(released.committed_usd) == pytest.approx(0.12) and released.reserved_usd == 0


def test_budget_ledger_detects_tampering_and_duplicate_request_ids(tmp_path: Path):
    ledger = DailyBudgetLedger(tmp_path / "costs.jsonl", timezone_name="UTC", hard_limit_usd="2")
    ledger.reserve(
        request_id="r1",
        provider="gemini",
        model="m",
        image_id="img_a",
        label="hair",
        maximum_cost_usd="0.1",
    )
    with pytest.raises(CloudBudgetError, match="already exists"):
        ledger.reserve(
            request_id="r1",
            provider="gemini",
            model="m",
            image_id="img_a",
            label="hair",
            maximum_cost_usd="0.1",
        )
    text = (tmp_path / "costs.jsonl").read_text().replace('"label":"hair"', '"label":"face"')
    (tmp_path / "costs.jsonl").write_text(text)
    with pytest.raises(CloudBudgetError, match="hash chain"):
        ledger.snapshot()


def test_cloud_eligibility_requires_exact_hash_adult_rights_provider_and_approval(tmp_path: Path):
    source = tmp_path / "source.png"
    Image.new("RGB", (10, 10), "gray").save(source)
    registry = tmp_path / "eligibility.yaml"
    record = {
        "source_sha256": sha256_file(source),
        "age_safety": "clear_adult",
        "rights_evidence": "owned by Kevin",
        "approved_by": "kevin",
        "approved_at": "2026-07-12T18:00:00Z",
        "providers": ["gemini"],
    }
    registry.write_text(
        yaml.safe_dump(
            {"schema_version": "1.0.0", "default": "deny", "images": {"img_0123456789ab": record}}
        )
    )
    assert (
        verify_cloud_eligibility(
            registry_path=registry,
            image_id="img_0123456789ab",
            provider="gemini",
            source_path=source,
        )["approved_by"]
        == "kevin"
    )
    with pytest.raises(CloudTeacherError, match="provider is not approved"):
        verify_cloud_eligibility(
            registry_path=registry,
            image_id="img_0123456789ab",
            provider="openai",
            source_path=source,
        )
    Image.new("RGB", (10, 10), "red").save(source)
    with pytest.raises(CloudTeacherError, match="hash mismatch"):
        verify_cloud_eligibility(
            registry_path=registry,
            image_id="img_0123456789ab",
            provider="gemini",
            source_path=source,
        )


def test_teacher_parser_rejects_self_inconsistent_pass_and_bad_coordinates():
    usage = TeacherUsage(10, 5, 0.001)
    parsed = parse_teacher_judgment(
        json.dumps(_teacher_response()), provider="gemini", model="g", usage=usage, latency_ms=2
    )
    assert parsed.verdict == "fail" and parsed.correction.tool == "points"
    inconsistent = _teacher_response(verdict="pass")
    inconsistent["defects"] = ["wrong_part"]
    with pytest.raises(CloudTeacherError, match="pass cannot"):
        parse_teacher_judgment(
            json.dumps(inconsistent), provider="openai", model="o", usage=usage, latency_ms=2
        )
    invalid = _teacher_response()
    invalid["correction"]["positive_points"] = [[1001, 0]]
    with pytest.raises(CloudTeacherError, match="invalid normalized point"):
        parse_teacher_judgment(
            json.dumps(invalid), provider="anthropic", model="a", usage=usage, latency_ms=2
        )


def test_escalation_uses_hard_labels_local_failure_autoqa_and_disagreement(tmp_path: Path):
    request, _mask, _protected = _fixture(tmp_path)
    selection = load_cloud_teacher_config()["selection"]
    assert should_escalate_to_cloud(request, selection=selection)
    passing_request, _, _ = _fixture(tmp_path / "passing", verdict="pass")
    passing_request = TeacherRequest(
        passing_request.image_id,
        passing_request.instance_id,
        "neck",
        passing_request.source_path,
        passing_request.evidence,
        passing_request.local_audit,
        (),
    )
    assert not should_escalate_to_cloud(passing_request, selection=selection)
    assert should_escalate_to_cloud(
        passing_request, selection=selection, disagreement_fraction=0.04
    )


def test_teacher_cascade_reserves_budget_and_stops_when_primary_agrees(tmp_path: Path):
    request, _mask, _protected = _fixture(tmp_path)
    config = load_cloud_teacher_config()
    config["enabled"] = True
    config["providers"]["gemini"]["enabled"] = True
    config["selection"]["always_escalate_labels"].append("left_forearm")
    config["governance"]["eligibility_registry"] = str(tmp_path / "eligibility.yaml")
    record = {
        "source_sha256": sha256_file(request.source_path),
        "age_safety": "clear_adult",
        "rights_evidence": "owned",
        "approved_by": "kevin",
        "approved_at": "2026-07-12T18:00:00Z",
        "providers": ["gemini"],
    }
    (tmp_path / "eligibility.yaml").write_text(
        yaml.safe_dump(
            {"schema_version": "1.0.0", "default": "deny", "images": {request.image_id: record}}
        )
    )

    class Provider:
        name, model, maximum_reserved_cost_usd = "gemini", "fake", 0.1
        calls = 0

        def review(self, request, prompt):
            self.calls += 1
            assert "left_forearm" in prompt
            return parse_teacher_judgment(
                json.dumps(_teacher_response()),
                provider="gemini",
                model="fake",
                usage=TeacherUsage(100, 100, 0.01),
                latency_ms=1,
            )

    provider = Provider()
    budget = DailyBudgetLedger(tmp_path / "costs.jsonl", timezone_name="UTC", hard_limit_usd="1")
    judgments = run_teacher_cascade(
        request,
        providers={"gemini": provider},
        config=config,
        budget=budget,
        prompt_template=Path("src/maskfactory/vlm/prompts/p_cloud_teacher.txt").read_text(),
        report_path=tmp_path / "teacher_report.json",
    )
    assert provider.calls == 1 and len(judgments) == 1
    assert float(budget.snapshot().committed_usd) == pytest.approx(0.01)
    report = json.loads((tmp_path / "teacher_report.json").read_text())
    assert report["authority"] == "shadow_advisory_human_approval_required"


def test_teacher_failure_conservatively_charges_full_reservation(tmp_path: Path):
    request, _mask, _protected = _fixture(tmp_path)
    config = load_cloud_teacher_config()
    config["enabled"] = True
    config["providers"]["gemini"]["enabled"] = True
    config["governance"]["eligibility_registry"] = str(tmp_path / "eligibility.yaml")
    (tmp_path / "eligibility.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0.0",
                "default": "deny",
                "images": {
                    request.image_id: {
                        "source_sha256": sha256_file(request.source_path),
                        "age_safety": "clear_adult",
                        "rights_evidence": "owned",
                        "approved_by": "kevin",
                        "approved_at": "2026-07-12T18:00:00Z",
                        "providers": ["gemini"],
                    }
                },
            }
        )
    )

    class BrokenProvider:
        name, model, maximum_reserved_cost_usd = "gemini", "broken", 0.2

        def review(self, request, prompt):
            raise CloudTeacherError("malformed billed response")

    budget = DailyBudgetLedger(tmp_path / "costs.jsonl", timezone_name="UTC", hard_limit_usd="1")
    result = run_teacher_cascade(
        request,
        providers={"gemini": BrokenProvider()},
        config=config,
        budget=budget,
        prompt_template="Review <label>",
        report_path=tmp_path / "report.json",
    )
    assert result == () and float(budget.snapshot().committed_usd) == pytest.approx(0.2)
    assert "unknown_usage_after_dispatch" in (tmp_path / "costs.jsonl").read_text()


def test_polygon_candidate_is_isolated_and_local_guards_reject_protected_overlap(tmp_path: Path):
    request, mask, protected = _fixture(tmp_path)
    judgment = parse_teacher_judgment(
        json.dumps(_teacher_response(tool="polygon")),
        provider="gemini",
        model="g",
        usage=TeacherUsage(1, 1, 0.001),
        latency_ms=1,
    )
    candidate = materialize_teacher_candidate(
        judgment,
        request=request,
        current_mask=mask,
        protected_neighbor=protected,
        refiner=None,
        output_path=tmp_path / "candidate.png",
    )
    assert candidate.status == "candidate_created" and (tmp_path / "candidate.png").is_file()
    assert np.array_equal(mask, np.pad(np.ones((30, 30), bool), ((15, 15), (25, 25))))
    blocked = materialize_teacher_candidate(
        judgment,
        request=request,
        current_mask=mask,
        protected_neighbor=np.ones_like(mask),
        refiner=None,
        output_path=tmp_path / "must_not_exist.png",
    )
    assert blocked.status == "not_created" and not (tmp_path / "must_not_exist.png").exists()


@pytest.mark.parametrize(
    ("provider_class", "name", "env_name", "response"),
    [
        (
            OpenAITeacherProvider,
            "openai",
            "OPENAI_API_KEY",
            {
                "output_text": json.dumps(_teacher_response()),
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        ),
        (
            GeminiTeacherProvider,
            "gemini",
            "GEMINI_API_KEY",
            {
                "candidates": [{"content": {"parts": [{"text": json.dumps(_teacher_response())}]}}],
                "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 50},
            },
        ),
        (
            AnthropicTeacherProvider,
            "anthropic",
            "ANTHROPIC_API_KEY",
            {
                "content": [{"type": "text", "text": json.dumps(_teacher_response())}],
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        ),
    ],
)
def test_provider_adapters_use_strict_multimage_payload_without_leaking_key(
    tmp_path: Path, monkeypatch, provider_class, name, env_name, response
):
    request, _mask, _protected = _fixture(tmp_path)

    class Transport:
        def post(self, url, *, headers, payload, timeout):
            self.url, self.headers, self.payload, self.timeout = url, headers, payload, timeout
            return response

    transport = Transport()
    monkeypatch.setenv(env_name, "secret-test-key")
    provider = provider_class(
        {
            "enabled": True,
            "model": {
                "openai": "gpt-5.6-luna",
                "gemini": "gemini-3.5-flash",
                "anthropic": "claude-sonnet-5",
            }[name],
            "api_key_env": env_name,
            "base_url": {
                "openai": "https://api.openai.com/v1",
                "gemini": "https://generativelanguage.googleapis.com/v1beta",
                "anthropic": "https://api.anthropic.com/v1",
            }[name],
            "input_usd_per_million": 1,
            "output_usd_per_million": 2,
            "maximum_reserved_cost_usd": 0.2,
            "timeout_sec": 10,
            "role": "test",
        },
        transport=transport,
    )
    judgment = provider.review(request, "strict test prompt")
    assert judgment.provider == name and judgment.usage.input_tokens == 100
    serialized = json.dumps(transport.payload)
    assert "secret-test-key" not in serialized and len(request.evidence.images) == 6


def test_provider_credentials_support_canonical_and_kevin_legacy_env_syntax(
    tmp_path: Path, monkeypatch
):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GEMINI_API_KEY=canonical-g\nOpenai: legacy-o\nAnthropic: 'legacy-a'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MASKFACTORY_ENV_FILE", str(env_file))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert credential_present("GEMINI_API_KEY", "gemini")
    assert credential_present("OPENAI_API_KEY", "openai")
    assert credential_present("ANTHROPIC_API_KEY", "anthropic")


def test_learning_records_refuse_drafts_and_accept_only_frozen_human_gold(tmp_path: Path):
    package = tmp_path / "packages/img_0123456789ab/instances/p0"
    (package / "masks").mkdir(parents=True)
    (package / "annotations/draft_baseline/masks").mkdir(parents=True)
    mask = np.zeros((20, 20), dtype=bool)
    mask[5:15, 5:15] = True
    write_binary_mask(package / "masks/left_forearm.png", mask)
    write_binary_mask(package / "annotations/draft_baseline/masks/left_forearm.png", mask)
    manifest = {
        "image_id": "img_0123456789ab",
        "review": {"reviewer": "kevin", "approved_at": "2026-07-12T18:00:00Z"},
        "qa": {"qa_overall": "pass"},
        "parts": {"left_forearm": {"status": "human_approved_gold"}},
    }
    (package / "manifest.json").write_text(json.dumps(manifest))
    teacher_report = tmp_path / "teacher.json"
    teacher_report.write_text(
        json.dumps(
            {"label": "left_forearm", "judgments": [{"provider": "gemini", "verdict": "fail"}]}
        )
    )
    with pytest.raises(CloudTeacherError, match="frozen"):
        harvest_human_teacher_resolution(
            package_root=package,
            teacher_report_path=teacher_report,
            output_path=tmp_path / "learning.jsonl",
        )
    (package / ".maskfactory_frozen.json").write_text("{}")
    record = harvest_human_teacher_resolution(
        package_root=package,
        teacher_report_path=teacher_report,
        output_path=tmp_path / "learning.jsonl",
    )
    assert record["authority"] == "human_approved_gold_only"
    harvest_human_teacher_resolution(
        package_root=package,
        teacher_report_path=teacher_report,
        output_path=tmp_path / "learning.jsonl",
    )
    assert len((tmp_path / "learning.jsonl").read_text().splitlines()) == 1


def test_distillation_manifest_is_gold_only_balanced_and_image_disjoint(tmp_path: Path):
    records = tmp_path / "learning.jsonl"
    rows = []
    for image_index in range(10):
        for label_index, verdict in enumerate(("pass", "fail")):
            rows.append(
                {
                    "record_id": f"r{image_index}_{label_index}",
                    "image_id": f"img_{image_index:012x}",
                    "label": "hair" if label_index else "left_forearm",
                    "human_truth_verdict": verdict,
                    "authority": "human_approved_gold_only",
                    "teacher_judgments": [{"provider": "gemini"}],
                }
            )
    records.write_text("".join(json.dumps(row) + "\n" for row in rows))
    document = build_teacher_distillation_manifest(
        records_path=records,
        output_path=tmp_path / "distillation.json",
        minimum_prompt_records=8,
        minimum_lora_records=500,
    )
    train_ids = set(document["training_record_ids"])
    holdout_ids = set(document["holdout_record_ids"])
    assert train_ids.isdisjoint(holdout_ids) and holdout_ids
    train_images = {row["image_id"] for row in rows if row["record_id"] in train_ids}
    holdout_images = {row["image_id"] for row in rows if row["record_id"] in holdout_ids}
    assert train_images.isdisjoint(holdout_images)
    assert document["prompt_exemplars_ready"] is True
    assert document["lora_candidate_ready"] is False
    assert document["training_truth_counts"]["pass"] == document["training_truth_counts"]["fail"]


def test_distillation_rejects_cloud_only_pseudo_labels(tmp_path: Path):
    records = tmp_path / "learning.jsonl"
    records.write_text(
        json.dumps(
            {
                "record_id": "r1",
                "image_id": "img_000000000001",
                "human_truth_verdict": "fail",
                "authority": "cloud_teacher_only",
            }
        )
        + "\n"
    )
    with pytest.raises(CloudTeacherError, match="gold authority"):
        build_teacher_distillation_manifest(
            records_path=records,
            output_path=tmp_path / "distillation.json",
            minimum_prompt_records=10,
            minimum_lora_records=500,
        )


def test_cloud_status_and_empty_distillation_cli_are_nonbillable(tmp_path: Path, monkeypatch):
    config = load_cloud_teacher_config()
    config["budget"]["ledger_path"] = str(tmp_path / "costs.jsonl")
    config["learning"]["records_path"] = str(tmp_path / "records.jsonl")
    config_path = tmp_path / "cloud_teacher.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    for variable in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("MASKFACTORY_ENV_FILE", str(tmp_path / "absent.env"))
    status = CliRunner().invoke(main, ["vlmqa", "cloud-status", "--config", str(config_path)])
    assert status.exit_code == 0, status.output
    document = json.loads(status.output)
    assert document["enabled"] is True and document["budget"]["committed_usd"] == "0"
    assert all(not row["credential_present"] for row in document["providers"].values())
    output = tmp_path / "distillation.json"
    built = CliRunner().invoke(
        main,
        [
            "vlmqa",
            "build-distillation",
            "--config",
            str(config_path),
            "--records",
            str(tmp_path / "absent.jsonl"),
            "--output",
            str(output),
        ],
    )
    assert built.exit_code == 0, built.output
    assert json.loads(built.output)["record_count"] == 0 and output.is_file()
    assert not (tmp_path / "costs.jsonl").exists()


def test_s11_cloud_teacher_is_shadow_only_and_writes_isolated_candidate(tmp_path: Path):
    source = tmp_path / "source.png"
    Image.new("RGB", (80, 60), "gray").save(source)
    part = np.zeros((60, 80), dtype=np.uint16)
    part[15:45, 25:55] = 18
    part_path = write_label_map(tmp_path / "part.png", part, bits=16)
    report_path = tmp_path / "s10.json"
    report_path.write_text(
        json.dumps(
            {
                "image_id": "img_0123456789ab",
                "run_id": "qa_20260712_1800_fixture",
                "pipeline_version": "maskfactory test",
                "created_at": "2026-07-12T18:00:00Z",
                "checks": [],
                "metrics_per_part": {},
                "consensus": {"method": "weighted_vote_v1", "sources": ["sam2"]},
                "vlm_review": {"model": "pending_s11", "verdicts": []},
                "overall": "pass",
                "score": 1.0,
            }
        )
    )
    config = load_cloud_teacher_config()
    config["enabled"] = True
    config["providers"]["gemini"]["enabled"] = True
    config["selection"]["always_escalate_labels"].append("left_forearm")
    config["budget"]["ledger_path"] = str(tmp_path / "costs.jsonl")
    config["governance"]["eligibility_registry"] = str(tmp_path / "eligibility.yaml")
    config_path = tmp_path / "cloud.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    (tmp_path / "eligibility.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0.0",
                "default": "deny",
                "images": {
                    "img_0123456789ab": {
                        "source_sha256": sha256_file(source),
                        "age_safety": "clear_adult",
                        "rights_evidence": "owned",
                        "approved_by": "kevin",
                        "approved_at": "2026-07-12T18:00:00Z",
                        "providers": ["gemini"],
                    }
                },
            }
        )
    )

    class LocalClient:
        def generate(self, **kwargs):
            if "VISIBLE LABEL DIGEST" in kwargs["prompt"]:
                return json.dumps(
                    {
                        "missing": [],
                        "mislabeled": [],
                        "lr_suspect": [],
                        "impossible_claims": [],
                        "notes": "shadow test",
                    }
                )
            return json.dumps(
                {
                    "verdict": "pass",
                    "confidence": 0.9,
                    "problems": [],
                    "observations": {
                        key: "localized observation"
                        for key in {
                            "full_context",
                            "source_crop",
                            "mask",
                            "overlay",
                            "contour",
                            "neighbor_overlap",
                        }
                    },
                    "evidence": "local claims pass",
                    "correction_instruction": "",
                    "correction_plan": {
                        "tool": "none",
                        "positive_points": [],
                        "negative_points": [],
                        "rationale": "pass",
                    },
                }
            )

    class Teacher:
        name, model, maximum_reserved_cost_usd = "gemini", "fake", 0.1

        def review(self, request, prompt):
            return parse_teacher_judgment(
                json.dumps(_teacher_response(tool="polygon")),
                provider="gemini",
                model="fake",
                usage=TeacherUsage(10, 10, 0.01),
                latency_ms=1,
            )

    output = tmp_path / "s11"
    status = run_s11_production(
        source_crop_path=source,
        part_map_path=part_path,
        s10_report_path=report_path,
        output_dir=output,
        gate_path=tmp_path / "gate.json",
        client=LocalClient(),
        gate_checker=lambda *args, **kwargs: {"fingerprint": "fixture"},
        workhorse_enabled=True,
        cloud_teacher_config_path=config_path,
        teacher_providers={"gemini": Teacher()},
        teacher_budget=DailyBudgetLedger(
            tmp_path / "costs.jsonl", timezone_name="UTC", hard_limit_usd="1"
        ),
    )
    assert status["cloud_teacher"]["judgment_count"] == 1
    assert status["cloud_teacher"]["candidate_created_count"] == 1
    assert status["routes"]["left_forearm"]["queue"] == "careful"
    assert (output / "cloud_teacher_candidates/gemini_left_forearm.png").is_file()
    assert status["autonomy"]["decision_count"] == 1
    lifecycle = json.loads((output / "autonomy/left_forearm.json").read_text())
    assert lifecycle["status"] == "residual_human_queue"
    assert lifecycle["authoritative_human_gold"] is False
    assert np.array_equal(np.asarray(Image.open(part_path)), part)


def test_s11_promotes_qa_clean_local_correction_into_non_gold_review_draft(
    tmp_path: Path,
):
    source = tmp_path / "source.png"
    Image.new("RGB", (80, 60), "gray").save(source)
    part = np.zeros((60, 80), dtype=np.uint16)
    part[15:45, 25:55] = 18
    part_path = write_label_map(tmp_path / "part.png", part, bits=16)
    report_path = tmp_path / "s10.json"
    report_path.write_text(
        json.dumps(
            {
                "image_id": "img_0123456789ab",
                "run_id": "qa_20260713_1200_fixture",
                "pipeline_version": "maskfactory test",
                "created_at": "2026-07-13T12:00:00Z",
                "checks": [],
                "metrics_per_part": {},
                "consensus": {
                    "method": "weighted_vote_v1",
                    "sources": ["sam2", "densepose", "detectron2", "pose", "consensus"],
                },
                "vlm_review": {"model": "pending_s11", "verdicts": []},
                "overall": "pass",
                "score": 1.0,
            }
        )
    )
    cloud_config = load_cloud_teacher_config()
    cloud_config["enabled"] = False
    cloud_config_path = tmp_path / "cloud.yaml"
    cloud_config_path.write_text(yaml.safe_dump(cloud_config, sort_keys=False))

    class LocalClient:
        audit_calls = 0

        def generate(self, **kwargs):
            if "VISIBLE LABEL DIGEST" in kwargs["prompt"]:
                return json.dumps(
                    {
                        "missing": [],
                        "mislabeled": [],
                        "lr_suspect": [],
                        "impossible_claims": [],
                        "notes": "whole-image review complete",
                    }
                )
            if len(kwargs.get("images", ())) == 12:
                return json.dumps(
                    {
                        "decision": "better",
                        "confidence": 0.95,
                        "fixed_problems": ["boundary_too_loose"],
                        "remaining_problems": [],
                        "before_observation": "Before extends one column past the target.",
                        "after_observation": "After follows the target boundary.",
                        "evidence": "The excess column is removed without losing the target.",
                    }
                )
            self.audit_calls += 1
            verdict = "fail" if self.audit_calls == 1 else "pass"
            return json.dumps(
                {
                    "verdict": verdict,
                    "confidence": 0.95,
                    "problems": ["boundary_too_loose"] if verdict == "fail" else [],
                    "observations": {
                        key: "Specific localized observation."
                        for key in {
                            "full_context",
                            "source_crop",
                            "mask",
                            "overlay",
                            "contour",
                            "neighbor_overlap",
                        }
                    },
                    "evidence": "The boundary evidence was inspected.",
                    "correction_instruction": (
                        "Remove the one-column excess." if verdict == "fail" else ""
                    ),
                    "correction_plan": {
                        "tool": "sam2_refine" if verdict == "fail" else "none",
                        "positive_points": [[40, 30]] if verdict == "fail" else [],
                        "negative_points": [[70, 30]] if verdict == "fail" else [],
                        "rationale": "Bounded correction." if verdict == "fail" else "Pass.",
                    },
                }
            )

    def refiner(_source, _label, _clicks):
        candidate = part == 18
        candidate[:, 54:] = False
        return candidate

    validation_tags = []

    def validate_map(map_path: Path, tag: str) -> CandidateQaOutcome:
        validation_tags.append(tag)
        qa_path = tmp_path / "candidate_qa" / tag / "qa_report.json"
        qa_path.parent.mkdir(parents=True, exist_ok=True)
        qa_path.write_text(json.dumps({"overall": "pass", "checks": []}))
        assert np.asarray(Image.open(map_path)).shape == part.shape
        return CandidateQaOutcome((), qa_path, "pass")

    output = tmp_path / "s11"
    status = run_s11_production(
        source_crop_path=source,
        part_map_path=part_path,
        s10_report_path=report_path,
        output_dir=output,
        gate_path=tmp_path / "gate.json",
        client=LocalClient(),
        gate_checker=lambda *args, **kwargs: {"fingerprint": "verified-fixture"},
        workhorse_enabled=True,
        correction_refiner=refiner,
        cloud_teacher_config_path=cloud_config_path,
        map_qa_validator=validate_map,
    )

    review = json.loads((output / "autonomy_review_draft/report.json").read_text())
    draft = np.asarray(Image.open(output / "autonomy_review_draft/label_map_part.png"))
    assert review["promoted_for_human_review"] is True
    assert review["authoritative_human_gold"] is False
    assert review["applied"][0]["candidate_id"] == "local_correction_r1"
    assert status["autonomy"]["status_counts"] == {"machine_verified_candidate": 1}
    assert validation_tags == ["left_forearm_local_r1", "autonomy_review_draft"]
    assert np.count_nonzero(draft == 18) == 29 * 30
    assert np.array_equal(np.asarray(Image.open(part_path)), part)


def test_cloud_teacher_frozen_eval_measures_incremental_value(tmp_path: Path):
    corpus = tmp_path / "benchmark.json"
    corpus.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "frozen": True,
                "provider": "gemini",
                "model": "fake",
                "cases": [
                    _benchmark_case(
                        "a",
                        human="fail",
                        severity="serious",
                        local="fail",
                        teacher="fail",
                        useful=True,
                    ),
                    _benchmark_case(
                        "b",
                        human="fail",
                        severity="minor",
                        local="pass",
                        teacher="fail",
                        useful=True,
                    ),
                    _benchmark_case(
                        "c",
                        human="pass",
                        severity="none",
                        local="pass",
                        teacher="pass",
                        useful=None,
                    ),
                    _benchmark_case(
                        "d",
                        human="pass",
                        severity="none",
                        local="pass",
                        teacher="pass",
                        useful=None,
                    ),
                ],
            }
        ),
        encoding="utf-8",
    )
    thresholds = dict(load_cloud_teacher_config()["evaluation"])
    thresholds["minimum_cases"] = 4
    report = evaluate_cloud_teacher_corpus(corpus, thresholds=thresholds)
    assert report.passed
    assert report.serious_defect_recall == 1
    assert report.overall_defect_recall == 1
    assert report.incremental_recall_over_local == 0.5
    assert report.cost_per_useful_correction_usd == 0.04


def test_cloud_teacher_eval_rejects_pass_everything_and_unfrozen_truth(tmp_path: Path):
    document = {
        "schema_version": "1.0.0",
        "frozen": True,
        "provider": "openai",
        "model": "fake",
        "cases": [
            _benchmark_case(
                "a", human="fail", severity="serious", local="pass", teacher="pass", useful=None
            ),
            _benchmark_case(
                "b", human="pass", severity="none", local="pass", teacher="pass", useful=None
            ),
        ],
    }
    corpus = tmp_path / "benchmark.json"
    corpus.write_text(json.dumps(document), encoding="utf-8")
    thresholds = dict(load_cloud_teacher_config()["evaluation"])
    thresholds["minimum_cases"] = 2
    report = evaluate_cloud_teacher_corpus(corpus, thresholds=thresholds)
    assert not report.passed
    assert report.false_pass_rate == 1
    document["frozen"] = False
    corpus.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(CloudTeacherEvalError, match="must be schema"):
        evaluate_cloud_teacher_corpus(corpus, thresholds=thresholds)


def test_cloud_teacher_eval_cli_is_offline(tmp_path: Path):
    cases = [
        _benchmark_case(
            f"bad_{index}",
            human="fail",
            severity="serious",
            local="pass",
            teacher="fail",
            useful=True,
        )
        for index in range(100)
    ] + [
        _benchmark_case(
            f"good_{index}",
            human="pass",
            severity="none",
            local="pass",
            teacher="pass",
            useful=None,
        )
        for index in range(100)
    ]
    corpus = tmp_path / "benchmark.json"
    corpus.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "frozen": True,
                "provider": "gemini",
                "model": "fake",
                "cases": cases,
            }
        ),
        encoding="utf-8",
    )
    config = load_cloud_teacher_config()
    config_path = tmp_path / "cloud.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    output = tmp_path / "report.json"
    result = CliRunner().invoke(
        main,
        [
            "vlmqa",
            "evaluate-cloud-teacher",
            str(corpus),
            "--config",
            str(config_path),
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert output.is_file()
