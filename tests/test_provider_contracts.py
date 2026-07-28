import copy
from pathlib import Path

import numpy as np
import pytest
import yaml

from maskfactory.providers.adapters import (
    ConceptDetectorAdapter,
    GeometryProviderAdapter,
    InteractiveSegmenterAdapter,
    PersonDetectorAdapter,
    PoseProviderAdapter,
    SilhouetteProviderAdapter,
    VlmReviewerAdapter,
    provider_contract_metadata,
    provider_identity_from_manifest,
)
from maskfactory.providers.contracts import (
    BoxProposal,
    ConceptDetector,
    GeometryProvider,
    InteractiveSegmenter,
    MaskProposal,
    PersonDetector,
    PoseProvider,
    ProviderIdentity,
    SilhouetteProvider,
    VlmReviewer,
    independent_model_families,
    require_independent_model_families,
)
from maskfactory.providers.selection import (
    ProviderSelectionError,
    validate_provider_selection,
)
from maskfactory.providers.shadow import run_shadow_tournament, validate_shadow_manifest

ROOT = Path(__file__).resolve().parents[1]


def test_independence_counts_model_families_not_correlated_variants() -> None:
    identities = (
        ProviderIdentity("sam3_1_text", "concept_detector", "sam3", "a", "r1"),
        ProviderIdentity("sam3_1_point", "interactive_segmenter", "sam3", "a", "r1"),
        ProviderIdentity("sam2_1", "interactive_segmenter", "sam2", "b", "r2"),
        ProviderIdentity("sapiens_0_6b", "parsing", "sapiens", "c", "r3"),
    )
    assert independent_model_families(identities) == {"sam3", "sam2", "sapiens"}
    require_independent_model_families(identities, minimum=3)


def test_pipeline_role_registry_keeps_incumbents_challengers_and_rollback_explicit() -> None:
    config = yaml.safe_load(Path("configs/pipeline.yaml").read_text(encoding="utf-8"))
    roles = config["provider_roles"]
    assert roles["interactive_segmenter"] == {
        "active": "sam2_1_large",
        "active_scope": "optional_local_editor_and_legacy_compatibility_only",
        "production_primary_forbidden": True,
        "challengers": ["sam3_1", "sam3_litetext_s0"],
        "shadow_only_experiments": ["sam3_litetext_s0"],
        "oom_fallback": "sam2_1_base_plus",
        "rollback": "sam2_1_large",
    }
    assert roles["person_detector"]["challengers"][0] == "rf_detr_medium"
    assert roles["geometry_provider"]["challengers"] == ["sam3d_body"]
    assert roles["challenger_policy"] == "shadow_only_until_benchmark_certificate"
    assert roles["concept_detector"]["active"] is None
    assert roles["concept_detector"]["offline_fallback"] == "groundingdino_local"
    assert roles["vlm_reviewer"]["active"] is None
    assert roles["custom_segmenter"] == {
        "active": None,
        "challengers": ["segformer_b2", "mask2former_swin_t", "eomt_dinov3"],
        "rollback": None,
    }


def _validate_selection(config: dict) -> dict:
    return validate_provider_selection(
        config,
        external_registry_path=ROOT / "configs/external_sources.yaml",
        model_registry_path=ROOT / "models/model_registry.json",
    )


def test_provider_selection_preserves_local_nonbillable_groundingdino_fallback() -> None:
    config = yaml.safe_load((ROOT / "configs/pipeline.yaml").read_text(encoding="utf-8"))
    result = _validate_selection(config)
    assert result["concept_offline_fallback"] == "groundingdino_local"
    assert result["fallbacks"]["concept_detector"] == {"offline_fallback": "groundingdino_local"}
    assert "concept_detector" not in result["active"]

    hosted_only = copy.deepcopy(config)
    hosted_only["provider_catalog"]["groundingdino_local"]["execution"] = "hosted"
    hosted_only["provider_catalog"]["groundingdino_local"]["billing"] = "paid"
    with pytest.raises(ProviderSelectionError, match="hosted-only is forbidden"):
        _validate_selection(hosted_only)


