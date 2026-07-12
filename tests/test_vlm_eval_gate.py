import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image

from maskfactory.cli import main
from maskfactory.ontology import get_ontology
from maskfactory.vlm.eval import (
    DEFECT_TAXONOMY,
    VlmEvalError,
    build_calibration_from_gold_selection,
    build_calibration_from_seed_manifest,
    evaluate_gate,
    generate_calibration_set,
    load_cases,
    require_current_gate,
)


def _gold_selection_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    packages = tmp_path / "packages"
    images = tmp_path / "images"
    target_by_problem = {
        "wrong_side": ("left_forearm", None),
        "boundary_too_loose": ("hair", None),
        "boundary_too_tight": ("left_thigh", None),
        "includes_clothing_as_skin": ("skin", "top_garment"),
        "includes_neighbor_part": ("chest_upper_torso", "left_upper_arm"),
        "missing_visible_area": ("right_calf", None),
        "mask_on_hidden_area": ("left_breast", None),
        "finger_merge": ("left_index_finger", "left_middle_finger"),
        "hair_edge_bad": ("hair", None),
        "occlusion_error": ("right_forearm", "occluding_object"),
    }
    authority = get_ontology()
    cases = []
    for index in range(20):
        problem = DEFECT_TAXONOMY[index % len(DEFECT_TAXONOMY)]
        label, auxiliary = target_by_problem[problem]
        image_id = f"img_{index + 1:012x}"
        package = packages / image_id / "instances/p0"
        package.mkdir(parents=True)
        source = np.full((64, 64, 3), (30 + index, 60 + index, 90 + index), dtype=np.uint8)
        Image.fromarray(source, mode="RGB").save(package / "source.png")
        masks = {label, auxiliary, "right_forearm" if problem == "wrong_side" else None} - {None}
        parts = {}
        for mask_index, name in enumerate(sorted(masks)):
            definition = authority.label(name)
            if definition.mask_type == "protected_qa":
                directory = package / "protected"
            elif definition.map == "material":
                directory = package / "masks_material"
            else:
                directory = package / "masks"
            directory.mkdir(exist_ok=True)
            mask = np.zeros((64, 64), dtype=np.uint8)
            left = 8 + mask_index * 22
            mask[12:52, left : left + 16] = 255
            Image.fromarray(mask, mode="L").save(directory / f"{name}.png")
            parts[name] = {
                "visibility": "not_visible"
                if definition.mask_type == "protected_qa"
                else "visible",
                "status": "n/a"
                if definition.mask_type == "protected_qa"
                else "human_approved_gold",
            }
        manifest = {
            "image_id": image_id,
            "source": {
                "source_file": "source.png",
                "source_origin": "generated",
                "origin_note": f"owned deterministic gold calibration fixture {index}",
            },
            "parts": parts,
            "review": {
                "reviewer": "kevin",
                "approved_at": "2026-07-12T00:00:00+00:00",
                "review_time_sec": 60,
            },
            "qa": {"qa_overall": "pass"},
        }
        (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (package / ".maskfactory_frozen.json").write_text("{}", encoding="utf-8")
        intake = images / image_id
        intake.mkdir(parents=True)
        (intake / "manifest.json").write_text(
            json.dumps({"age_safety": {"verdict": "clear_adult"}}), encoding="utf-8"
        )
        cases.append(
            {
                "id": f"gold_{index:02d}",
                "package": f"{image_id}/instances/p0",
                "label": label,
                "defect_type": problem,
                "auxiliary_label": auxiliary,
            }
        )
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps({"schema_version": "1.0.0", "cases": cases}), encoding="utf-8")
    return selection, packages, images


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
    labels = (
        "hair",
        "right_hand_base",
        "left_forearm",
        "right_foot_base",
        "chest_upper_torso",
    )
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
                "governance": {
                    "source_origin": "generated",
                    "age_safety": "clear_adult",
                    "rights_evidence": "deterministic test fixture generated in this test",
                    "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
                },
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
    assert {source["age_safety"] for source in document["sources"]} == {"clear_adult"}
    assert load_cases(output) == cases


