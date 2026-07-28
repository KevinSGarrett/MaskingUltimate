import numpy as np
import pytest

from maskfactory.stages.s05_geometry import (
    GeometryError,
    limb_capsule_prior,
    torso_partition_priors,
)


def test_s05_partitions_front_torso_into_disjoint_named_priors() -> None:
    torso = np.ones((20, 20), dtype=bool)
    priors = torso_partition_priors(
        torso,
        left_shoulder_xy=(4.0, 2.0),
        right_shoulder_xy=(16.0, 2.0),
        left_hip_xy=(5.0, 16.0),
        right_hip_xy=(15.0, 16.0),
        view="front",
    )

    assert {"chest_upper_torso", "abdomen_stomach", "pelvic_region", "left_hip", "right_hip"} <= set(priors)
    assert priors["chest_upper_torso"].dtype == bool
    assert not np.any(priors["left_hip"] & priors["right_hip"])


def test_s05_capsule_requires_intersecting_parsing_evidence() -> None:
    visible = np.ones((20, 20), dtype=bool)
    prior, radius, widths = limb_capsule_prior(
        visible,
        visible,
        (5.0, 5.0),
        (15.0, 15.0),
    )
    assert prior.any()
    assert radius > 0
    assert len(widths) == 5

    with pytest.raises(GeometryError, match="no parsing cross-section"):
        limb_capsule_prior(
            np.zeros((20, 20), dtype=bool),
            visible,
            (5.0, 5.0),
            (15.0, 15.0),
        )
