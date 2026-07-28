from pathlib import Path

import conftest

ROOT = Path(__file__).resolve().parents[1]


def test_governed_asset_partition_is_explicit_and_existing() -> None:
    assert len(conftest.GOVERNED_ASSET_TEST_MODULES) == 19
    assert all(path.startswith("tests/test_") for path in conftest.GOVERNED_ASSET_TEST_MODULES)
    assert all((ROOT / path).is_file() for path in conftest.GOVERNED_ASSET_TEST_MODULES)


def test_critical_governance_and_bridge_tests_remain_hermetic() -> None:
    required_hermetic = {
        "tests/test_currency_review.py",
        "tests/test_tracker_completion_profiles.py",
        "tests/test_governance_policy.py",
        "tests/test_provider_contracts.py",
    }
    assert required_hermetic.isdisjoint(conftest.GOVERNED_ASSET_TEST_MODULES)


def test_ci_collects_asset_lane_and_executes_hermetic_lane() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "pytest --collect-only -m governed_asset" in workflow
    assert 'pytest -m "not governed_asset"' in workflow
