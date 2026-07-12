import hashlib
import json
from pathlib import Path


def test_ontology_v2_no_go_matches_live_failure_evidence() -> None:
    report = json.loads(Path("qa/reports/ontology_v2_evidence_review_2026-07-12.json").read_text())
    queue = Path(report["failure_queue_path"])
    assert report["failure_queue_present"] == queue.is_file() is True
    assert report["failure_queue_records"] == len(queue.read_text().splitlines()) == 27
    assert report["failure_queue_sha256"] == hashlib.sha256(queue.read_bytes()).hexdigest()
    assert report["required_distinct_failures"] == 10
    assert report["changes_authorized"] == []
    assert all(
        candidate == {"distinct_qualifying_failures": 0, "decision": "no_go"}
        for candidate in report["candidates"].values()
    )
    changelog = Path("Plan/CHANGELOG_ONTOLOGY.md").read_text(encoding="utf-8")
    assert "body_parts_v2 evaluation: NO-GO" in changelog


def test_horizon_memos_preserve_actual_gates_and_architecture() -> None:
    video = Path("Plan/HORIZON_VIDEO_GO_NO_GO.md").read_text(encoding="utf-8")
    multi = Path("Plan/HORIZON_MULTI_PERSON_GO_NO_GO.md").read_text(encoding="utf-8")
    for requirement in (
        "temporal package",
        "identity switch",
        "keyframes per minute",
        "operator minutes per approved video minute",
        "D1–D11",
    ):
        assert requirement in video
    assert "Architecture decision: **GO" in multi
    assert "Production promotion decision: **NO-GO until D11/G9" in multi
    assert "instances/pN" in multi and "QC-035/036" in multi
