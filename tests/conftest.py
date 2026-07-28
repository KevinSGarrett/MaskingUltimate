"""Repository-wide pytest governance hooks.

GitHub runners are intentionally source-only. The modules below exercise
governed model payloads, local evidence, or Windows-only runtimes that are not
committed to Git. They remain mandatory in the asset-complete lane; this marker
only prevents a source-only runner from misreporting missing local bytes as a
product regression.
"""

from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

GOVERNED_ASSET_TEST_MODULES = frozenset(
    {
        "tests/test_civitai_auxiliary_runtime.py",
        "tests/test_civitai_stress_runtime.py",
        "tests/test_cvat_autonomy_publish.py",
        "tests/test_dataset_builder.py",
        "tests/test_daz_control_plane.py",
        "tests/test_daz_dim_manifest.py",
        "tests/test_daz_geometry_pass.py",
        "tests/test_daz_multi_person_relationship.py",
        "tests/test_daz_relationship_pass.py",
        "tests/test_daz_runtime_worker.py",
        "tests/test_eomt_dinov3_contract.py",
        "tests/test_failure_mining_coverage.py",
        "tests/test_live_vitmatte_evidence.py",
        "tests/test_reference_library.py",
        "tests/test_reviewed_s02_benchmark.py",
        "tests/test_rfdetr_provider.py",
        "tests/test_sam31_multiplex.py",
        "tests/test_sam3d_body_geometry_provider.py",
        "tests/test_sam3d_body_runtime_lock.py",
    }
)


def pytest_configure(config: pytest.Config) -> None:
    """Fail collection if the explicit governed-asset registry drifts."""

    missing = [
        relative_path
        for relative_path in sorted(GOVERNED_ASSET_TEST_MODULES)
        if not (REPOSITORY_ROOT / relative_path).is_file()
    ]
    if missing:
        raise pytest.UsageError(f"governed asset test modules are missing: {missing}")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Mark only the audited module registry as requiring governed assets."""

    del config
    governed_asset = pytest.mark.governed_asset
    for item in items:
        try:
            relative_path = item.path.resolve().relative_to(REPOSITORY_ROOT).as_posix()
        except ValueError:
            continue
        if relative_path in GOVERNED_ASSET_TEST_MODULES:
            item.add_marker(governed_asset)
