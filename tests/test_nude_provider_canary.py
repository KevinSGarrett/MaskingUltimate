from __future__ import annotations

import json
from pathlib import Path

import pytest

from maskfactory.nude_provider_canary import (
    NudeProviderCanaryError,
    _runtime_bindings,
    _validated_box,
)


def test_bbox_validation_preserves_prompt_geometry_not_pixels() -> None:
    assert _validated_box({"bbox": [2, 3, 10, 12]}, width=32, height=24) == [2, 3, 12, 15]
    with pytest.raises(NudeProviderCanaryError, match="out_of_bounds"):
        _validated_box({"bbox": [30, 3, 10, 12]}, width=32, height=24)


def test_runtime_bindings_require_installed_no_gold_providers(tmp_path: Path) -> None:
    providers = [
        "sam3_1",
        "maskfactory_core",
        "sam2matting_base_plus",
        "sam3_litetext_s0",
    ]
    path = tmp_path / "matrix.json"
    path.write_text(
        json.dumps(
            {
                "runtimes": [
                    {
                        "provider": provider,
                        "status": "live_smoke_passed",
                        "isolation_boundary": provider + "_env",
                        "checkpoint_status": "installed",
                        "may_author_gold": False,
                        "artifacts": [],
                    }
                    for provider in providers
                ]
            }
        ),
        encoding="utf-8",
    )
    assert set(_runtime_bindings(path)) == set(providers)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["runtimes"][0]["may_author_gold"] = True
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(NudeProviderCanaryError, match="authority_invalid"):
        _runtime_bindings(path)
