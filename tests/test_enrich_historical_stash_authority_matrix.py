from __future__ import annotations

import importlib.util
from pathlib import Path

TOOL_PATH = (
    Path(__file__).resolve().parents[1] / "tools" / "enrich_historical_stash_authority_matrix.py"
)
SPEC = importlib.util.spec_from_file_location("stash_authority", TOOL_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def row(path: str, disposition: str) -> dict[str, object]:
    return {
        "stash_index": 0,
        "stash_oid": "a" * 40,
        "path": path,
        "source": "untracked_parent",
        "relation": "MAIN_ABSENT",
        "stash_blob_oid": "b" * 40,
        "main_blob_oid": None,
        "meaningful_candidate": True,
        "disposition": disposition,
        "decision_basis": "fixture",
    }


def test_adopted_test_gets_repository_test_and_functional_bindings() -> None:
    item_ids = MODULE.classify_items(
        row(
            "tests/test_visual_defect_abstention.py",
            "ADOPTED_AS_SEMANTIC_PORT_ON_CURRENT_MAIN",
        )
    )
    assert item_ids == [
        "MF-P6-20.01",
        "MF-P6-20.02",
        "MF-P6-20.03",
        "MF-P6-21.02",
    ]


def test_archived_evidence_gets_recovery_attribution_only() -> None:
    fixture = row(
        "qa/historical/report.json",
        "HISTORICAL_EVIDENCE_ARCHIVED",
    )
    assert MODULE.classify_items(fixture) == ["MF-P6-20.01"]
    assert MODULE.canonical_location(fixture)["state"] == ("NOT_CANONICAL_PRODUCT_INPUT")


def test_generated_precommit_cache_is_bound_to_test_baseline() -> None:
    item_ids = MODULE.classify_items(
        row(
            ".pre-commit-home-climb4/cache.db",
            "GENERATED_PRECOMMIT_CACHE",
        )
    )
    assert item_ids == ["MF-P6-20.01", "MF-P6-20.03"]


def test_incomplete_prototype_has_explicit_no_credit_limitation() -> None:
    fixture = row(
        "src/maskfactory/autonomy/certifiable_subset.py",
        "PRESERVED_INCOMPLETE_PROTOTYPE_NOT_ADOPTED",
    )
    text = " ".join(MODULE.limitations(fixture)).lower()
    assert "incomplete" in text
    assert "not executable authority" in text
