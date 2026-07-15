from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from maskfactory.autonomy.multi_person_evidence import (
    EVIDENCE_AUTHORITY,
    MULTI_PERSON_FUNCTIONAL_FAMILIES,
    MultiPersonCandidateRecord,
    MultiPersonEvidenceError,
    MultiPersonTournamentTarget,
    ProviderContribution,
    load_multi_person_tournament_candidates,
    verify_multi_person_tournament_evidence,
    write_multi_person_tournament_evidence,
)
from maskfactory.autonomy.tournament import CandidateEvidence
from maskfactory.io.hashing import sha256_file
from maskfactory.io.png_strict import write_binary_mask
from maskfactory.providers.contracts import ProviderIdentity
from maskfactory.providers.provider_matrix import canonical_sha256
from maskfactory.validation import validate_document

PIPELINE_FINGERPRINT = "f" * 64
PROVIDERS = {
    "deterministic_repair": ("deterministic_repair", "repair", "deterministic"),
    "fusion": ("s09_fusion", "fusion", "fusion"),
    "geometry": ("sam3d_body", "geometry_provider", "sam3d_body"),
    "pose": ("rtmw_x", "pose_provider", "rtmw"),
    "rf_detr_detection": ("rf_detr", "person_detector", "rfdetr"),
    "sam21_refinement": ("sam2_1", "interactive_segmenter", "sam2"),
    "sam31_exhaustive_discovery": ("sam3_1", "concept_detector", "sam3"),
    "sam31_refinement": ("sam3_1", "interactive_segmenter", "sam3"),
    "silhouette": ("birefnet_dynamic", "silhouette_provider", "birefnet"),
    "specialist": ("specialist_ensemble", "specialist", "specialist"),
}


