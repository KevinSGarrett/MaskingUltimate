"""Create a consistent SQLite backup and retain exactly seven nightly generations."""

from __future__ import annotations

import argparse
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path


def backup_database(source: Path, destination: Path, *, retain: int = 7) -> Path:
    source = Path(source)
    destination = Path(destination)
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / f"maskfactory_{datetime.now():%Y%m%d_%H%M%S_%f}.sqlite"
    with (
        closing(sqlite3.connect(source)) as source_db,
        closing(sqlite3.connect(output)) as backup_db,
    ):
        source_db.backup(backup_db)
        row = backup_db.execute("PRAGMA integrity_check").fetchone()
        if row is None or row[0] != "ok":
            raise RuntimeError(f"backup integrity check failed: {row}")
    backups = sorted(
        destination.glob("maskfactory_*.sqlite"), key=lambda path: path.stat().st_mtime
    )
    for expired in backups[:-retain]:
        expired.unlink()
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("data/maskfactory.sqlite"))
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--retain", type=int, default=7)
    args = parser.parse_args()
    if args.retain < 1:
        parser.error("--retain must be positive")
    print(backup_database(args.source, args.destination, retain=args.retain))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