def test_gold_selection_builds_exact_governed_calibration_corpus(tmp_path: Path) -> None:
    selection, packages, images = _gold_selection_fixture(tmp_path)
    output = tmp_path / "vlm_eval"
    cases = build_calibration_from_gold_selection(
        selection,
        output,
        packages_root=packages,
        images_root=images,
        package_verifier=lambda package: (SimpleNamespace(passed=True),),
    )
    assert len(cases) == 40
    assert sum(not case.expected_defect for case in cases) == 20
    assert sum(case.expected_defect for case in cases) == 20
    assert load_cases(output) == cases
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["corpus_authority"] == "explicit_source_good_defect_pairs"
    assert len({source["source_sha256"] for source in manifest["sources"]}) == 20
    assert {source["age_safety"] for source in manifest["sources"]} == {"clear_adult"}
    assert (output / "seeds/manifest.json").is_file()


def test_gold_selection_refuses_unapproved_or_unverified_packages(tmp_path: Path) -> None:
    selection, packages, images = _gold_selection_fixture(tmp_path)
    first = packages / "img_000000000001/instances/p0"
    manifest_path = first / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["review"]["approved_at"] = None
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(VlmEvalError, match="lacks approval"):
        build_calibration_from_gold_selection(
            selection,
            tmp_path / "unapproved",
            packages_root=packages,
            images_root=images,
            package_verifier=lambda package: (SimpleNamespace(passed=True),),
        )

    manifest["review"]["approved_at"] = "2026-07-12T00:00:00+00:00"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(VlmEvalError, match="fails format/hash verification"):
        build_calibration_from_gold_selection(
            selection,
            tmp_path / "unverified",
            packages_root=packages,
            images_root=images,
            package_verifier=lambda package: (SimpleNamespace(passed=False),),
        )


def test_vlmqa_build_calibration_cli_reports_exact_balance(tmp_path: Path, monkeypatch) -> None:
    selection = tmp_path / "selection.json"
    selection.write_text("{}", encoding="utf-8")
    packages = tmp_path / "packages"
    images = tmp_path / "images"
    packages.mkdir()
    images.mkdir()
    fixture_cases = tuple(
        [SimpleNamespace(expected_defect=False) for _ in range(20)]
        + [SimpleNamespace(expected_defect=True) for _ in range(20)]
    )
    monkeypatch.setattr(
        "maskfactory.vlm.eval.build_calibration_from_gold_selection",
        lambda *args, **kwargs: fixture_cases,
    )
    output = tmp_path / "vlm_eval"
    result = CliRunner().invoke(
        main,
        [
            "vlmqa",
            "build-calibration",
            "--selection",
            str(selection),
            "--packages-root",
            str(packages),
            "--images-root",
            str(images),
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "output": str(output),
        "total": 40,
        "good": 20,
        "defect": 20,
    }


def test_production_builder_refuses_duplicate_or_ungoverned_sources(tmp_path: Path) -> None:
    seeds_root = tmp_path / "seeds"
    seeds_root.mkdir()
    source_path = seeds_root / "source.png"
    good_path = seeds_root / "good.png"
    defect_path = seeds_root / "defect.png"
    Image.fromarray(np.full((20, 20, 3), 80, dtype=np.uint8), mode="RGB").save(source_path)
    good = np.zeros((20, 20), dtype=np.uint8)
    good[4:12, 4:12] = 255
    defect = good.copy()
    defect[15:18, 15:18] = 255
    Image.fromarray(good, mode="L").save(good_path)
    Image.fromarray(defect, mode="L").save(defect_path)
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    seeds = [
        {
            "id": f"seed_{index:02d}",
            "label": (
                "hair",
                "right_hand_base",
                "left_forearm",
                "right_foot_base",
                "chest_upper_torso",
            )[index % 5],
            "source": source_path.name,
            "good_mask": good_path.name,
            "defect_mask": defect_path.name,
            "defect_type": DEFECT_TAXONOMY[index % len(DEFECT_TAXONOMY)],
            "governance": {
                "source_origin": "owned_photo",
                "age_safety": "clear_adult",
                "rights_evidence": "fixture",
                "source_sha256": digest,
            },
        }
        for index in range(20)
    ]
    manifest = seeds_root / "manifest.json"
    manifest.write_text(json.dumps({"seeds": seeds}), encoding="utf-8")
    with pytest.raises(VlmEvalError, match="20 distinct source images"):
        build_calibration_from_seed_manifest(manifest, tmp_path / "output")

    seeds[0]["governance"]["age_safety"] = "uncertain"
    manifest.write_text(json.dumps({"seeds": seeds}), encoding="utf-8")
    with pytest.raises(VlmEvalError, match="not age-cleared adult"):
        build_calibration_from_seed_manifest(manifest, tmp_path / "output")


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