def _source(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "source.png"
    Image.fromarray(np.zeros((20, 24, 3), dtype=np.uint8), "RGB").save(path)
    return path


def _provider(family: str) -> ProviderIdentity:
    key, role, model_family = PROVIDERS[family]
    return ProviderIdentity(
        key, role, model_family, "a" * 40, family.encode().hex()[:64].ljust(64, "0")
    )


def _candidate(
    root: Path,
    candidate_id: str,
    index: int,
    families: tuple[str, ...],
    *,
    generator: str,
    round_number: int = 0,
    parent: str | None = None,
) -> MultiPersonCandidateRecord:
    mask = np.zeros((20, 24), dtype=bool)
    mask[2 + index : 6 + index, 3 + index : 9 + index] = True
    path = write_binary_mask(root / "masks" / f"{candidate_id}.png", mask, source_size=(24, 20))
    contributions = tuple(ProviderContribution(family, _provider(family)) for family in families)
    provider_keys = tuple(sorted({item.provider.provider_key for item in contributions}))
    model_families = tuple(sorted({item.provider.model_family for item in contributions}))
    evidence = CandidateEvidence(
        candidate_id=candidate_id,
        mask_path=str(path),
        mask_sha256=sha256_file(path),
        independent_sources=len(model_families),
        consensus_iou=0.95,
        boundary_agreement=0.94,
        pose_consistency=0.93,
        critic_pass_weight=0.96,
        critic_disagreement=False,
        protected_overlap=0.0,
        exclusive_overlap=0.0,
        component_count=1,
        ontology_max_components=2,
        format_valid=True,
        block_qc_ids=(),
        source_provider_keys=provider_keys,
        source_model_families=model_families,
    )
    return MultiPersonCandidateRecord(
        generator,
        round_number,
        parent,
        contributions,
        evidence,
    )


def _target(root: Path, person: str, instance: str, offset: int) -> MultiPersonTournamentTarget:
    prefix = f"{person}-{instance}"
    first = _candidate(
        root,
        f"{prefix}-discovery",
        offset,
        ("sam31_exhaustive_discovery", "rf_detr_detection", "pose", "geometry"),
        generator="sam31_exhaustive_discovery",
    )
    second = _candidate(
        root,
        f"{prefix}-fusion",
        offset + 1,
        ("sam21_refinement", "silhouette", "fusion", "specialist"),
        generator="fusion",
    )
    third = _candidate(
        root,
        f"{prefix}-repair",
        offset + 2,
        ("deterministic_repair", "sam31_refinement"),
        generator="deterministic_repair",
        round_number=1,
        parent=second.evidence.candidate_id,
    )
    return MultiPersonTournamentTarget(
        person,
        instance,
        "hair",
        {family: None for family in MULTI_PERSON_FUNCTIONAL_FAMILIES},
        (first, second, third),
    )


def _build(tmp_path: Path) -> tuple[Path, Path, Path, dict]:
    root = tmp_path / "artifacts"
    source = _source(tmp_path)
    manifest = write_multi_person_tournament_evidence(
        image_id="img_fixture_duo",
        source_image_path=source,
        instance_context="duo",
        pipeline_fingerprint=PIPELINE_FINGERPRINT,
        targets=(
            _target(root, "person-0", "instance-0", 0),
            _target(root, "person-1", "instance-1", 5),
        ),
        artifact_root=root,
        output_path=tmp_path / "multi_person_evidence.json",
    )
    return manifest, root, source, json.loads(manifest.read_text(encoding="utf-8"))


def _reseal(path: Path, document: dict) -> None:
    document["sha256"] = canonical_sha256(
        {key: value for key, value in document.items() if key != "sha256"}
    )
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")


def test_duo_evidence_preserves_targets_provider_identity_and_independent_families(
    tmp_path: Path,
) -> None:
    manifest, root, source, document = _build(tmp_path)
    summary = verify_multi_person_tournament_evidence(
        manifest,
        artifact_root=root,
        expected_pipeline_fingerprint=PIPELINE_FINGERPRINT,
        source_image_path=source,
    )
    assert not validate_document(document, "multi_person_tournament_evidence")
    assert summary == {
        "image_id": "img_fixture_duo",
        "instance_context": "duo",
        "target_count": 2,
        "candidate_count": 6,
        "sha256": document["sha256"],
        "authority": EVIDENCE_AUTHORITY,
    }
    loaded = load_multi_person_tournament_candidates(
        manifest,
        artifact_root=root,
        expected_pipeline_fingerprint=PIPELINE_FINGERPRINT,
        source_image_path=source,
    )
    assert set(loaded) == {
        ("person-0", "instance-0", "hair"),
        ("person-1", "instance-1", "hair"),
    }
    assert all(Path(row.mask_path).is_absolute() for rows in loaded.values() for row in rows)
    repair = loaded[("person-0", "instance-0", "hair")][2]
    assert repair.independent_sources == 2
    assert repair.source_model_families == ("deterministic", "sam3")


def test_explicitly_unavailable_family_is_not_silently_required(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    source = _source(tmp_path)
    targets = []
    for person, instance, offset in (("person-0", "instance-0", 0), ("person-1", "instance-1", 5)):
        target = _target(root, person, instance, offset)
        availability = dict(target.family_availability)
        availability["geometry"] = "governed provider is not installed"
        first = target.candidates[0]
        contributions = tuple(
            item for item in first.contributions if item.functional_family != "geometry"
        )
        provider_keys = tuple(sorted({item.provider.provider_key for item in contributions}))
        model_families = tuple(sorted({item.provider.model_family for item in contributions}))
        evidence = copy.copy(first.evidence)
        object.__setattr__(evidence, "source_provider_keys", provider_keys)
        object.__setattr__(evidence, "source_model_families", model_families)
        object.__setattr__(evidence, "independent_sources", len(model_families))
        first = MultiPersonCandidateRecord(
            first.generator_family,
            first.round_number,
            first.parent_candidate_id,
            contributions,
            evidence,
        )
        targets.append(
            MultiPersonTournamentTarget(
                target.person_id,
                target.instance_id,
                target.label,
                availability,
                (first, *target.candidates[1:]),
            )
        )
    manifest = write_multi_person_tournament_evidence(
        image_id="img_fixture_duo",
        source_image_path=source,
        instance_context="duo",
        pipeline_fingerprint=PIPELINE_FINGERPRINT,
        targets=targets,
        artifact_root=root,
        output_path=tmp_path / "unavailable.json",
    )
    assert (
        verify_multi_person_tournament_evidence(
            manifest,
            artifact_root=root,
            expected_pipeline_fingerprint=PIPELINE_FINGERPRINT,
        )["candidate_count"]
        == 6
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda doc: doc["targets"][1].update(
            person_id=doc["targets"][0]["person_id"],
            instance_id=doc["targets"][0]["instance_id"],
        ),
        lambda doc: doc["targets"][1]["candidates"][0]["evidence"].update(
            candidate_id=doc["targets"][0]["candidates"][0]["evidence"]["candidate_id"]
        ),
        lambda doc: doc["targets"][0]["candidates"][0]["contributions"][0]["provider"].update(
            model_family="rebound-family"
        ),
        lambda doc: doc["targets"][0]["candidates"][0].update(
            generator_family="deterministic_repair"
        ),
        lambda doc: doc["targets"][0]["candidates"][2].update(parent_candidate_id="missing"),
        lambda doc: doc.update(autonomy_config_sha256="0" * 64),
        lambda doc: doc["targets"][0]["candidates"][0]["evidence"].update(
            mask_path="../outside.png"
        ),
    ],
)
def test_identity_reuse_provenance_rebinding_round_policy_and_path_escape_fail(
    tmp_path: Path, mutation
) -> None:
    manifest, root, _, document = _build(tmp_path)
    mutation(document)
    _reseal(manifest, document)
    with pytest.raises(MultiPersonEvidenceError):
        verify_multi_person_tournament_evidence(
            manifest,
            artifact_root=root,
            expected_pipeline_fingerprint=PIPELINE_FINGERPRINT,
        )


def test_artifact_source_pipeline_and_manifest_drift_fail(tmp_path: Path) -> None:
    manifest, root, source, document = _build(tmp_path)
    path = root / document["targets"][0]["candidates"][0]["evidence"]["mask_path"]
    Image.fromarray(np.full((20, 24), 128, dtype=np.uint8), "L").save(path)
    with pytest.raises(MultiPersonEvidenceError, match="strict PNG"):
        verify_multi_person_tournament_evidence(
            manifest,
            artifact_root=root,
            expected_pipeline_fingerprint=PIPELINE_FINGERPRINT,
        )

    manifest, root, source, document = _build(tmp_path / "source-drift")
    Image.fromarray(np.ones((20, 24, 3), dtype=np.uint8), "RGB").save(source)
    with pytest.raises(MultiPersonEvidenceError, match="source image identity"):
        verify_multi_person_tournament_evidence(
            manifest,
            artifact_root=root,
            expected_pipeline_fingerprint=PIPELINE_FINGERPRINT,
            source_image_path=source,
        )

    manifest, root, _, _ = _build(tmp_path / "pipeline-drift")
    with pytest.raises(MultiPersonEvidenceError, match="policy identity"):
        verify_multi_person_tournament_evidence(
            manifest,
            artifact_root=root,
            expected_pipeline_fingerprint="e" * 64,
        )

    manifest, root, _, document = _build(tmp_path / "seal-drift")
    document["image_id"] = "rebound"
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(MultiPersonEvidenceError, match="hash mismatch"):
        verify_multi_person_tournament_evidence(
            manifest,
            artifact_root=root,
            expected_pipeline_fingerprint=PIPELINE_FINGERPRINT,
        )


def test_writer_rejects_missing_family_inventory_outside_artifact_and_solo_context(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    source = _source(tmp_path)
    target = _target(root, "person-0", "instance-0", 0)
    missing = dict(target.family_availability)
    missing.pop("geometry")
    target = MultiPersonTournamentTarget(
        target.person_id,
        target.instance_id,
        target.label,
        missing,
        target.candidates,
    )
    with pytest.raises(MultiPersonEvidenceError, match="every governed family"):
        write_multi_person_tournament_evidence(
            image_id="img",
            source_image_path=source,
            instance_context="duo",
            pipeline_fingerprint=PIPELINE_FINGERPRINT,
            targets=(target,),
            artifact_root=root,
            output_path=tmp_path / "missing.json",
        )

    targets = (
        _target(root, "person-0", "instance-0", 0),
        _target(root, "person-1", "instance-1", 5),
    )
    with pytest.raises(MultiPersonEvidenceError, match="duo or small_group"):
        write_multi_person_tournament_evidence(
            image_id="img",
            source_image_path=source,
            instance_context="solo",
            pipeline_fingerprint=PIPELINE_FINGERPRINT,
            targets=targets,
            artifact_root=root,
            output_path=tmp_path / "solo.json",
        )

    outside = _target(tmp_path / "outside", "person-2", "instance-2", 9)
    with pytest.raises(MultiPersonEvidenceError, match="escapes"):
        write_multi_person_tournament_evidence(
            image_id="img",
            source_image_path=source,
            instance_context="duo",
            pipeline_fingerprint=PIPELINE_FINGERPRINT,
            targets=(targets[0], outside),
            artifact_root=root,
            output_path=tmp_path / "outside.json",
        )