def test_interactive_selection_resolves_incumbent_oom_fallback_and_rollback() -> None:
    config = yaml.safe_load((ROOT / "configs/pipeline.yaml").read_text(encoding="utf-8"))
    result = _validate_selection(config)

    assert result["active"]["interactive_segmenter"] == "sam2_1_large"
    assert result["fallbacks"]["interactive_segmenter"] == {"oom_fallback": "sam2_1_base_plus"}
    assert result["rollback"]["interactive_segmenter"] == "sam2_1_large"
    assert result["provider_states"]["sam2_1_large"] == "promoted"
    assert result["provider_states"]["sam2_1_base_plus"] == "installed"


@pytest.mark.parametrize("selection_field", ["rollback", "oom_fallback"])
def test_interactive_selection_rejects_planned_sam31_as_recovery_path(
    selection_field: str,
) -> None:
    config = yaml.safe_load((ROOT / "configs/pipeline.yaml").read_text(encoding="utf-8"))
    config["provider_roles"]["interactive_segmenter"][selection_field] = "sam3_1"

    with pytest.raises(ProviderSelectionError, match="requires an installed"):
        _validate_selection(config)


@pytest.mark.parametrize("lifecycle_state", ["planned", "installed"])
def test_provider_selection_rejects_unpromoted_active_provider(
    tmp_path: Path, lifecycle_state: str
) -> None:
    config = yaml.safe_load((ROOT / "configs/pipeline.yaml").read_text(encoding="utf-8"))
    registry = yaml.safe_load((ROOT / "configs/external_sources.yaml").read_text(encoding="utf-8"))
    registry["providers"]["rfdetr"]["lifecycle_state"] = lifecycle_state
    registry_path = tmp_path / "external_sources.yaml"
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    config["provider_roles"]["person_detector"]["active"] = "rf_detr_medium"

    with pytest.raises(ProviderSelectionError, match="active roles require promoted"):
        validate_provider_selection(
            config,
            external_registry_path=registry_path,
            model_registry_path=ROOT / "models/model_registry.json",
        )


def _shadow_only_experiment_fixture(tmp_path: Path) -> tuple[dict, Path]:
    config = yaml.safe_load((ROOT / "configs/pipeline.yaml").read_text(encoding="utf-8"))
    registry = yaml.safe_load((ROOT / "configs/external_sources.yaml").read_text(encoding="utf-8"))
    registry["providers"]["sam3_litetext_s0"]["lifecycle_state"] = "installed"
    registry_path = tmp_path / "external_sources.yaml"
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    return config, registry_path


def test_shadow_only_experiment_is_distinct_and_evaluation_only(tmp_path: Path) -> None:
    config, registry_path = _shadow_only_experiment_fixture(tmp_path)
    result = validate_provider_selection(
        config,
        external_registry_path=registry_path,
        model_registry_path=ROOT / "models/model_registry.json",
    )
    assert result["shadow"]["interactive_segmenter"] == (
        "sam3_1",
        "sam3_litetext_s0",
    )
    assert result["provider_states"]["sam3_litetext_s0"] == "installed"


@pytest.mark.parametrize(
    ("role", "selection_field"),
    [
        ("concept_detector", "active"),
        ("concept_detector", "rollback"),
        ("interactive_segmenter", "active"),
        ("interactive_segmenter", "rollback"),
        ("interactive_segmenter", "oom_fallback"),
    ],
)
def test_shadow_only_experiment_cannot_substitute_for_official_provider(
    tmp_path: Path, role: str, selection_field: str
) -> None:
    config, registry_path = _shadow_only_experiment_fixture(tmp_path)
    config["provider_roles"][role][selection_field] = "sam3_litetext_s0"

    with pytest.raises(ProviderSelectionError, match="shadow-only"):
        validate_provider_selection(
            config,
            external_registry_path=registry_path,
            model_registry_path=ROOT / "models/model_registry.json",
        )


@pytest.mark.parametrize("role", ["concept_detector", "interactive_segmenter"])
def test_shadow_only_experiment_requires_official_provider_first(tmp_path: Path, role: str) -> None:
    config, registry_path = _shadow_only_experiment_fixture(tmp_path)
    config["provider_roles"][role]["challengers"] = [
        "sam3_litetext_s0",
        "sam3_1",
    ]

    with pytest.raises(ProviderSelectionError, match="official provider 'sam3_1' before"):
        validate_provider_selection(
            config,
            external_registry_path=registry_path,
            model_registry_path=ROOT / "models/model_registry.json",
        )


