import json
from pathlib import Path

import pytest

from maskfactory.vlm.text import TextLlmError, cluster_failure_reasons


class Client:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls = []

    def generate(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return self.responses.pop(0)


def test_text_llm_clustering_retries_then_seals_complete_mapping(tmp_path: Path) -> None:
    valid = json.dumps(
        {
            "clusters": {
                "finger_merge": "hands_fingers",
                "hair_edge": "hair_boundary",
            },
            "coverage_targets": ["fingers_spread", "hair_occlusion"],
            "weekly_summary": "Acquire difficult hand and hair-boundary examples.",
        }
    )
    client = Client(["not json", valid])
    path = tmp_path / "clustering.json"

    mapping = cluster_failure_reasons(
        ("hair_edge", "finger_merge", "hair_edge"),
        client=client,
        model="qwen2.5:7b-instruct",
        prompt_version="failure-cluster-v1-doc10",
        output_path=path,
    )

    assert mapping == {"finger_merge": "hands_fingers", "hair_edge": "hair_boundary"}
    assert len(client.calls) == 2
    assert client.calls[0]["images"] == ()
    assert client.calls[0]["options"] == {"temperature": 0, "seed": 1337}
    evidence = json.loads(path.read_text())
    assert evidence["input_reasons"] == ["finger_merge", "hair_edge"]
    assert evidence["model_called"] is True
    assert len(evidence["prompt_sha256"]) == len(evidence["response_sha256"]) == 64


def test_text_llm_clustering_refuses_omitted_reason_after_retry(tmp_path: Path) -> None:
    incomplete = json.dumps(
        {
            "clusters": {"finger_merge": "hands_fingers"},
            "coverage_targets": [],
            "weekly_summary": "Incomplete.",
        }
    )
    client = Client([incomplete, incomplete])
    with pytest.raises(TextLlmError, match="after one retry"):
        cluster_failure_reasons(
            ("finger_merge", "hair_edge"),
            client=client,
            model="qwen2.5:7b-instruct",
            prompt_version="failure-cluster-v1-doc10",
            output_path=tmp_path / "must_not_exist.json",
        )
    assert not (tmp_path / "must_not_exist.json").exists()


def test_empty_failure_set_writes_no_model_call_evidence(tmp_path: Path) -> None:
    client = Client([])
    path = tmp_path / "empty.json"
    assert (
        cluster_failure_reasons(
            (),
            client=client,
            model="qwen2.5:7b-instruct",
            prompt_version="failure-cluster-v1-doc10",
            output_path=path,
        )
        == {}
    )
    assert client.calls == []
    assert json.loads(path.read_text())["model_called"] is False
