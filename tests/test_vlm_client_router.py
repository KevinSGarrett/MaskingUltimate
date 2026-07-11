import json
from pathlib import Path

import pytest
import yaml
from PIL import Image

from maskfactory.cvat_bridge.push import ReviewInstance, _task_description
from maskfactory.validation import validate_document
from maskfactory.vlm.client import (
    OllamaClient,
    VlmClientError,
    VlmVerdict,
    append_verdict,
    compact_manifest_digest,
    prepare_image_context,
    prepare_panel_input,
    review_part,
)
from maskfactory.vlm.router import cvat_task_description, route
from test_qa_report_schema import valid_report

PROMPT_ROOT = Path("src/maskfactory/vlm/prompts")


def _verdict(verdict="pass", confidence=0.9, instruction="Tighten the upper edge."):
    return VlmVerdict(
        "left_forearm",
        "qa_panels/left_forearm.png",
        "qwen2.5vl:7b",
        "p-part-v1-doc10",
        verdict,
        confidence,
        (),
        "Upper edge near elbow.",
        instruction,
        12,
    )


def test_versioned_prompts_and_config_cover_all_three_contracts() -> None:
    config = yaml.safe_load(Path("configs/vlm.yaml").read_text())
    assert config["runtime"] == {
        "provider": "ollama",
        "base_url": "http://127.0.0.1:11434",
        "container_name": "ollama",
        "cloud_enabled": False,
        "gpu_slot": "exclusive",
    }
    assert set(config["prompts"]) == {"p_part", "p_image", "p_manifest"}
    for name in ("p_part", "p_image", "p_manifest"):
        text = (PROMPT_ROOT / f"{name}.txt").read_text()
        assert "PROMPT_VERSION:" in text and "STRICT JSON only" in text
    assert config["governance"]["may_author_masks"] is False
    assert config["governance"]["may_approve_gold"] is False
    assert config["governance"]["may_clear_blocks"] is False
    with pytest.raises(VlmClientError, match="local-only"):
        OllamaClient("https://example.com")


def test_panel_prep_manifest_digest_and_strict_retry(tmp_path: Path) -> None:
    panel = tmp_path / "panel.png"
    Image.new("RGB", (2560, 512), "gray").save(panel)
    prepared = prepare_panel_input(panel, tmp_path / "prepared.png")
    assert max(Image.open(prepared).size) == 1024
    digest = compact_manifest_digest(
        {"parts": {"hair": {"visibility": "visible", "area_pct": 3.25}}}
    )
    assert digest == "label:state:area_pct\nhair:visible:3.2500"
    context = prepare_image_context(
        panel,
        {"parts": {"hair": {"visibility": "visible", "area_pct": 3.25}}},
        {"checks": [{"id": "QC-021", "result": "warn"}, {"id": "QC-011", "result": "pass"}]},
        output_path=tmp_path / "whole.png",
    )
    assert max(Image.open(context.overlay_path).size) == 1024
    assert context.manifest_digest == digest
    assert context.qa_excerpts == ({"id": "QC-021", "result": "warn"},)

    class FakeClient:
        def __init__(self, responses):
            self.responses = list(responses)
            self.prompts = []

        def generate(self, *, model, prompt, images=()):
            self.prompts.append(prompt)
            return self.responses.pop(0)

    valid = json.dumps(
        {
            "verdict": "fail",
            "confidence": 0.8,
            "problems": ["boundary_too_loose"],
            "evidence": "Loose at upper edge.",
            "correction_instruction": "Tighten the upper edge.",
        }
    )
    client = FakeClient(["not json", valid])
    result = review_part(
        client,
        label="left_forearm",
        panel_path=prepared,
        panel_file="qa_panels/left_forearm.png",
        model="qwen2.5vl:7b",
        prompt_template=(PROMPT_ROOT / "p_part.txt").read_text(),
        prompt_version="p-part-v1-doc10",
        gpu_lock_path=tmp_path / "gpu.lock",
    )
    assert result.verdict == "fail" and len(client.prompts) == 2
    assert client.prompts[1].endswith("JSON only.")
    assert not (tmp_path / "gpu.lock").exists()
    uncertain = review_part(
        FakeClient(["bad", "still bad"]),
        label="hair",
        panel_path=prepared,
        panel_file="qa_panels/hair.png",
        model="qwen2.5vl:7b",
        prompt_template="audit <label>",
        prompt_version="p-part-v1-doc10",
        gpu_lock_path=tmp_path / "gpu2.lock",
    )
    assert uncertain.verdict == "uncertain" and uncertain.confidence == 0
    assert uncertain.correction_instruction == ""


def test_verdict_appends_atomically_and_preserves_qa_schema(tmp_path: Path) -> None:
    report = valid_report()
    report["vlm_review"] = {"model": "qwen2.5vl:7b", "verdicts": []}
    path = tmp_path / "qa_report.json"
    path.write_text(json.dumps(report))
    append_verdict(path, _verdict("fail"))
    document = json.loads(path.read_text())
    assert len(document["vlm_review"]["verdicts"]) == 1
    assert document["vlm_review"]["verdicts"][0]["problems"] == []
    assert not validate_document(document, "qa_report")


def test_router_covers_five_rows_blocks_and_authority_invariants() -> None:
    quick = route("all_pass", _verdict("pass", 0.9))
    assert quick.queue == "quick_pass"
    fail = route("all_pass", _verdict("fail"))
    assert fail.queue == "careful" and fail.correction_hint.startswith("MACHINE-GENERATED")
    assert "MACHINE-GENERATED SUGGESTION" in cvat_task_description("Review task", fail)
    auto_wins = route("route", _verdict("pass"))
    assert auto_wins.queue == "careful" and auto_wins.correction_hint is None
    priority = route("route", _verdict("fail"))
    assert priority.priority == "high" and priority.pin_disagreement_heatmap
    uncertain = route("all_pass", _verdict("uncertain", 0.4))
    assert uncertain.queue == "careful" and uncertain.correction_hint is None
    assert cvat_task_description("Review task", uncertain) == "Review task"
    block = route("block", _verdict("pass", 1.0))
    assert block.queue == "careful" and block.priority == "highest"
    for decision in (quick, fail, auto_wins, priority, uncertain, block):
        assert not decision.may_approve_gold
        assert not decision.may_clear_block
        assert not decision.may_edit_mask


def test_cvat_task_description_attaches_only_machine_marked_fail_suggestions(
    tmp_path: Path,
) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "qa_report.json").write_text(
        json.dumps(
            {
                "vlm_review": {
                    "verdicts": [
                        {
                            "label": "hair",
                            "verdict": "fail",
                            "correction_instruction": "Remove shoulder bleed.",
                        },
                        {
                            "label": "neck",
                            "verdict": "uncertain",
                            "correction_instruction": "Do not show this.",
                        },
                    ]
                }
            }
        )
    )
    instance = ReviewInstance(
        "img_aaaaaaaaaaaa",
        "p0",
        package,
        package / "source.png",
        package / "overlay.png",
        None,
    )
    description = _task_description([instance])
    assert "p0/hair: MACHINE-GENERATED SUGGESTION: Remove shoulder bleed." in description
    assert "Do not show this" not in description
    assert "cannot approve gold" in description