def test_shadow_only_experiment_requires_distinct_registry_identity(tmp_path: Path) -> None:
    config, registry_path = _shadow_only_experiment_fixture(tmp_path)
    config["provider_catalog"]["sam3_litetext_s0"]["key"] = "sam3_1"

    with pytest.raises(ProviderSelectionError, match="distinct registry identity"):
        validate_provider_selection(
            config,
            external_registry_path=registry_path,
            model_registry_path=ROOT / "models/model_registry.json",
        )


def test_official_provider_can_be_active_while_litetext_remains_shadow_only(
    tmp_path: Path,
) -> None:
    config, registry_path = _shadow_only_experiment_fixture(tmp_path)
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registry["providers"]["sam3_1"]["lifecycle_state"] = "promoted"
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    role = config["provider_roles"]["interactive_segmenter"]
    role["active"] = "sam3_1"
    role["challengers"] = ["sam2_1_large", "sam3_litetext_s0"]
    role["rollback"] = "sam2_1_large"

    result = validate_provider_selection(
        config,
        external_registry_path=registry_path,
        model_registry_path=ROOT / "models/model_registry.json",
    )
    assert result["active"]["interactive_segmenter"] == "sam3_1"
    assert result["rollback"]["interactive_segmenter"] == "sam2_1_large"
    assert result["shadow"]["interactive_segmenter"] == (
        "sam2_1_large",
        "sam3_litetext_s0",
    )


def test_litetext_requires_official_provider_active_or_challenging(tmp_path: Path) -> None:
    config, registry_path = _shadow_only_experiment_fixture(tmp_path)
    config["provider_roles"]["interactive_segmenter"]["challengers"] = ["sam3_litetext_s0"]

    with pytest.raises(ProviderSelectionError, match="as active or as a challenger"):
        validate_provider_selection(
            config,
            external_registry_path=registry_path,
            model_registry_path=ROOT / "models/model_registry.json",
        )


def test_shadow_tournament_runs_installed_challenger_and_records_planned_skips() -> None:
    config = yaml.safe_load((ROOT / "configs/pipeline.yaml").read_text(encoding="utf-8"))
    calls: list[tuple[str, str]] = []

    def execute(provider_key: str, sample_id: str) -> dict:
        calls.append((provider_key, sample_id))
        return {"output_sha256": f"fixture-{provider_key}-{sample_id}"}

    manifest = run_shadow_tournament(
        config,
        role="vlm_reviewer",
        sample_ids=("human-anchor-1", "human-anchor-2"),
        executor=execute,
        external_registry_path=ROOT / "configs/external_sources.yaml",
        model_registry_path=ROOT / "models/model_registry.json",
    )
    assert calls == [
        ("qwen2_5_vl_7b", "human-anchor-1"),
        ("qwen2_5_vl_7b", "human-anchor-2"),
        ("qwen3_vl_4b", "human-anchor-1"),
        ("qwen3_vl_4b", "human-anchor-2"),
        ("qwen3_vl_8b_quantized", "human-anchor-1"),
        ("qwen3_vl_8b_quantized", "human-anchor-2"),
    ]
    assert manifest["active_provider"] is None
    assert manifest["skipped"] == {}
    assert manifest["authority"] == "evaluation_only_no_runtime_or_promotion_authority"
    validate_shadow_manifest(manifest)

    tampered = copy.deepcopy(manifest)
    tampered["authority"] = "active"
    with pytest.raises(ProviderSelectionError, match="hash mismatch"):
        validate_shadow_manifest(tampered)


