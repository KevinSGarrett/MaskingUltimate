import json
from pathlib import Path

from maskfactory.ontology_v2_rollback import rehearse_v1_rollback


def test_v1_rollback_rehearsal_restores_exact_bytes_without_mutating_sources(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    registry = root / "models" / "model_registry.json"
    workflow = (
        root / "src" / "maskfactory" / "serve" / "maskfactory_nodes" / "workflows" / "wf.json"
    )
    registry.parent.mkdir(parents=True)
    workflow.parent.mkdir(parents=True)
    registry.write_text('{"models": []}\n', encoding="utf-8")
    workflow.write_text('{"workflow": "v1"}\n', encoding="utf-8")
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "active_ontology": "body_parts_v1",
                "champion_pointers": [
                    {"role": "champion_bodypart", "key": "v1", "sha256": "a" * 64}
                ],
            }
        ),
        encoding="utf-8",
    )
    before = {registry: registry.read_bytes(), workflow: workflow.read_bytes()}
    result = rehearse_v1_rollback(
        root=root,
        snapshot_path=snapshot,
        artifact_paths=(registry, workflow),
    )
    assert result["result"] == "pass"
    assert result["source_unchanged"] is True
    assert result["v2_activation_performed"] is False
    assert result["champion_pointers_restored"][0]["key"] == "v1"
    assert all(record["restored_exactly"] for record in result["artifacts"].values())
    assert {path: path.read_bytes() for path in before} == before
