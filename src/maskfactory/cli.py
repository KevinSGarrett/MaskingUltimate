"""maskfactory command-line interface (doc 05 §3, MF-P0-08.08).

Console entry point ``maskfactory = maskfactory.cli:main``. Every command is a
stub for now (scaffold): each prints where its real implementation will land and
exits cleanly, so ``maskfactory --help`` lists the full command surface and CI
stays green before the stages are wired up.
"""

from __future__ import annotations

import click

from . import __version__

_STUB = "  (stub) not yet implemented — see {spec}"


def _todo(spec: str) -> None:
    click.echo(_STUB.format(spec=spec))


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="maskfactory")
def main() -> None:
    """MaskFactory — body-part mask factory pipeline (Plan/ docs 00–17)."""


# --- core per-image pipeline commands (doc 05 §3 / doc 07 stages) ---
@main.command()
@click.argument("image", required=False)
def ingest(image: str | None) -> None:
    """S00: ingest a new image (age-safety gate + registration)."""
    _todo("doc 07 S00, doc 01 §7")


@main.command()
@click.argument("image_id", required=False)
def run(image_id: str | None) -> None:
    """Run the full drafting pipeline (S01–S09) for an image."""
    _todo("doc 07")


@main.command()
def fuse() -> None:
    """S09: fuse sources into label_map_part/material (doc 03 §4)."""
    _todo("doc 07 S09")


@main.command("export-binaries")
def export_binaries() -> None:
    """Regenerate all binary atomics from the label maps (QC-030 parity)."""
    _todo("doc 03 §4")


@main.command()
def derive() -> None:
    """Regenerate derived/union masks from the maps (script-only)."""
    _todo("doc 03 §4, doc 08")


@main.command("derive-inpaint")
def derive_inpaint() -> None:
    """Derive dilated/feathered inpaint masks (separate from gold)."""
    _todo("doc 03 §6")


@main.command()
@click.argument("image_id", required=False)
def qa(image_id: str | None) -> None:
    """S10: run the auto-QA battery (QC-001..034)."""
    _todo("doc 09")


@main.command()
@click.argument("image_id", required=False)
def vlmqa(image_id: str | None) -> None:
    """S11: local VLM QA + routing (never authoritative)."""
    _todo("doc 10")


@main.group()
def cvat() -> None:
    """CVAT bridge (push drafts / pull corrections)."""


@cvat.command("push")
def cvat_push() -> None:
    """Push draft tasks into CVAT."""
    _todo("doc 11")


@cvat.command("pull")
def cvat_pull() -> None:
    """Pull human-corrected annotations from CVAT."""
    _todo("doc 11")


@main.command()
@click.argument("image_id", required=False)
def package(image_id: str | None) -> None:
    """S13: package + freeze an approved gold image (re-runs QA)."""
    _todo("doc 03, doc 04 §1, MF-P1-07.05")


@main.command("verify-package")
@click.argument("image_id", required=False)
def verify_package(image_id: str | None) -> None:
    """Verify a gold package (all hashes + format QCs)."""
    _todo("doc 03, MF-P1-07.06")


@main.group()
def dataset() -> None:
    """Dataset operations."""


@dataset.command("build")
def dataset_build() -> None:
    """S14: build the training dataset from gold packages."""
    _todo("doc 12")


@main.group()
def coverage() -> None:
    """Coverage-matrix operations."""


@coverage.command("report")
def coverage_report() -> None:
    """Report label x pose coverage (>=80% cells, D5)."""
    _todo("doc 12")


@main.command()
@click.argument("model", required=False)
def train(model: str | None) -> None:
    """Fine-tune a specialist model (doc 12 §6)."""
    _todo("doc 12 §6")


@main.command()
def leaderboard() -> None:
    """Show the model leaderboard + champion (D6/G7)."""
    _todo("doc 12 §7")


@main.command()
def reindex() -> None:
    """Rebuild the SQLite pipeline-state index from packages."""
    _todo("doc 04 §6")


@main.command()
def gc() -> None:
    """Garbage-collect deprecated package versions (runbook §6)."""
    _todo("doc 15 §6")


# --- environment / model management (P0) ---
@main.command()
def doctor() -> None:
    """Environment health checks (MF-P0-07)."""
    _todo("doc 06 §9, MF-P0-07")


@main.group()
def models() -> None:
    """Model checkpoint registry operations."""


@models.command("fetch")
@click.argument("key", required=False)
@click.option("--all", "fetch_all", is_flag=True, help="Fetch every registered model.")
def models_fetch(key: str | None, fetch_all: bool) -> None:
    """Download + register a model checkpoint (SHA-256 + smoke test)."""
    _todo("doc 06 §3, doc 04 §3, MF-P0-06.01")


if __name__ == "__main__":
    main()
