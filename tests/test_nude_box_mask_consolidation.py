from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from maskfactory.nude_box_mask_consolidation import (
    NudeBoxMaskConsolidationError,
    consolidate_box_prompt_provider_batches,
)
from maskfactory.nude_box_mask_generation import (
    generate_box_prompt_provider_batch,
    validate_box_prompt_provider_batch,
)
from test_nude_box_mask_generation import _fixture, _Provider


def _provider_wave(tmp_path: Path):
    catalog, source_paths = _fixture(tmp_path)
    root = tmp_path / "wave"
    document = generate_box_prompt_provider_batch(
        catalog_batch=catalog,
        source_paths=source_paths,
        provider=_Provider("provider-a", "family-a"),
        output_root=root,
        sample_ids=["sample-a"],
    )
    return catalog, source_paths, document, root


def test_consolidation_materializes_catalog_abstain_and_quarantines_orphan(
    tmp_path: Path,
) -> None:
    catalog, source_paths, document, root = _provider_wave(tmp_path)
    candidate = document["records"][0]["candidates"][0]
    orphan = root / "orphan-sample" / "person_000" / "provider-a.png"
    orphan.parent.mkdir(parents=True)
    shutil.copyfile(root / candidate["artifact_relative_path"], orphan)

    output = tmp_path / "consolidated"
    manifest = consolidate_box_prompt_provider_batches(
        catalog_batch=catalog,
        provider_batches=[(document, root)],
        source_paths=source_paths,
        output_root=output,
    )

    assert manifest["record_count"] == 2
    assert manifest["candidate_count"] == 1
    assert manifest["provider_status_counts"] == {
        "catalog_abstain": 1,
        "generated": 1,
    }
    assert manifest["hard_qc_status_counts"] == {
        "pass": 1,
        "upstream_abstain": 1,
    }
    assert manifest["quarantined_unreferenced_count"] == 1
    provider = json.loads((output / "provider.json").read_text())
    assert (
        validate_box_prompt_provider_batch(
            provider,
            output_root=output / "candidates",
        )
        == provider
    )
    quarantine = json.loads((output / "quarantine.json").read_text())
    assert quarantine["records"][0]["relative_path"] == ("orphan-sample/person_000/provider-a.png")
    assert quarantine["records"][0]["eligible_for_consolidation"] is False
    assert not (output / "candidates" / "orphan-sample").exists()


def test_consolidation_rejects_overlapping_waves_without_publishing(tmp_path: Path) -> None:
    catalog, source_paths, document, root = _provider_wave(tmp_path)
    output = tmp_path / "duplicate-output"
    with pytest.raises(NudeBoxMaskConsolidationError, match="provider_record_overlap"):
        consolidate_box_prompt_provider_batches(
            catalog_batch=catalog,
            provider_batches=[(document, root), (document, root)],
            source_paths=source_paths,
            output_root=output,
        )
    assert not output.exists()


def test_consolidation_refuses_existing_output_root(tmp_path: Path) -> None:
    catalog, source_paths, document, root = _provider_wave(tmp_path)
    output = tmp_path / "existing"
    output.mkdir()
    with pytest.raises(NudeBoxMaskConsolidationError, match="already_exists"):
        consolidate_box_prompt_provider_batches(
            catalog_batch=catalog,
            provider_batches=[(document, root)],
            source_paths=source_paths,
            output_root=output,
        )
