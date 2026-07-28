import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image

from maskfactory.cli import main
from maskfactory.serve.benchmark import (
    LatencyBenchmarkError,
    canonical_all_labels,
    evaluate_latency_samples,
    run_latency_benchmark,
    write_latency_report,
)


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class _Process:
    def __init__(self) -> None:
        self.closed = False

    def poll(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


def test_latency_gate_uses_worst_case_and_exact_thresholds() -> None:
    passing = evaluate_latency_samples(
        cold_start_sec=60,
        predict_all_sec=[1, 2, 4],
        predict_single_sec=[1, 1.5, 2],
        refine_click_sec=[0.8, 1, 1.2],
    )
    assert passing["passed"] is True
    assert passing["checks"]["predict_all_warm"]["max_sec"] == 4
    failing = evaluate_latency_samples(
        cold_start_sec=60.000001,
        predict_all_sec=[1, 2, 4.000001],
        predict_single_sec=[1, 1.5, 2.000001],
        refine_click_sec=[0.8, 1, 1.200001],
    )
    assert failing["passed"] is False
    assert all(not check["passed"] for check in failing["checks"].values())


@pytest.mark.parametrize("values", [[], [1, 2], [1, float("nan"), 2], [1, -1, 2]])
def test_latency_gate_refuses_incomplete_or_invalid_samples(values: list[float]) -> None:
    with pytest.raises(LatencyBenchmarkError):
        evaluate_latency_samples(
            cold_start_sec=1,
            predict_all_sec=values,
            predict_single_sec=[1, 1, 1],
            refine_click_sec=[1, 1, 1],
        )


def test_canonical_all_labels_are_enabled_indexed_and_non_background() -> None:
    labels = canonical_all_labels()
    assert "background" not in labels and "none_background" not in labels
    assert {"left_forearm", "left_index_finger", "strap"}.issubset(labels)
    assert len(labels) == len(set(labels)) == 68


def test_full_benchmark_cold_launches_warms_measures_and_writes(tmp_path: Path) -> None:
    image = tmp_path / "fixture.png"
    Image.new("RGB", (1024, 768), "white").save(image)
    output = tmp_path / "latency.json"
    clock = _Clock()
    state = {"launched": False}
    process = _Process()
    post_counts = {"all": 0, "single": 0, "refine": 0}

    def launch(port: int, log_path: Path) -> _Process:
        assert port == 9876 and log_path.name == "latency.server.log"
        state["launched"] = True
        clock.advance(5.0)
        return process

    def get(_url: str, _timeout: float) -> dict:
        if not state["launched"]:
            raise OSError("connection refused")
        return {"status": "ok", "versions": {"mode_b_api": "1.0.0"}}

    def post(url: str, fields: dict[str, str], _image: bytes, _timeout: float) -> dict:
        if url.endswith("/refine"):
            kind = "refine"
            duration = 0.5
            response = {
                "status": "draft_model_generated",
                "label": fields["label"],
                "mask": "encoded",
            }
        else:
            requested = fields["labels"].split(",")
            kind = "single" if len(requested) == 1 else "all"
            duration = 1.0 if kind == "single" else 3.0
            response = {
                "status": "draft_model_generated",
                "labels": requested,
                "masks": {label: "encoded" for label in requested},
            }
        post_counts[kind] += 1
        clock.advance(duration)
        return response

    path = run_latency_benchmark(
        image,
        output,
        port=9876,
        repetitions=3,
        get_json=get,
        post_multipart=post,
        process_factory=launch,
        clock=clock,
        sleep=clock.advance,
    )
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["passed"] is True and report["all_label_count"] == 68
    assert report["checks"]["cold_start"]["measured_max_sec"] == 5
    assert post_counts == {"all": 4, "single": 4, "refine": 4}
    assert process.closed is True


def test_benchmark_refuses_wrong_image_size_existing_server_and_short_run(tmp_path: Path) -> None:
    image = tmp_path / "small.png"
    Image.new("RGB", (512, 512), "white").save(image)
    with pytest.raises(LatencyBenchmarkError, match="1024"):
        run_latency_benchmark(image, tmp_path / "out.json")

    Image.new("RGB", (1024, 800), "white").save(image)
    with pytest.raises(LatencyBenchmarkError, match="at least three"):
        run_latency_benchmark(image, tmp_path / "out.json", repetitions=2)
    with pytest.raises(LatencyBenchmarkError, match="port to be unused"):
        run_latency_benchmark(
            image,
            tmp_path / "out.json",
            get_json=lambda _url, _timeout: {"status": "ok"},
        )


def test_latency_writer_and_cli_refuse_incomplete_evidence(tmp_path: Path, monkeypatch) -> None:
    with pytest.raises(LatencyBenchmarkError, match="incomplete"):
        write_latency_report(tmp_path / "bad.json", {"item_id": "MF-P6-02.05"})

    image = tmp_path / "fixture.png"
    Image.new("RGB", (1024, 800), "white").save(image)

    def fail(*_args, **_kwargs):
        raise LatencyBenchmarkError("measured failure")

    monkeypatch.setattr("maskfactory.serve.benchmark.run_latency_benchmark", fail)
    result = CliRunner().invoke(main, ["benchmark-serving", str(image)])
    assert result.exit_code != 0 and "measured failure" in result.output
