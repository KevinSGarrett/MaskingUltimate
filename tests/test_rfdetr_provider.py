from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from maskfactory.providers.contracts import BoxProposal, PersonDetector
from maskfactory.providers.rfdetr import (
    RFDETR_CHECKPOINT_SHA256,
    RfdetrPersonDetector,
    RfdetrProviderError,
    compare_person_boxes,
    windows_to_wsl_path,
)


def _detector(tmp_path: Path, report: dict, *, returncode: int = 0) -> RfdetrPersonDetector:
    checkpoint = tmp_path / "rf-detr-medium.pth"
    checkpoint.write_bytes(b"checkpoint-fixture")
    image = tmp_path / "input.jpg"
    image.write_bytes(b"image-fixture")
    report["image"] = {
        "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
    }
    report.setdefault("checkpoint", {"sha256": RFDETR_CHECKPOINT_SHA256})
    report.setdefault("rfdetr", "1.7.1")
    report.setdefault("deterministic", True)
    report.setdefault("repeats", 2)
    report.setdefault("threshold", 0.5)

    def execute(argv, timeout):
        assert argv[0:4] == ("wsl.exe", "-d", "Ubuntu-22.04", "--")
        assert "--repeats" in argv and argv[argv.index("--repeats") + 1] == "2"
        assert timeout == 20
        return subprocess.CompletedProcess(
            argv,
            returncode,
            stdout="provider log\n" + json.dumps(report) + "\n",
            stderr="fixture failure" if returncode else "",
        )

    detector = RfdetrPersonDetector(
        checkpoint=checkpoint,
        timeout_seconds=20,
        executor=execute,
    )
    detector.fixture_image = image  # type: ignore[attr-defined]
    return detector


def _valid_report() -> dict:
    return {
        "detections": [
            {
                "class_id": 1,
                "class_name": "person",
                "confidence": 0.91,
                "xyxy": [10.0, 20.0, 110.0, 220.0],
            },
            {
                "class_id": 6,
                "class_name": "bus",
                "confidence": 0.95,
                "xyxy": [1.0, 2.0, 300.0, 250.0],
            },
        ],
        "person_count": 1,
    }


def test_rfdetr_medium_conforms_and_returns_only_person_boxes(tmp_path: Path) -> None:
    detector = _detector(tmp_path, _valid_report())
    assert isinstance(detector, PersonDetector)
    proposals = detector.detect_people(detector.fixture_image)  # type: ignore[attr-defined]
    assert proposals == (
        BoxProposal((10.0, 20.0, 110.0, 220.0), 0.91, "person", "rf_detr_medium:0"),
    )
    assert detector.identity.provider_key == "rf_detr_medium"
    assert detector.identity.model_family == "rfdetr"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda report: report["checkpoint"].update(sha256="0" * 64), "checkpoint SHA"),
        (lambda report: report.update(rfdetr="1.7.0"), "runtime version"),
        (lambda report: report.update(deterministic=False), "determinism proof"),
        (lambda report: report.update(person_count=2), "person count"),
    ],
)
def test_rfdetr_medium_fails_closed_on_provenance_or_output_drift(
    tmp_path: Path, mutation, message: str
) -> None:
    report = _valid_report()
    detector = _detector(tmp_path, report)
    mutation(report)
    with pytest.raises(RfdetrProviderError, match=message):
        detector.detect_people(detector.fixture_image)  # type: ignore[attr-defined]


def test_rfdetr_medium_normalizes_process_failure(tmp_path: Path) -> None:
    detector = _detector(tmp_path, _valid_report(), returncode=7)
    with pytest.raises(RfdetrProviderError, match="exit 7"):
        detector.detect_people(detector.fixture_image)  # type: ignore[attr-defined]


def test_windows_to_wsl_path_maps_drive_without_shell_text() -> None:
    converted = windows_to_wsl_path(Path("C:/fixture folder/image.jpg"))
    assert converted == "/mnt/c/fixture folder/image.jpg"


def test_frozen_box_comparison_is_deterministic_and_one_to_one() -> None:
    incumbent = (
        BoxProposal((0, 0, 100, 100), 0.9, "person"),
        BoxProposal((200, 0, 300, 100), 0.8, "person"),
    )
    challenger = (
        BoxProposal((5, 5, 105, 105), 0.95, "person"),
        BoxProposal((205, 0, 305, 100), 0.85, "person"),
        BoxProposal((400, 0, 500, 100), 0.7, "person"),
    )
    first = compare_person_boxes(incumbent, challenger)
    second = compare_person_boxes(incumbent, challenger)
    assert first == second
    assert first["authority"] == "shadow_comparison_only"
    assert first["matched_count"] == 2
    assert first["incumbent_recall"] == 1.0
    assert first["unmatched_challenger"] == [2]
