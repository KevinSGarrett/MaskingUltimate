from pathlib import Path

import pytest

from maskfactory.fs_atomic import replace_with_retry


def test_replace_retries_only_bounded_permission_failures() -> None:
    calls = []
    sleeps = []

    def replace(source: Path, destination: Path) -> None:
        calls.append((source, destination))
        if len(calls) < 3:
            raise PermissionError(13, "transient sharing violation")

    replace_with_retry(
        Path("staging"),
        Path("destination"),
        delays=(0.01, 0.02),
        replace=replace,
        sleeper=sleeps.append,
    )
    assert len(calls) == 3
    assert sleeps == [0.01, 0.02]

    with pytest.raises(PermissionError):
        replace_with_retry(
            Path("staging"),
            Path("destination"),
            delays=(),
            replace=lambda *_args: (_ for _ in ()).throw(PermissionError(13, "locked")),
            sleeper=lambda _delay: None,
        )

    with pytest.raises(ValueError, match="semantic failure"):
        replace_with_retry(
            Path("staging"),
            Path("destination"),
            replace=lambda *_args: (_ for _ in ()).throw(ValueError("semantic failure")),
            sleeper=lambda _delay: None,
        )
