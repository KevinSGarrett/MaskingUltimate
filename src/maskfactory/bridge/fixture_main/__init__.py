"""Governed synthetic Main consumer runtime for MaskFactory producer verify.

This package materializes hash-bound, fixture-key-signed Main-consumer artifacts
so producer verify clauses can close under closed-fixture / pinned cross-project
evidence. It never claims KevinSGarrett/Comfy_UI_Main production commits and
never sets ``main_adoption_complete``.
"""

from .binding import (
    FixtureMainBindingError,
    load_fixture_main_binding,
    observation_from_fixture_main_binding,
)
from .runtime import (
    AUTHORITY_KIND,
    CONSUMER_KIND,
    SYNTHETIC_MAIN_GIT_COMMIT,
    FixtureMainError,
    FixtureMainRuntime,
    materialize_fixture_main,
    run_fixture_main_producer_verify,
)

__all__ = [
    "AUTHORITY_KIND",
    "CONSUMER_KIND",
    "SYNTHETIC_MAIN_GIT_COMMIT",
    "FixtureMainBindingError",
    "FixtureMainError",
    "FixtureMainRuntime",
    "load_fixture_main_binding",
    "materialize_fixture_main",
    "observation_from_fixture_main_binding",
    "run_fixture_main_producer_verify",
]
