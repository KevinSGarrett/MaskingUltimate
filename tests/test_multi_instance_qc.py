import json
from dataclasses import replace

import numpy as np
import pytest

from maskfactory.packager import PackageBlockedError, approve_package
from maskfactory.qa.multi_instance import MultiInstanceQcInputs, run_multi_instance_qc


def _clean() -> MultiInstanceQcInputs:
    a = np.zeros((60, 100), dtype=bool)
    b = np.zeros_like(a)
    a[10:50, 5:35] = True
    b[10:50, 65:95] = True
    return MultiInstanceQcInputs(
        silhouettes={"p0": a, "p1": b},
        atomic_unions={"p0": a, "p1": b},
        expected_promoted_count=2,
    )


def _failures(inputs: MultiInstanceQcInputs) -> set[str]:
    return {result.qc_id for result in run_multi_instance_qc(inputs) if not result.passed}


@pytest.mark.parametrize("qc_id", ("QC-035", "QC-036", "QC-037", "QC-038"))
def test_each_multi_instance_seed_trips_exactly_its_check(qc_id: str) -> None:
    base = _clean()
    if qc_id == "QC-035":
        b = np.asarray(base.silhouettes["p0"]).copy()
        empty = np.zeros_like(b)
        seeded = replace(
            base,
            silhouettes={"p0": base.silhouettes["p0"], "p1": b},
            atomic_unions={"p0": empty, "p1": empty},
        )
    elif qc_id == "QC-036":
        atomics = dict(base.atomic_unions)
        atomics["p0"] = atomics["p0"] | base.silhouettes["p1"]
        seeded = replace(base, atomic_unions=atomics)
    elif qc_id == "QC-037":
        seeded = replace(base, recorded_relationships={"p0": frozenset({"p1"})})
    else:
        seeded = replace(base, expected_promoted_count=3)
    assert _failures(seeded) == {qc_id}


def test_qc035_and_qc036_are_nonoverridable_block_severity() -> None:
    base = _clean()
    b = np.asarray(base.silhouettes["p0"]).copy()
    atomics = dict(base.atomic_unions)
    atomics["p0"] = atomics["p0"] | b
    results = {
        item.qc_id: item
        for item in run_multi_instance_qc(
            replace(
                base, silhouettes={"p0": base.silhouettes["p0"], "p1": b}, atomic_unions=atomics
            )
        )
    }
    assert results["QC-035"].severity == "BLOCK" and not results["QC-035"].passed
    assert results["QC-036"].severity == "BLOCK" and not results["QC-036"].passed


@pytest.mark.parametrize("qc_id", ("QC-035", "QC-036"))
def test_human_approval_cannot_override_multi_instance_block(tmp_path, qc_id: str) -> None:
    (tmp_path / "qa_report.json").write_text(
        json.dumps(
            {
                "checks": [
                    {
                        "id": qc_id,
                        "name": "multi_instance_hard_gate",
                        "result": "fail",
                        "severity": "BLOCK",
                        "message": "seeded failure",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(PackageBlockedError) as caught:
        approve_package(
            tmp_path,
            reviewer="kevin",
            review_minutes=1,
            approved=True,
            dvc_add=lambda path: None,
        )
    assert [result.qc_id for result in caught.value.results] == [qc_id]
