import json
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image

from maskfactory.cli import main
from maskfactory.vlm.eval import (
    DEFECT_TAXONOMY,
    VlmEvalError,
    build_calibration_from_seed_manifest,
    evaluate_gate,
    generate_calibration_set,
    load_cases,
    require_current_gate,
)


def test_generate_exact_balanced_40_panel_taxonomy(tmp_path: Path) -> None:
    cases = generate_calibration_set(tmp_path, test_fixture=True)
    assert len(cases) == 40
    assert sum(not case.expected_defect for case in cases) == 20
    assert sum(case.expected_defect for case in cases) == 20
    assert {case.seeded_problem for case in cases if case.expected_defect} == set(DEFECT_TAXONOMY)
    assert all((tmp_path / case.panel_file).is_file() for case in cases)
    assert load_cases(tmp_path) == cases
    with pytest.raises(VlmEvalError, match="test-only"):
        generate_calibration_set(tmp_path / "forbidden-production")


def test_production_builder_requires_explicit_unique_good_defect_pairs(
    tmp_path: Path,
) -> None:
    seeds_root = tmp_path / "seeds"
    seeds_root.mkdir()
    labels = ("hair", "right_hand", "left_forearm", "right_foot_base", "chest_upper_torso")
    seeds = []
    for index in range(20):
        source = np.full((80, 100, 3), 40 + index, dtype=np.uint8)
        good = np.zeros((80, 100), dtype=np.uint8)
        good[15:65, 20 + index % 5 : 60 + index % 5] = 255
        defect = good.copy()
        defect[5 + index % 10 : 12 + index % 10, 70:90] = 255
        source_path = seeds_root / f"source_{index:02d}.png"
        good_path = seeds_root / f"good_{index:02d}.png"
        defect_path = seeds_root / f"defect_{index:02d}.png"
        Image.fromarray(source, mode="RGB").save(source_path)
        Image.fromarray(good, mode="L").save(good_path)
        Image.fromarray(defect, mode="L").save(defect_path)
        seeds.append(
            {
                "id": f"seed_{index:02d}",
                "label": labels[index % len(labels)],
                "source": source_path.name,
                "good_mask": good_path.name,
                "defect_mask": defect_path.name,
                "defect_type": DEFECT_TAXONOMY[index % len(DEFECT_TAXONOMY)],
            }
        )
    manifest_path = seeds_root / "manifest.json"
    manifest_path.write_text(json.dumps({"seeds": seeds}), encoding="utf-8")
    output = tmp_path / "production"
    cases = build_calibration_from_seed_manifest(manifest_path, output)
    assert len(cases) == 40
    document = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert document["corpus_authority"] == "explicit_source_good_defect_pairs"
    assert document["answer_text_embedded_in_panels"] is False
    assert len(document["sources"]) == 20
    assert load_cases(output) == cases


def test_eval_thresholds_and_model_prompt_change_invalidation(tmp_path: Path) -> None:
    cases = generate_calibration_set(tmp_path / "set", test_fixture=True)
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("version one")
    perfect = {case.case_id: "fail" if case.expected_defect else "pass" for case in cases}
    report = evaluate_gate(
        cases,
        perfect,
        model="qwen2.5vl:7b",
        prompt_version="p-part-v1-doc10",
        prompt_path=prompt,
        output_dir=tmp_path / "reports",
    )
    assert report.recall == 1 and report.precision == 1 and report.passed
    gate = tmp_path / "reports/production_gate.json"
    assert require_current_gate(
        gate,
        model="qwen2.5vl:7b",
        prompt_version="p-part-v1-doc10",
        prompt_path=prompt,
    )["passed"]
    with pytest.raises(VlmEvalError, match="invalidated"):
        require_current_gate(
            gate,
            model="fallback:1",
            prompt_version="p-part-v1-doc10",
            prompt_path=prompt,
        )
    prompt.write_text("version changed")
    with pytest.raises(VlmEvalError, match="invalidated"):
        require_current_gate(
            gate,
            model="qwen2.5vl:7b",
            prompt_version="p-part-v1-doc10",
            prompt_path=prompt,
        )


def test_gate_refuses_below_recall_or_precision(tmp_path: Path) -> None:
    cases = generate_calibration_set(tmp_path / "set", test_fixture=True)
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("prompt")
    predictions = {case.case_id: "pass" for case in cases}
    report = evaluate_gate(
        cases,
        predictions,
        model="model",
        prompt_version="v1",
        prompt_path=prompt,
        output_dir=tmp_path / "reports",
    )
    assert not report.passed and report.recall == 0
    with pytest.raises(VlmEvalError, match="refused"):
        require_current_gate(
            tmp_path / "reports/production_gate.json",
            model="model",
            prompt_version="v1",
            prompt_path=prompt,
        )


def test_vlmqa_eval_cli_scores_fixed_set(tmp_path: Path) -> None:
    root = tmp_path / "set"
    cases = generate_calibration_set(root, test_fixture=True)
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("fixed prompt", encoding="utf-8")
    predictions = tmp_path / "predictions.json"
    predictions.write_text(
        json.dumps({case.case_id: "fail" if case.expected_defect else "pass" for case in cases}),
        encoding="utf-8",
    )
    output = tmp_path / "results"
    result = CliRunner().invoke(
        main,
        [
            "vlmqa",
            "eval",
            "--calibration-root",
            str(root),
            "--predictions",
            str(predictions),
            "--model",
            "qwen2.5vl:7b",
            "--prompt",
            str(prompt),
            "--output-dir",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert '"passed": true' in result.output
    assert (output / "production_gate.json").is_file()
