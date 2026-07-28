"""MF-P0-08.04: ban raw mask writers outside png_strict (pitfall 5 / QC-030 parity).

No source file except ``io/png_strict.py`` may call ``cv2.imwrite(...)`` or a raw
PIL ``.save(...)``. All mask PNG writes must route through png_strict so the gold
format invariants (doc 03 §1) can never be bypassed. A line may opt out only with
an explicit ``# png-strict: allow`` marker (audited exception, e.g. saving a
non-mask artifact).
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "maskfactory"
ALLOW_MARKER = "# png-strict: allow"
# The single sanctioned writer file (relative to SRC).
WHITELIST = {Path("io/png_strict.py")}

_FORBIDDEN = re.compile(r"cv2\.imwrite\s*\(|(?<![\w.])\w+\.save\s*\(|Image\.save\s*\(")


def scan_for_raw_mask_writes(text: str) -> list[tuple[int, str]]:
    """Return (lineno, line) for each offending line lacking the allow marker."""
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER in line:
            continue
        if _FORBIDDEN.search(line):
            hits.append((i, line.strip()))
    return hits


def test_no_raw_mask_writers_in_src() -> None:
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC)
        if rel in WHITELIST:
            continue
        for lineno, line in scan_for_raw_mask_writes(path.read_text(encoding="utf-8")):
            offenders.append(f"{rel}:{lineno}: {line}")
    assert not offenders, (
        "raw mask writers found outside png_strict (use maskfactory.io.png_strict, "
        "or add '# png-strict: allow' for an audited non-mask save):\n" + "\n".join(offenders)
    )


def test_checker_catches_violation_fixture() -> None:
    """The guard itself must flag a deliberate violation (fixture -> fails CI)."""
    bad = 'import cv2\ncv2.imwrite("mask.png", m)\nimg.save("x.png")\n'
    assert scan_for_raw_mask_writes(bad), "checker failed to flag a known violation"
    # ...and the allow-marker escape hatch must suppress it.
    allowed = 'cv2.imwrite("plot.png", fig)  # png-strict: allow\n'
    assert not scan_for_raw_mask_writes(allowed), "allow marker should suppress"
