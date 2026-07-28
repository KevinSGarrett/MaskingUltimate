"""Unit tests for strict self-hosted VLM gate (fail-closed, no live Ollama required)."""

from __future__ import annotations

from pathlib import Path

import yaml

from maskfactory.vlm.strict_gate import (
    STRICT_PROMPT_VERSION,
    build_strict_prompt,
    decide_outcome,
    load_strict_gate_config,
    parse_strict_response,
    prompt_sha256,
    run_strict_visual_review,
)

ROOT = Path(__file__).resolve().parents[1]


def _valid_payload(verdict: str = "pass", *, dim_fail: str | None = None) -> dict:
    rubric = {
        d: {"verdict": "pass", "reason": "ok"}
        for d in (
            "anatomy",
            "boundary",
            "leakage",
            "emptiness",
            "label_consistency",
            "overlay_contour_review",
        )
    }
    if dim_fail:
        rubric[dim_fail] = {"verdict": "fail", "reason": "bad"}
    return {
        "verdict": verdict,
        "confidence": 0.9,
        "problems": [],
        "evidence": "left tile shows clean silhouette",
        "correction_instruction": "none",
        "rubric": rubric,
    }


def test_strict_gate_config_loads_high_end_primary() -> None:
    cfg = load_strict_gate_config(ROOT)
    assert cfg.primary_vlm == "llava:13b"
    assert cfg.secondary_ensemble_vlm == "qwen2.5vl:7b"
    assert cfg.allow_skip_vlm is False
    assert cfg.temperature == 0
    assert cfg.seed == 1337


def test_parse_and_decide_fail_on_rubric_dimension() -> None:
    raw = {"message": {"content": __import__("json").dumps(_valid_payload(dim_fail="leakage"))}}
    parsed = parse_strict_response(raw)
    cfg = load_strict_gate_config(ROOT)
    outcome, blocker = decide_outcome(primary=parsed, ensemble=parsed, cfg=cfg)
    assert outcome == "ABSTAIN_BOUNDED"
    assert blocker == "strict_vlm_fail"


def test_ensemble_must_agree_for_pass() -> None:
    cfg = load_strict_gate_config(ROOT)
    primary = _valid_payload("pass")
    ensemble = _valid_payload("uncertain")
    outcome, blocker = decide_outcome(primary=primary, ensemble=ensemble, cfg=cfg)
    assert outcome == "ABSTAIN_BOUNDED"
    assert blocker == "ensemble_not_pass"


def test_force_disable_and_skip_are_blocked() -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    disabled = run_strict_visual_review(
        repo_root=ROOT, panel_png=png, label="hand", force_disable_critic=True
    )
    assert disabled.outcome == "VISUAL_CRITIC_BLOCKED"
    skipped = run_strict_visual_review(repo_root=ROOT, panel_png=png, label="hand", skip_vlm=True)
    assert skipped.outcome == "VISUAL_CRITIC_BLOCKED"
    assert skipped.blocker == "skip_vlm_forbidden_under_strict_gate"


def test_prompt_hash_stable() -> None:
    p = build_strict_prompt(label="hand", context="solo")
    assert STRICT_PROMPT_VERSION.startswith("strict-visual-gate")
    assert "SCOPE=HAND ONLY" in p
    assert "WHITE hand regions" in p or "small white" in p.lower()
    assert len(prompt_sha256(p)) == 64
    # yaml still has governance non-authoritative
    config = yaml.safe_load((ROOT / "configs" / "vlm.yaml").read_text(encoding="utf-8"))
    assert config["governance"]["may_clear_blocks"] is False


def test_parse_soft_fills_missing_correction_and_truncates() -> None:
    payload = _valid_payload("pass")
    del payload["correction_instruction"]
    payload["evidence"] = " ".join(["word"] * 50)
    raw = {"message": {"content": __import__("json").dumps(payload)}}
    parsed = parse_strict_response(raw)
    assert parsed["correction_instruction"] == "none"
    assert len(parsed["evidence"].split()) <= 40


def test_parse_extracts_fenced_json() -> None:
    payload = _valid_payload("fail", dim_fail="emptiness")
    fenced = "```json\n" + __import__("json").dumps(payload) + "\n```"
    parsed = parse_strict_response({"message": {"content": fenced}})
    assert parsed["verdict"] == "fail"


def test_parse_synthesizes_rubric_for_truncated_fail() -> None:
    payload = {
        "verdict": "fail",
        "confidence": 0.9,
        "problems": ["wrong_part"],
        "evidence": "mask wrong",
        "correction_instruction": "fix mask",
    }
    parsed = parse_strict_response({"message": {"content": __import__("json").dumps(payload)}})
    assert "rubric" in parsed
    assert parsed["rubric"]["anatomy"]["verdict"] == "fail"


def test_truncated_primary_does_not_demote() -> None:
    from maskfactory.vlm.strict_gate import StrictGateConfig, decide_outcome

    primary = parse_strict_response(
        {
            "message": {
                "content": __import__("json").dumps(
                    {
                        "verdict": "fail",
                        "confidence": 0.9,
                        "problems": ["other"],
                        "evidence": "truncated",
                        "correction_instruction": "retry",
                    }
                )
            }
        }
    )
    assert primary["rubric"]["anatomy"]["reason"] == "synthesized_from_truncated_response"
    cfg = StrictGateConfig(
        enabled=True,
        primary_vlm="llava:13b",
        alternate_high_end_vlm="llama3.2-vision:11b",
        secondary_ensemble_vlm="qwen2.5vl:7b",
        require_ensemble_for_pass=True,
        temperature=0.0,
        seed=1337,
        num_predict=1280,
        base_url="http://127.0.0.1:11434",
        fail_closed_if_unavailable=True,
        allow_skip_vlm=False,
        min_pass_confidence=0.75,
        panels_required=("source", "mask", "overlay"),
        mandatory_for=("hand_clothing_climb",),
        rubric_dimensions=tuple(primary["rubric"].keys()),
        may_author_masks=False,
        may_approve_gold=False,
        may_clear_blocks=False,
        unload_after_burst=True,
    )
    outcome, blocker = decide_outcome(primary=primary, ensemble=None, cfg=cfg)
    assert outcome == "VISUAL_CRITIC_BLOCKED"
    assert blocker == "strict_vlm_truncated_primary"
