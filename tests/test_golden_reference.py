import json
from pathlib import Path

import numpy as np
import pytest
import yaml
from click.testing import CliRunner
from PIL import Image

from maskfactory.cli import main
from maskfactory.golden_reference import (
    GoldenReferenceError,
    import_golden_reference,
    run_reference_cloud_benchmark,
    verify_golden_reference,
)
from maskfactory.io.hashing import sha256_file
from maskfactory.vlm.cloud_teacher import (
    TeacherUsage,
    load_cloud_teacher_config,
    parse_teacher_judgment,
)


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = np.full((8, 6, 3), 80, dtype=np.uint8)
    Image.fromarray(source).save(source_root / "Original.png")
    definitions = {
        "hair": (slice(0, 3), slice(1, 5)),
        "top_clothing": (slice(3, 6), slice(1, 5)),
    }
    for name, region in definitions.items():
        mask = np.zeros((8, 6), dtype=np.uint8)
        mask[region] = 255
        Image.fromarray(np.repeat(mask[:, :, None], 3, axis=2)).save(
            source_root / f"{name}_BW_Masked.png"
        )
        solid = source.copy()
        solid[mask != 0] = (0, 0, 255)
        Image.fromarray(solid).save(source_root / f"{name}_solid.png")
    mapping = {
        "schema_version": "1.0.0",
        "source_file": "Original.png",
        "reviewer_assertion": "test reference",
        "layers": {
            "hair": {
                "category": "ontology_part_candidates",
                "map": "part",
                "target": "hair",
                "mapping_status": "direct_candidate",
                "notes": "test",
            },
            "top_clothing": {
                "category": "ontology_material_candidates",
                "map": "material",
                "target": "top_garment",
                "mapping_status": "direct_candidate",
                "notes": "test",
            },
        },
    }
    mapping_path = tmp_path / "mapping.yaml"
    mapping_path.write_text(yaml.safe_dump(mapping), encoding="utf-8")
    return source_root, mapping_path


def test_reference_import_is_lossless_but_refuses_gold_authority(tmp_path: Path):
    source_root, mapping_path = _fixture(tmp_path)
    output = tmp_path / "normalized"
    manifest = import_golden_reference(source_root, output, mapping_path=mapping_path)
    assert manifest["layer_count"] == 2
    assert manifest["eligible_for_package_gold"] is False
    assert manifest["eligible_for_training"] is False
    assert "hair" in manifest["mapped_part_targets"]
    normalized = Image.open(output / "masks/ontology_part_candidates/hair.png")
    assert normalized.mode == "L" and set(np.unique(normalized)) == {0, 255}
    assert json.loads((output / "reference_manifest.json").read_text())["manifest_sha256"]
    assert verify_golden_reference(output) == ()


def test_reference_import_rejects_solid_disagreement_and_existing_output(tmp_path: Path):
    source_root, mapping_path = _fixture(tmp_path)
    bad = np.asarray(Image.open(source_root / "hair_solid.png")).copy()
    bad[7, 5] = (0, 0, 255)
    Image.fromarray(bad).save(source_root / "hair_solid.png")
    with pytest.raises(GoldenReferenceError, match="changed-pixel mismatch"):
        import_golden_reference(source_root, tmp_path / "normalized", mapping_path=mapping_path)
    (tmp_path / "existing").mkdir()
    with pytest.raises(GoldenReferenceError, match="already exists"):
        import_golden_reference(source_root, tmp_path / "existing", mapping_path=mapping_path)


def test_reference_import_cli_reports_non_gold_status(tmp_path: Path):
    source_root, mapping_path = _fixture(tmp_path)
    output = tmp_path / "normalized"
    result = CliRunner().invoke(
        main,
        [
            "golden-reference",
            "import",
            str(source_root),
            "--mapping",
            str(mapping_path),
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    summary = json.loads(result.output)
    assert summary["eligible_for_package_gold"] is False
    assert summary["layer_count"] == 2
    verified = CliRunner().invoke(main, ["golden-reference", "verify", str(output)])
    assert verified.exit_code == 0 and json.loads(verified.output)["passed"] is True


def test_reference_cloud_benchmark_runs_each_provider_in_shadow(tmp_path: Path):
    source_root, mapping_path = _fixture(tmp_path)
    reference = tmp_path / "normalized"
    manifest = import_golden_reference(source_root, reference, mapping_path=mapping_path)
    config = load_cloud_teacher_config()
    config["budget"]["ledger_path"] = str(tmp_path / "costs.jsonl")
    eligibility = tmp_path / "eligibility.yaml"
    eligibility.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0.0",
                "default": "deny",
                "images": {
                    manifest["image_id"]: {
                        "source_sha256": sha256_file(source_root / "Original.png"),
                        "rights_evidence": "test",
                        "approved_by": "kevin",
                        "approved_at": "2026-07-12T23:00:00Z",
                        "providers": ["gemini", "openai", "anthropic"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    config["governance"]["eligibility_registry"] = str(eligibility)
    config_path = tmp_path / "cloud.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    class Provider:
        maximum_reserved_cost_usd = 0.1

        def __init__(self, name):
            self.name, self.model = name, f"fake-{name}"

        def review(self, request, prompt):
            raw = json.dumps(
                {
                    "verdict": "pass",
                    "confidence": 0.9,
                    "defects": [],
                    "observations": {
                        key: "localized observation"
                        for key in (
                            "full_context",
                            "source_crop",
                            "mask",
                            "overlay",
                            "contour",
                            "neighbor_overlap",
                        )
                    },
                    "evidence": "The test mask follows the target.",
                    "correction": {
                        "tool": "none",
                        "polygon": [],
                        "positive_points": [],
                        "negative_points": [],
                        "rationale": "No correction.",
                    },
                }
            )
            return parse_teacher_judgment(
                raw,
                provider=self.name,
                model=self.model,
                usage=TeacherUsage(10, 10, 0.01),
                latency_ms=1,
            )

    summary = run_reference_cloud_benchmark(
        reference,
        labels=("hair",),
        cloud_config_path=config_path,
        output_root=tmp_path / "benchmark",
        providers={name: Provider(name) for name in ("gemini", "openai", "anthropic")},
    )
    assert len(summary["provider_results"]) == 3
    assert all(row["status"] == "complete" for row in summary["provider_results"])
    assert summary["authority"] == "shadow_only_no_gold_or_mask_authority"
