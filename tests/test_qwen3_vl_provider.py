from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from maskfactory.providers.contracts import VlmReviewer
from maskfactory.providers.qwen3_vl import (
    QWEN3_VL_VARIANTS,
    Qwen3VlmProviderError,
    Qwen3VlmReviewer,
)


class FakeClient:
    def __init__(self, response: str):
        self.response = response
        self.requests = []

    def generate(self, **request):
        self.requests.append(request)
        return self.response


def _tags(provider_key: str) -> dict:
    variant = QWEN3_VL_VARIANTS[provider_key]
    return {
        variant["model"]: {
            "digest": variant["digest"],
            "details": {"family": "qwen3vl", "quantization_level": "Q4_K_M"},
            "capabilities": ["vision", "completion", "tools"],
        }
    }


def _valid_verdict() -> str:
    return json.dumps(
        {
            "verdict": "fail",
            "confidence": 0.82,
            "problems": ["boundary_too_loose"],
            "evidence": "Loose along the upper contour.",
            "correction_instruction": "Tighten the upper contour.",
        }
    )


@pytest.mark.parametrize("provider_key", sorted(QWEN3_VL_VARIANTS))
def test_qwen3_vl_conforms_with_exact_local_identity_and_strict_verdict(
    tmp_path: Path, provider_key: str
) -> None:
    image = tmp_path / "source.png"
    mask = tmp_path / "mask.png"
    image.write_bytes(b"source")
    mask.write_bytes(b"mask")
    client = FakeClient(_valid_verdict())
    reviewer = Qwen3VlmReviewer(
        provider_key,
        client=client,
        tag_loader=lambda: _tags(provider_key),
    )
    assert isinstance(reviewer, VlmReviewer)
    result = reviewer.review(
        image,
        masks={"left_forearm": mask},
        evidence={"label": "left_forearm", "qa": "route"},
    )
    assert result["verdict"] == "fail"
    assert reviewer.identity.runtime_fingerprint == QWEN3_VL_VARIANTS[provider_key]["digest"]
    assert client.requests[0]["think"] is False
    assert client.requests[0]["format_schema"]["additionalProperties"] is False
    assert client.requests[0]["options"]["temperature"] == 0
    assert client.requests[0]["options"]["num_ctx"] == 4096


def test_qwen3_vl_fails_closed_on_digest_or_schema_drift(tmp_path: Path) -> None:
    image = tmp_path / "source.png"
    image.write_bytes(b"source")
    reviewer = Qwen3VlmReviewer(
        "qwen3_vl_4b",
        client=FakeClient(_valid_verdict()),
        tag_loader=lambda: {
            QWEN3_VL_VARIANTS["qwen3_vl_4b"]["model"]: {
                "digest": "0" * 64,
                "details": {"family": "qwen3vl", "quantization_level": "Q4_K_M"},
                "capabilities": ["vision"],
            }
        },
    )
    with pytest.raises(Qwen3VlmProviderError, match="digest mismatch"):
        reviewer.review(image, masks={}, evidence={"label": "hair"})

    invalid = Qwen3VlmReviewer(
        "qwen3_vl_4b",
        client=FakeClient('{"verdict":"pass"}'),
        tag_loader=lambda: _tags("qwen3_vl_4b"),
    )
    with pytest.raises(Qwen3VlmProviderError, match="strict verdict schema"):
        invalid.review(image, masks={}, evidence={"label": "hair"})


def test_qwen3_vl_config_is_exact_shadow_and_retains_incumbents() -> None:
    vlm = yaml.safe_load(Path("configs/vlm.yaml").read_text(encoding="utf-8"))
    assert vlm["models"] == {
        "primary_vlm": "qwen2.5vl:7b",
        "fallback_vlm": "llava:13b",
        "text_llm": "qwen2.5:7b-instruct",
        "challengers": [
            "qwen3-vl:4b-instruct-q4_K_M",
            "qwen3-vl:8b-instruct-q4_K_M",
        ],
        "challenger_mode": "shadow_only",
        "llava_retirement_requires_measured_replacement_win": True,
    }
    pipeline = yaml.safe_load(Path("configs/pipeline.yaml").read_text(encoding="utf-8"))
    assert pipeline["provider_roles"]["vlm_reviewer"]["active"] is None
    assert pipeline["provider_roles"]["vlm_reviewer"]["rollback"] == "qwen2_5_vl_7b"
