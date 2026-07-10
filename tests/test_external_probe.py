import hashlib
import json
from pathlib import Path

import yaml
from click.testing import CliRunner

from maskfactory.cli import main
from maskfactory.providers.probe import probe_external_sources


def _write_probe_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    weight = tmp_path / "weights" / "provider.onnx"
    weight.parent.mkdir()
    weight.write_bytes(b"fixture-model-weights")
    config = {
        "providers": {
            "installed_provider": {
                "source_url": "https://example.invalid/model",
                "license": "fixture",
                "version": "v1",
                "local_path": str(weight),
                "output_type": "fixture map",
                "role": "fixture candidate",
                "authority_level": "proposal only",
            },
            "missing_provider": {
                "source_url": "https://example.invalid/missing",
                "license": "fixture",
                "version": "v2",
                "local_path": "missing/model.pt",
                "output_type": "fixture map",
                "role": "fallback fixture",
                "authority_level": "proposal only",
            },
            "openpose": {
                "source_url": "https://example.invalid/reference",
                "license": "fixture",
                "version": "reference",
                "local_path": "(not installed; fixture reference)",
                "output_type": "keypoints",
                "role": "reference only",
                "authority_level": "geometry reference",
            },
        }
    }
    config_path = tmp_path / "external_sources.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    workflows = {
        "records": [
            {
                "id": 1,
                "name": "Fixture workflow",
                "version": "v1",
                "file_name": "fixture.json",
                "classification": "comfyui_graph_reference",
                "download_status": "downloaded",
                "source_url": "https://example.invalid/workflow",
                "sha256": "a" * 64,
                "authority": "proposal_or_reference_only",
            }
        ]
    }
    workflow_path = tmp_path / "workflows.json"
    workflow_path.write_text(json.dumps(workflows), encoding="utf-8")
    return config_path, workflow_path, weight


def test_probe_hashes_files_and_reports_explicit_statuses(tmp_path: Path) -> None:
    config_path, workflow_path, weight = _write_probe_inputs(tmp_path)
    output_path = tmp_path / "report.json"

    report = probe_external_sources(
        config_path=config_path,
        workflow_path=workflow_path,
        output_path=output_path,
        root=tmp_path,
    )

    assert output_path.exists()
    assert report["read_only"] is True
    assert report["downloads_attempted"] == 0
    assert report["summary"] == {
        "provider_count": 3,
        "available": 1,
        "missing": 1,
        "reference_only": 1,
    }
    providers = {provider["provider"]: provider for provider in report["providers"]}
    assert (
        providers["installed_provider"]["files"][0]["sha256"]
        == hashlib.sha256(weight.read_bytes()).hexdigest()
    )
    assert providers["missing_provider"]["degraded"] is True
    assert providers["openpose"]["fallback_providers"] == ["dwpose"]
    assert report["workflow_references"][0]["sha256"] == "a" * 64


def test_external_probe_cli_writes_json_without_downloading(tmp_path: Path) -> None:
    config_path, workflow_path, _ = _write_probe_inputs(tmp_path)
    output_path = tmp_path / "cli-report.json"

    result = CliRunner().invoke(
        main,
        [
            "external",
            "probe",
            "--config",
            str(config_path),
            "--workflows",
            str(workflow_path),
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "providers=3 available=1 missing=1 reference_only=1" in result.output
    assert "downloads_attempted=0" in result.output
    assert json.loads(output_path.read_text(encoding="utf-8"))["downloads_attempted"] == 0
