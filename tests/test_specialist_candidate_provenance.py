from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from maskfactory.autonomy.adapters import (
    MaskCandidateInput,
    build_mask_candidate_evidence,
    summarize_candidate_provenance,
)
from maskfactory.autonomy.calibration import load_autonomy_config
from maskfactory.autonomy.tournament import AutonomyTournamentError, run_candidate_tournament
from maskfactory.io.png_strict import write_binary_mask
from maskfactory.providers.contracts import ProviderIdentity


def _identity(provider_key: str, model_family: str) -> ProviderIdentity:
    return ProviderIdentity(
        provider_key,
        "specialist_candidate",
        model_family,
        f"{provider_key}-source",
        f"{provider_key}-runtime",
    )


def _mask(path: Path, offset: int) -> Path:
    array = np.zeros((16, 16), dtype=np.uint8)
    array[2 + offset : 12 + offset, 3:13] = 255
    return write_binary_mask(path, array)


def test_correlated_specialists_remain_candidates_but_count_one_family(tmp_path: Path) -> None:
    dynamic = _identity("birefnet_dynamic", "birefnet")
    hr = _identity("birefnet_hr", "birefnet")
    rfdetr = _identity("rf_detr_medium", "rfdetr")
    inputs = (
        MaskCandidateInput(
            "dynamic-mask",
            _mask(tmp_path / "dynamic.png", 0),
            (),
            0.8,
            False,
            0.8,
            provider_identities=(dynamic,),
        ),
        MaskCandidateInput(
            "hr-mask",
            _mask(tmp_path / "hr.png", 1),
            (),
            0.8,
            False,
            0.8,
            provider_identities=(hr,),
        ),
        MaskCandidateInput(
            "rfdetr-route-mask",
            _mask(tmp_path / "rfdetr.png", 2),
            (),
            0.8,
            False,
            0.8,
            provider_identities=(rfdetr,),
        ),
    )
    evidence = build_mask_candidate_evidence(
        inputs,
        protected_neighbor=np.zeros((16, 16), dtype=bool),
        mutually_exclusive=np.zeros((16, 16), dtype=bool),
        ontology_max_components=1,
    )
    assert [candidate.candidate_id for candidate in evidence] == [
        "dynamic-mask",
        "hr-mask",
        "rfdetr-route-mask",
    ]
    assert [candidate.source_provider_keys for candidate in evidence] == [
        ("birefnet_dynamic",),
        ("birefnet_hr",),
        ("rf_detr_medium",),
    ]
    summary = summarize_candidate_provenance(evidence)
    assert summary["candidate_count"] == 3
    assert summary["provider_count"] == 3
    assert summary["independent_source_count"] == 2
    assert summary["independent_model_families"] == ["birefnet", "rfdetr"]
    assert summary["candidate_provider_map"] == {
        "dynamic-mask": ["birefnet_dynamic"],
        "hr-mask": ["birefnet_hr"],
        "rfdetr-route-mask": ["rf_detr_medium"],
    }


def test_composite_candidate_deduplicates_correlated_provider_family(tmp_path: Path) -> None:
    identities = (
        _identity("birefnet_dynamic", "birefnet"),
        _identity("birefnet_hr_matting", "birefnet"),
        _identity("sam2_1_large", "sam2"),
    )
    evidence = build_mask_candidate_evidence(
        (
            MaskCandidateInput(
                "composite",
                _mask(tmp_path / "composite.png", 0),
                (),
                0.8,
                False,
                0.8,
                provider_identities=identities,
            ),
        ),
        protected_neighbor=np.zeros((16, 16), dtype=bool),
        mutually_exclusive=np.zeros((16, 16), dtype=bool),
        ontology_max_components=1,
    )[0]
    assert evidence.independent_sources == 2
    assert evidence.source_provider_keys == (
        "birefnet_dynamic",
        "birefnet_hr_matting",
        "sam2_1_large",
    )
    assert evidence.source_model_families == ("birefnet", "sam2")
    inflated = replace(evidence, independent_sources=3)
    with pytest.raises(AutonomyTournamentError, match="differs from provenance"):
        run_candidate_tournament(
            (inflated,),
            label="person_full_visible",
            context="solo",
            pipeline_fingerprint="specialist-provenance-fixture",
            config=load_autonomy_config(Path("configs/autonomous_masks.yaml")),
        )


def test_specialist_provenance_rejects_family_claim_drift(tmp_path: Path) -> None:
    candidate = MaskCandidateInput(
        "drifted",
        _mask(tmp_path / "drifted.png", 0),
        ("birefnet", "fake_independent_family"),
        0.8,
        False,
        0.8,
        provider_identities=(_identity("birefnet_hr", "birefnet"),),
    )
    with pytest.raises(ValueError, match="differ from provider model families"):
        build_mask_candidate_evidence(
            (candidate,),
            protected_neighbor=np.zeros((16, 16), dtype=bool),
            mutually_exclusive=np.zeros((16, 16), dtype=bool),
            ontology_max_components=1,
        )


def test_specialist_summary_rejects_legacy_missing_provider_provenance(tmp_path: Path) -> None:
    evidence = build_mask_candidate_evidence(
        (
            MaskCandidateInput(
                "legacy",
                _mask(tmp_path / "legacy.png", 0),
                ("sam2", "pose"),
                0.8,
                False,
                0.8,
            ),
        ),
        protected_neighbor=np.zeros((16, 16), dtype=bool),
        mutually_exclusive=np.zeros((16, 16), dtype=bool),
        ontology_max_components=1,
    )
    with pytest.raises(ValueError, match="missing provider provenance"):
        summarize_candidate_provenance(evidence)