@pytest.mark.parametrize("provider_key", ["sam2_1_large", "fake_sam3_1_challenger"])
def test_incumbent_and_fake_challenger_conform_to_every_versioned_role(
    provider_key: str,
) -> None:
    image_path = Path("fixture.png")
    box = BoxProposal((1.0, 2.0, 9.0, 12.0), 0.9, "person", "p0")
    identity = ProviderIdentity(
        provider_key,
        "fixture_role",
        "sam2" if provider_key.startswith("sam2") else "fake_challenger",
        "commit-fixture",
        "runtime-fixture",
        provenance_aliases=("legacy_sam2_identifier",) if provider_key.startswith("sam2") else (),
    )
    mask = np.zeros((16, 16), dtype=bool)
    mask[2:12, 3:11] = True
    proposal = MaskProposal(mask, 0.85, identity, "prompt-fixture")

    person = PersonDetectorAdapter(identity, lambda _path: (box,))
    concept = ConceptDetectorAdapter(
        identity,
        lambda _path, *, concepts, exemplars: (box, proposal),
    )
    interactive = InteractiveSegmenterAdapter(
        identity,
        lambda image: {"shape": image.shape},
        lambda embedding, *, prompt: (proposal,),
    )
    geometry = GeometryProviderAdapter(
        identity, lambda _path, *, person_box: {"bbox": person_box.bbox_xyxy}
    )
    pose = PoseProviderAdapter(
        identity, lambda _path, *, person_box: {"person_box": person_box.bbox_xyxy}
    )
    silhouette = SilhouetteProviderAdapter(identity, lambda _path, *, person_box: proposal)
    reviewer = VlmReviewerAdapter(
        identity,
        lambda _path, *, masks, evidence: {"verdict": "pass", "evidence": evidence},
    )

    assert isinstance(person, PersonDetector)
    assert isinstance(concept, ConceptDetector)
    assert isinstance(interactive, InteractiveSegmenter)
    assert isinstance(geometry, GeometryProvider)
    assert isinstance(pose, PoseProvider)
    assert isinstance(silhouette, SilhouetteProvider)
    assert isinstance(reviewer, VlmReviewer)
    assert person.detect_people(image_path) == (box,)
    assert concept.discover(image_path, concepts=("person",)) == (box, proposal)
    embedding = interactive.embed(np.zeros((16, 16, 3), dtype=np.uint8))
    assert interactive.refine(embedding, prompt={"positive_points": [(4, 4)]}) == (proposal,)
    assert geometry.infer_geometry(image_path, person_box=box)["bbox"] == box.bbox_xyxy
    assert pose.infer_pose(image_path, person_box=box)["person_box"] == box.bbox_xyxy
    assert silhouette.infer_silhouette(image_path, person_box=box) is proposal
    assert (
        reviewer.review(image_path, masks={}, evidence={"source": "fixture"})["verdict"] == "pass"
    )


def test_provider_contracts_reject_noncanonical_geometry_and_mask_outputs() -> None:
    identity = ProviderIdentity("fake", "interactive_segmenter", "fake", "c", "r")
    with pytest.raises(ValueError, match="positive area"):
        BoxProposal((1, 1, 1, 2), 0.9, "person")
    with pytest.raises(ValueError, match="boolean"):
        MaskProposal(np.zeros((3, 3), dtype=np.uint8), 0.5, identity, "prompt")
    adapter = InteractiveSegmenterAdapter(identity, lambda image: image, lambda *args, **kwargs: ())
    with pytest.raises(TypeError, match="invalid mask proposals"):
        adapter.refine(object(), prompt={})


def test_legacy_sam2_manifest_keeps_original_provenance_and_emits_canonical_metadata() -> None:
    historical = {
        "sam2_model": "sam2.1_hiera_large",
        "winner_mask_sha256": "a" * 64,
        "review_note": "historical evidence must not be renamed",
    }
    original = copy.deepcopy(historical)
    identity = provider_identity_from_manifest(
        historical,
        role="interactive_segmenter",
        source_commit="sam2-commit-fixture",
        runtime_fingerprint="runtime-fixture",
    )
    assert historical == original
    assert identity.provider_key == "sam2_1_large"
    assert identity.provenance_aliases == ("sam2.1_hiera_large",)
    metadata = provider_contract_metadata(identity, historical_manifest=historical)
    assert metadata["provider_key"] == "sam2_1_large"
    assert metadata["provenance_aliases"] == ["sam2.1_hiera_large"]
    assert len(metadata["historical_provenance_sha256"]) == 64

    canonical = {"provider_contract": metadata}
    assert provider_identity_from_manifest(canonical, role="ignored") == identity
