import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.providers.discovery import (
    ProviderDiscoveryError,
    import_planned_challenger,
)

ROOT = Path(__file__).resolve().parents[1]


def _discovery(key: str, timestamp: str) -> dict:
    document = {
        "provider_key": key,
        "discovered_at": timestamp,
        "source_url": f"https://example.invalid/{key}",
        "component": f"fixture discovery {key}",
        "target_role": "concept_detector",
        "output_type": "fixture proposals",
    }
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    document["evidence_sha256"] = hashlib.sha256(canonical).hexdigest()
    return document


def _workspace(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    external = tmp_path / "external_sources.yaml"
    pipeline = tmp_path / "pipeline.yaml"
    models = tmp_path / "model_registry.json"
    history = tmp_path / "provider_discoveries.jsonl"
    external.write_bytes((ROOT / "configs/external_sources.yaml").read_bytes())
    pipeline.write_bytes((ROOT / "configs/pipeline.yaml").read_bytes())
    models.write_bytes((ROOT / "models/model_registry.json").read_bytes())
    return external, pipeline, models, history


def test_discovery_import_is_planned_only_and_preserves_roles_and_certificates(
    tmp_path: Path,
) -> None:
    external, pipeline, models, history = _workspace(tmp_path)
    original = yaml.safe_load(external.read_text(encoding="utf-8"))
    pipeline_before = pipeline.read_bytes()
    models_before = models.read_bytes()
    record = import_planned_challenger(
        _discovery("future_segmenter", "2026-07-14T12:00:00Z"),
        external_registry_path=external,
        pipeline_path=pipeline,
        model_registry_path=models,
        history_path=history,
    )

    updated = yaml.safe_load(external.read_text(encoding="utf-8"))
    assert updated["providers"]["future_segmenter"]["lifecycle_state"] == "planned"
    assert updated["providers"]["future_segmenter"]["verify_license"] is True
    assert {
        key: value for key, value in updated["providers"].items() if key != "future_segmenter"
    } == original["providers"]
    assert pipeline.read_bytes() == pipeline_before
    assert models.read_bytes() == models_before
    assert record["previous_record_sha256"] is None


def test_discovery_history_is_hash_chained_and_first_record_is_not_rewritten(
    tmp_path: Path,
) -> None:
    external, pipeline, models, history = _workspace(tmp_path)
    first = import_planned_challenger(
        _discovery("future_detector", "2026-07-14T12:00:00Z"),
        external_registry_path=external,
        pipeline_path=pipeline,
        model_registry_path=models,
        history_path=history,
    )
    first_line = history.read_text(encoding="utf-8").splitlines()[0]
    second = import_planned_challenger(
        _discovery("future_reviewer", "2026-07-14T12:01:00Z"),
        external_registry_path=external,
        pipeline_path=pipeline,
        model_registry_path=models,
        history_path=history,
    )
    lines = history.read_text(encoding="utf-8").splitlines()
    assert lines[0] == first_line
    assert len(lines) == 2
    assert second["previous_record_sha256"] == first["record_sha256"]


def test_discovery_cannot_smuggle_active_state_or_rewrite_existing_provider(
    tmp_path: Path,
) -> None:
    external, pipeline, models, history = _workspace(tmp_path)
    original_external = external.read_bytes()
    extra = _discovery("future_geometry", "2026-07-14T12:00:00Z")
    extra["lifecycle_state"] = "promoted"
    with pytest.raises(ProviderDiscoveryError, match="exact fields"):
        import_planned_challenger(
            extra,
            external_registry_path=external,
            pipeline_path=pipeline,
            model_registry_path=models,
            history_path=history,
        )
    assert external.read_bytes() == original_external

    duplicate = copy.deepcopy(_discovery("sam3_1", "2026-07-14T12:00:00Z"))
    with pytest.raises(ProviderDiscoveryError, match="already exists"):
        import_planned_challenger(
            duplicate,
            external_registry_path=external,
            pipeline_path=pipeline,
            model_registry_path=models,
            history_path=history,
        )
    assert external.read_bytes() == original_external


def test_discovery_cli_imports_only_a_planned_challenger(tmp_path: Path) -> None:
    external, pipeline, models, history = _workspace(tmp_path)
    discovery_path = tmp_path / "discovery.json"
    discovery_path.write_text(
        json.dumps(_discovery("future_pose", "2026-07-14T12:02:00Z")),
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        main,
        [
            "external",
            "import-discovery",
            str(discovery_path),
            "--registry",
            str(external),
            "--pipeline",
            str(pipeline),
            "--models",
            str(models),
            "--history",
            str(history),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "provider=future_pose lifecycle=planned" in result.output
    assert (
        yaml.safe_load(external.read_text(encoding="utf-8"))["providers"]["future_pose"][
            "lifecycle_state"
        ]
        == "planned"
    )
