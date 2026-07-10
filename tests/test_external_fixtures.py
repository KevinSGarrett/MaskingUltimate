import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image

from maskfactory.cli import main
from maskfactory.providers.fixtures import SelfTestRunner, run_external_fixtures


def _fixture_image(directory: Path) -> Path:
    directory.mkdir(parents=True)
    y, x = np.mgrid[:32, :48]
    image = np.stack(((x * 5) % 256, (y * 8) % 256, ((x + y) * 3) % 256), axis=2).astype(np.uint8)
    path = directory / "synthetic.png"
    Image.fromarray(image, mode="RGB").save(path)
    return path


def test_fixture_run_preserves_raw_outputs_provenance_and_panel(tmp_path: Path) -> None:
    fixtures_dir = tmp_path / "fixtures"
    source_path = _fixture_image(fixtures_dir)
    output_root = tmp_path / "raw-run"

    manifest = run_external_fixtures(
        fixtures_dir=fixtures_dir,
        output_root=output_root,
        runners=[SelfTestRunner()],
        project_root=tmp_path,
    )

    assert manifest["raw_outputs_preserved_before_visualization"] is True
    assert manifest["promoted_to_gold"] is False
    assert manifest["gold_output_forbidden"] is True
    fixture = manifest["fixtures"][0]
    expected_source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert fixture["source_image_sha256"] == expected_source_hash
    provider = fixture["providers"][0]
    assert provider["source_image_sha256"] == expected_source_hash
    assert provider["provider"] == "maskfactory_self_test"
    assert provider["version"] == "1"
    assert provider["source_url"].startswith("internal://")
    assert provider["authority"] == "proposal_only_never_gold"
    assert {output["name"] for output in provider["outputs"]} == {
        "silhouette",
        "parsing",
        "pose",
        "densepose",
        "sam2_proposal",
    }
    for output in provider["outputs"]:
        path = Path(output["path"])
        assert hashlib.sha256(path.read_bytes()).hexdigest() == output["sha256"]
        np.load(path, allow_pickle=False)
    panel = Image.open(fixture["panel_path"])
    assert panel.size == (512 * 7, 512)
    persisted = json.loads((output_root / "run_manifest.json").read_text(encoding="utf-8"))
    assert persisted["promoted_to_gold"] is False


def test_fixture_run_structurally_rejects_gold_package_output(tmp_path: Path) -> None:
    fixtures_dir = tmp_path / "fixtures"
    _fixture_image(fixtures_dir)

    with pytest.raises(ValueError, match="never be written under data/packages"):
        run_external_fixtures(
            fixtures_dir=fixtures_dir,
            output_root=tmp_path / "data" / "packages" / "bad",
            runners=[SelfTestRunner()],
            project_root=tmp_path,
        )


def test_run_fixtures_cli_self_test(tmp_path: Path) -> None:
    fixtures_dir = tmp_path / "fixtures"
    _fixture_image(fixtures_dir)
    output_root = tmp_path / "cli-run"

    result = CliRunner().invoke(
        main,
        [
            "external",
            "run-fixtures",
            "--fixtures-dir",
            str(fixtures_dir),
            "--output-root",
            str(output_root),
            "--self-test",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "fixtures=1 runners=1 raw_before_visualization=True" in result.output
    assert "promoted_to_gold=False" in result.output
