from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _tool():
    path = Path(__file__).resolve().parents[1] / "tools/run_nude_box_prompt_masks.py"
    spec = importlib.util.spec_from_file_location("run_nude_box_prompt_masks", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(module, body):
    return module._canonical_sha256(body)


def test_source_shard_mapping_preserves_reference_only_role(tmp_path: Path):
    module = _tool()
    body = {
        "schema_version": "maskfactory.nude_batch_shard.v1",
        "sample_count": 1,
        "samples": [
            {
                "sample_id": "sample-a",
                "source_role": "reference_and_tournament_input",
                "source_labels": [],
                "annotation_ref": None,
                "source_path_readonly": "/workspace/assets/MaskedWarehouse/Nude/source.jpg",
            }
        ],
    }
    shard = {**body, "self_sha256": _sha(module, body)}
    path = tmp_path / "shard.json"
    path.write_text(json.dumps(shard), encoding="utf-8")
    assert module._source_paths_from_shard(path) == {
        "sample-a": Path("/workspace/assets/MaskedWarehouse/Nude/source.jpg")
    }

    shard["samples"][0]["source_labels"] = ["person"]
    changed = {key: value for key, value in shard.items() if key != "self_sha256"}
    shard["self_sha256"] = _sha(module, changed)
    path.write_text(json.dumps(shard), encoding="utf-8")
    with pytest.raises(ValueError, match="reference-only role drifted"):
        module._source_paths_from_shard(path)


def test_direct_sam31_executor_rejects_unexpected_launcher():
    module = _tool()
    with pytest.raises(ValueError, match="unexpected launcher prefix"):
        module._direct_linux_executor(("python", "tool.py"), 1)
