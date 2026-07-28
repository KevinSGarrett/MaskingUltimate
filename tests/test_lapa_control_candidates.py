from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest
import yaml
from PIL import Image

import maskfactory.vlm.lapa_control_candidates as lapa
from maskfactory.external_supervision_evidence import seal_payload
from maskfactory.external_supervision_qualification import QualificationEvidence
from maskfactory.vlm.canonical_polygon_source_candidates import sha256_file
from maskfactory.vlm.critic_catalog import canonical_sha256


def _json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path, Path, Path]:
    root = tmp_path / "LaPa"
    files: list[dict] = []
    records: list[dict] = []
    for split in ("train", "test"):
        for number in range(10):
            stem = f"{split}_{number:02d}"
            image = root / split / "images" / f"{stem}.jpg"
            label = root / split / "labels" / f"{stem}.png"
            image.parent.mkdir(parents=True, exist_ok=True)
            label.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(np.full((18, 20, 3), number + 20, dtype=np.uint8)).save(image)
            indexed = np.zeros((18, 20), dtype=np.uint8)
            indexed[3:12, 4:14] = 1
            indexed[2:5, 3:15] = 10
            Image.fromarray(indexed).save(label)
            for path in (image, label):
                files.append({"path": path.relative_to(root).as_posix(), "size": path.stat().st_size, "sha256": sha256_file(path)})
            records.append({"source": "lapa", "relative_path": image.relative_to(root).as_posix(), "source_sha256": sha256_file(image), "split_group_id": f"group-{split}-{number}", "upstream_split": split})
    manifest = {"schema_version": "1.0.0", "artifact_type": "external_supervision_source_hash_manifest", "source": "lapa", "gate": "source_hash_manifested", "status": "PASS", "path_encoding": "utf-8-posix-relative", "hash_algorithm": "sha256", "file_count": len(files), "total_bytes": sum(row["size"] for row in files), "files": sorted(files, key=lambda row: row["path"])}
    manifest["seal_sha256"] = seal_payload(manifest)
    manifest_path = _json(tmp_path / "manifest.json", manifest)
    dedup_path = _json(tmp_path / "dedup.json", {"status": "PASS", "records": records})
    provenance = {"policy": {"source_masks_are_gold": False}, "sources": {"lapa": {"training_admission": {"allowed_label_scope": ["head_face", "hair"]}}}}
    mappings = {0: {"source_label": "background", "action": "direct", "part": ["background"]}, 10: {"source_label": "hair", "action": "direct", "part": ["hair"]}}
    for value in range(1, 10):
        mappings[value] = {"source_label": f"face_{value}", "action": "merge", "part": ["head_face"]}
    provenance_path, remap_path = tmp_path / "provenance.yaml", tmp_path / "remap.yaml"
    provenance_path.write_text(yaml.safe_dump(provenance), encoding="utf-8")
    remap_path.write_text(yaml.safe_dump({"source": "lapa", "mappings": mappings}), encoding="utf-8")
    inventory_path = _json(tmp_path / "inventory.json", {"sources": [{"source": "lapa"}]})
    bundle_path = _json(tmp_path / "bundle.json", {"fixture": True})
    return root, provenance_path, inventory_path, remap_path, bundle_path, manifest_path, dedup_path


def _qualified(admitted: bool = True) -> QualificationEvidence:
    return QualificationEvidence(source="lapa", legally_eligible=True, technically_qualified=admitted, admitted=admitted, unmet_gates=() if admitted else ("source_hash_manifested",), evidence_tokens=(), evidence_bundle_sha256="a" * 64 if admitted else None, reason="fixture")


def _build(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[dict, Path]:
    root, provenance, inventory, remap, bundle, manifest, dedup = _inputs(tmp_path)
    monkeypatch.setattr(lapa, "verify_external_qualification_evidence", lambda *args, **kwargs: _qualified())
    return lapa.build_lapa_control_candidates(source_root=root, project_root=tmp_path, provenance_path=provenance, inventory_path=inventory, remap_path=remap, qualification_evidence_path=bundle, source_hash_manifest_path=manifest, split_dedup_path=dedup, per_partition=4), root


def test_selects_split_disjoint_exact_head_face_candidates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    document, _ = _build(monkeypatch, tmp_path)
    lapa.verify_lapa_control_candidates(document)
    assert document["selected_by_label"] == {"head_face": 8}
    assert document["selected_by_partition"] == {"qualification_test": 4, "qualification_train": 4}
    assert {tuple(row["raw_label_values"]) for row in document["selected"]} == {tuple(range(1, 10))}
    assert all(row["critic_control_eligible"] is False for row in document["selected"])


def test_cross_split_identity_group_is_excluded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root, provenance, inventory, remap, bundle, manifest, dedup = _inputs(tmp_path)
    document = json.loads(dedup.read_text(encoding="utf-8"))
    train = next(row for row in document["records"] if row["relative_path"] == "train/images/train_00.jpg")
    test = next(row for row in document["records"] if row["relative_path"] == "test/images/test_00.jpg")
    test["split_group_id"] = train["split_group_id"]
    dedup.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    monkeypatch.setattr(lapa, "verify_external_qualification_evidence", lambda *args, **kwargs: _qualified())
    result = lapa.build_lapa_control_candidates(source_root=root, project_root=tmp_path, provenance_path=provenance, inventory_path=inventory, remap_path=remap, qualification_evidence_path=bundle, source_hash_manifest_path=manifest, split_dedup_path=dedup, per_partition=4)
    assert train["split_group_id"] not in {row["split_group_id"] for row in result["selected"]}


def test_external_qualification_failure_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root, provenance, inventory, remap, bundle, manifest, dedup = _inputs(tmp_path)
    monkeypatch.setattr(lapa, "verify_external_qualification_evidence", lambda *args, **kwargs: _qualified(False))
    with pytest.raises(lapa.LaPaControlCandidateError, match="not admitted"):
        lapa.build_lapa_control_candidates(source_root=root, project_root=tmp_path, provenance_path=provenance, inventory_path=inventory, remap_path=remap, qualification_evidence_path=bundle, source_hash_manifest_path=manifest, split_dedup_path=dedup)


def test_materializes_and_verifies_exact_panels(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    candidates, root = _build(monkeypatch, tmp_path)
    output = tmp_path / "panels"
    report = lapa.materialize_lapa_control_panels(source_root=root, candidate_document=candidates, output_root=output)
    lapa.verify_lapa_control_panel_report(report, output)
    assert report["record_count"] == 8
    assert report["panel_count"] == 48
    assert report["critic_control_authority_granted"] is False


def test_authority_upgrade_fails_panel_verification(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    candidates, root = _build(monkeypatch, tmp_path)
    output = tmp_path / "panels"
    report = lapa.materialize_lapa_control_panels(source_root=root, candidate_document=candidates, output_root=output)
    changed = copy.deepcopy(report)
    changed["critic_control_authority_granted"] = True
    changed["self_sha256"] = canonical_sha256({key: value for key, value in changed.items() if key != "self_sha256"})
    with pytest.raises(lapa.LaPaControlCandidateError, match="authority"):
        lapa.verify_lapa_control_panel_report(changed, output)
