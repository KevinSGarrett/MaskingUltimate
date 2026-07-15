import json
from pathlib import Path

import pytest

from maskfactory.vlm.text import (
    TextLlmError,
    cluster_failure_reasons,
    lint_manifest,
    run_manifest_lint_sweep,
)


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


def test_manifest_lint_retries_and_enforces_text_only_contract(tmp_path: Path) -> None:
    valid = json.dumps(
        {
            "findings": [
                {
                    "severity": "WARN",
                    "path": "/notes",
                    "problem": "review note is vague",
                    "suggestion": "name the uncertain boundary",
                }
            ],
            "overall": "needs_human",
        }
    )
    client = Client(["not json", valid])
    result = lint_manifest(
        {"image_id": "img_a3f9c2e17b04", "notes": "check"},
        client=client,
        model="qwen2.5:7b-instruct",
        prompt_version="p-manifest-v1-doc10",
    )
    assert result["overall"] == "needs_human"
    assert result["findings"][0]["path"] == "/notes"
    assert all(call["images"] == () for call in client.calls)
    assert all(
        call["options"] == {"temperature": 0, "seed": 1337, "num_predict": 1024}
        for call in client.calls
    )
    assert len(result["prompt_sha256"]) == len(result["response_sha256"]) == 64


def test_manifest_sweep_uses_configured_model_and_blocks_malformed_json(tmp_path: Path) -> None:
    root = tmp_path / "packages"
    good = root / "img_a3f9c2e17b04/instances/p0"
    bad = root / "img_b3f9c2e17b04/instances/p0"
    good.mkdir(parents=True)
    bad.mkdir(parents=True)
    (good / "manifest.json").write_text(json.dumps({"image_id": "img_a3f9c2e17b04"}))
    (bad / "manifest.json").write_text("bad json")
    config = tmp_path / "vlm.yaml"
    config.write_text(
        "runtime:\n  base_url: http://127.0.0.1:11434\n"
        "models:\n  text_llm: qwen2.5:7b-instruct\n"
        "prompts:\n  p_manifest:\n    version: p-manifest-v1-doc10\n"
    )
    client = Client([json.dumps({"findings": [], "overall": "pass"})])
    output = run_manifest_lint_sweep(
        packages_root=root,
        output_path=tmp_path / "report.json",
        client=client,
        vlm_config_path=config,
    )
    report = json.loads(output.read_text())
    assert report["package_count"] == 2
    assert report["model"] == "qwen2.5:7b-instruct"
    assert sum(item["model_called"] for item in report["packages"]) == 1
    malformed = next(item for item in report["packages"] if not item["model_called"])
    assert malformed["findings"][0]["severity"] == "BLOCK"


def test_manifest_lint_rejects_findings_marked_pass(tmp_path: Path) -> None:
    invalid = json.dumps(
        {
            "findings": [
                {
                    "severity": "WARN",
                    "path": "/notes",
                    "problem": "vague",
                    "suggestion": "clarify",
                }
            ],
            "overall": "pass",
        }
    )
    client = Client([invalid, invalid])
    with pytest.raises(TextLlmError, match="P-MANIFEST"):
        lint_manifest(
            {"image_id": "img_a3f9c2e17b04"},
            client=client,
            model="qwen2.5:7b-instruct",
            prompt_version="p-manifest-v1-doc10",
        )


def test_manifest_sweep_only_lints_new_or_changed_authoritative_packages(tmp_path: Path) -> None:
    root = tmp_path / "packages"
    legacy = root / "img_legacy"
    instance = root / "img_multi/instances/p0"
    derivative = instance / "masks_derived"
    for directory in (legacy, instance, derivative):
        directory.mkdir(parents=True, exist_ok=True)
    (legacy / "manifest.json").write_text(json.dumps({"image_id": "img_legacy"}))
    instance_path = instance / "manifest.json"
    instance_path.write_text(json.dumps({"image_id": "img_multi", "parts": {}}))
    (derivative / "manifest.json").write_text(json.dumps({"derived": True}))
    config = tmp_path / "vlm.yaml"
    config.write_text(
        "runtime:\n  base_url: http://127.0.0.1:11434\n"
        "models:\n  text_llm: qwen2.5:7b-instruct\n"
        "prompts:\n  p_manifest:\n    version: p-manifest-v1-doc10\n"
    )
    pass_response = json.dumps({"findings": [], "overall": "pass"})
    state = tmp_path / "state.json"
    first_client = Client([pass_response, pass_response])
    first = run_manifest_lint_sweep(
        packages_root=root,
        output_path=tmp_path / "first.json",
        state_path=state,
        client=first_client,
        vlm_config_path=config,
    )
    first_report = json.loads(first.read_text())
    assert first_report["discovered_manifest_count"] == 2
    assert first_report["package_count"] == 2
    assert len(first_client.calls) == 2

    second_client = Client([])
    second = run_manifest_lint_sweep(
        packages_root=root,
        output_path=tmp_path / "second.json",
        state_path=state,
        client=second_client,
        vlm_config_path=config,
    )
    second_report = json.loads(second.read_text())
    assert second_report["package_count"] == 0
    assert second_report["skipped_unchanged_count"] == 2
    assert second_client.calls == []

    instance_path.write_text(json.dumps({"image_id": "img_multi", "parts": {"hair": {}}}))
    changed_client = Client([pass_response])
    changed = run_manifest_lint_sweep(
        packages_root=root,
        output_path=tmp_path / "changed.json",
        state_path=state,
        client=changed_client,
        vlm_config_path=config,
    )
    changed_report = json.loads(changed.read_text())
    assert changed_report["package_count"] == 1
    assert changed_report["skipped_unchanged_count"] == 1
    assert changed_report["packages"][0]["package"].endswith("p0")
