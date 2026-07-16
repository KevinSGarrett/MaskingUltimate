"""maskfactory command-line interface (doc 05 §3, MF-P0-08.08).

Production console entry point ``maskfactory = maskfactory.cli:main``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import click
import yaml

from . import __version__
from .doctor import LOCAL_INFERENCE_TIMEOUT_SECONDS, run_doctor
from .models import (
    DEFAULT_CATALOG,
    DEFAULT_REGISTRY,
    ModelFetchError,
    ModelRegistryError,
    catalog_model_keys,
    fetch_models,
    register_ollama_models,
    register_training_candidate,
)
from .providers.fixtures import DEFAULT_FIXTURES, SelfTestRunner, run_external_fixtures
from .providers.fixtures import DEFAULT_OUTPUT as DEFAULT_FIXTURE_OUTPUT
from .providers.probe import (
    DEFAULT_CONFIG,
    DEFAULT_OUTPUT,
    DEFAULT_WORKFLOWS,
    probe_external_sources,
)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="maskfactory")
def main() -> None:
    """MaskFactory pipeline (Plan docs 00–21; active v1, gated v2)."""


# --- core per-image pipeline commands (doc 05 §3 / doc 07 stages) ---
@main.command()
@click.argument(
    "image", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True
)
@click.option(
    "--incoming-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("data/incoming"),
    show_default=True,
)
@click.option(
    "--images-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("data/images"),
    show_default=True,
)
@click.option(
    "--database",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("data/maskfactory.sqlite"),
    show_default=True,
)
@click.option(
    "--event-log",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("logs/intake.jsonl"),
    show_default=True,
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("configs/pipeline.yaml"),
    show_default=True,
)
def ingest(
    image: Path,
    incoming_root: Path,
    images_root: Path,
    database: Path,
    event_log: Path,
    config_path: Path,
) -> None:
    """S00: ingest a new image (age-safety gate + registration)."""
    from .intake import LocalAgeSafetyScreener, ingest_one
    from .orchestrator import load_pipeline_config

    config = load_pipeline_config(config_path)
    intake_config = config.get("intake", {})
    if not isinstance(intake_config, dict):
        raise click.ClickException("pipeline intake config must be a mapping")
    min_side = intake_config.get("min_side", 512)
    if not isinstance(min_side, int) or min_side < 1:
        raise click.ClickException("intake.min_side must be a positive integer")
    try:
        result = ingest_one(
            image,
            screener=LocalAgeSafetyScreener(),
            incoming_root=incoming_root,
            images_root=images_root,
            database=database,
            event_log=event_log,
            min_side=min_side,
        )
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        json.dumps(
            {
                "image_id": result.image_id,
                "outcome": result.outcome,
                "reason": result.reason,
                "duplicate": result.duplicate,
            },
            sort_keys=True,
        )
    )


@main.command("rescreen-quarantine")
@click.argument(
    "image", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True
)
@click.option(
    "--incoming-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("data/incoming"),
    show_default=True,
)
@click.option(
    "--images-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("data/images"),
    show_default=True,
)
@click.option(
    "--database",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("data/maskfactory.sqlite"),
    show_default=True,
)
@click.option(
    "--event-log",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("logs/intake.jsonl"),
    show_default=True,
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("configs/pipeline.yaml"),
    show_default=True,
)
def rescreen_quarantine(
    image: Path,
    incoming_root: Path,
    images_root: Path,
    database: Path,
    event_log: Path,
    config_path: Path,
) -> None:
    """Re-screen and safely promote one existing age-safety quarantine."""
    from .intake import IntakeError, LocalAgeSafetyScreener, rescreen_quarantined
    from .orchestrator import load_pipeline_config

    config = load_pipeline_config(config_path)
    intake_config = config.get("intake", {})
    min_side = intake_config.get("min_side", 512) if isinstance(intake_config, dict) else 512
    try:
        result = rescreen_quarantined(
            image,
            screener=LocalAgeSafetyScreener(),
            incoming_root=incoming_root,
            images_root=images_root,
            database=database,
            event_log=event_log,
            min_side=min_side,
        )
    except (IntakeError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        json.dumps(
            {"image_id": result.image_id, "outcome": result.outcome, "reason": result.reason},
            sort_keys=True,
        )
    )


@main.command("draft")
@click.argument(
    "image", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True
)
@click.option(
    "--incoming-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("data/incoming"),
    show_default=True,
)
@click.option(
    "--images-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("data/images"),
    show_default=True,
)
@click.option(
    "--work-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("work"),
    show_default=True,
)
@click.option(
    "--database",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("data/maskfactory.sqlite"),
    show_default=True,
)
@click.option(
    "--event-log",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("logs/intake.jsonl"),
    show_default=True,
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("configs/pipeline.yaml"),
    show_default=True,
)
def draft(
    image: Path,
    incoming_root: Path,
    images_root: Path,
    work_root: Path,
    database: Path,
    event_log: Path,
    config_path: Path,
) -> None:
    """D1: draft all active-v1 56 PARTs; gated v2 requires 65 after activation."""
    from .gpu import DEFAULT_GPU_LOCK_PATH, GpuLockError
    from .intake import LocalAgeSafetyScreener, ingest_one
    from .orchestrator import (
        SemanticStageError,
        StageConfigurationError,
        StagePolicyError,
        load_pipeline_config,
    )
    from .stages.production import run_multi_person_production

    try:
        config = load_pipeline_config(config_path)
        intake_config = config.get("intake", {})
        if not isinstance(intake_config, dict):
            raise StageConfigurationError("pipeline intake config must be a mapping")
        min_side = intake_config.get("min_side", 512)
        if not isinstance(min_side, int) or min_side < 1:
            raise StageConfigurationError("intake.min_side must be a positive integer")
        intake = ingest_one(
            image,
            screener=LocalAgeSafetyScreener(),
            incoming_root=incoming_root,
            images_root=images_root,
            database=database,
            event_log=event_log,
            min_side=min_side,
        )
        ready_manifest = images_root / intake.image_id / "manifest.json"
        duplicate_ready = False
        if intake.duplicate and ready_manifest.is_file():
            ready_document = json.loads(ready_manifest.read_text(encoding="utf-8"))
            duplicate_ready = (
                ready_document.get("image_id") == intake.image_id
                and ready_document.get("status") == "ingested"
            )
        if intake.outcome != "ingested" and not duplicate_ready:
            raise StageConfigurationError(
                f"D1 draft refused intake outcome={intake.outcome}: {intake.reason}"
            )
        outcome = run_multi_person_production(
            intake.image_id,
            config=config,
            images_root=images_root,
            work_root=work_root,
            gpu_lock_path=DEFAULT_GPU_LOCK_PATH,
            database=database,
        )
        if outcome.terminal_outcome is not None:
            raise StageConfigurationError(
                f"D1 stopped at S01: {outcome.terminal_outcome} ({outcome.terminal_reason})"
            )
        if len(outcome.draft_contract_paths) != len(outcome.per_instance):
            raise StageConfigurationError("D1 did not emit one atomic contract per instance")
        contracts = []
        for path in outcome.draft_contract_paths:
            document = json.loads(path.read_text(encoding="utf-8"))
            if (
                document.get("contract") != "D1_all_56_atomic_parts"
                or document.get("atomic_count") != 56
            ):
                raise StageConfigurationError(f"D1 atomic contract invalid: {path}")
            contracts.append(str(path))
    except (
        GpuLockError,
        OSError,
        SemanticStageError,
        StageConfigurationError,
        StagePolicyError,
        ValueError,
    ) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        json.dumps(
            {
                "image_id": intake.image_id,
                "intake_outcome": intake.outcome,
                "promoted_instance_count": len(outcome.per_instance),
                "atomic_count_per_instance": 56,
                "draft_contracts": contracts,
                "qc035_passed": outcome.qc035_passed,
            },
            sort_keys=True,
        )
    )


@main.command()
@click.argument("image_id", required=False)
@click.option("--stage", "selected", multiple=True, help="Run only this stage (repeatable).")
@click.option("--force", multiple=True, help="Force this stage even if cached or disabled.")
@click.option("--skip", multiple=True, help="Skip this stage (repeatable).")
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("configs/pipeline.yaml"),
    show_default=True,
)
@click.option(
    "--images-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("data/images"),
    show_default=True,
)
@click.option(
    "--work-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("work"),
    show_default=True,
)
@click.option(
    "--database",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("data/maskfactory.sqlite"),
    show_default=True,
)
@click.option("--plan-only", is_flag=True, help="Print the resolved stage plan without running.")
@click.option(
    "--through-drafts",
    is_flag=True,
    help="Run shared S00/S01, every promoted instance through S09, then S09.5.",
)
@click.option(
    "--through-silhouettes",
    is_flag=True,
    help="Run shared S00/S01 and every promoted instance through S02, then stop.",
)
@click.option(
    "--through-parsing",
    is_flag=True,
    help="Run shared S00/S01 and every promoted instance through S03, then stop.",
)
@click.option(
    "--through-pose",
    is_flag=True,
    help="Run shared S00/S01 and every promoted instance through S04, then stop.",
)
@click.option(
    "--through-openvocab",
    is_flag=True,
    help="Run shared S00/S01 and every promoted instance through S06, then stop.",
)
@click.option(
    "--through-sam2",
    is_flag=True,
    help="Run shared S00/S01 and every promoted instance through S07, then stop.",
)
@click.option(
    "--through-densepose",
    is_flag=True,
    help="Run shared S00/S01 and every promoted instance through S08.5, then stop.",
)
@click.option(
    "--through-autoqa",
    is_flag=True,
    help="Run the activated multi-instance path through per-instance S10 hard gates.",
)
@click.option(
    "--through-review-handoff",
    is_flag=True,
    help="Run every promoted instance through S11 and create the pending S12 CVAT handoff.",
)
def run(
    image_id: str | None,
    selected: tuple[str, ...],
    force: tuple[str, ...],
    skip: tuple[str, ...],
    config_path: Path,
    images_root: Path,
    work_root: Path,
    database: Path,
    plan_only: bool,
    through_drafts: bool,
    through_silhouettes: bool,
    through_parsing: bool,
    through_pose: bool,
    through_openvocab: bool,
    through_sam2: bool,
    through_densepose: bool,
    through_autoqa: bool,
    through_review_handoff: bool,
) -> None:
    """Run the governed S00–S15 file-based stage graph for an image."""
    from .gpu import DEFAULT_GPU_LOCK_PATH, GpuLockError
    from .orchestrator import (
        SemanticStageError,
        StageConfigurationError,
        StagePolicyError,
        StageRunnerMissingError,
        load_pipeline_config,
        plan_stages,
        run_pipeline,
    )
    from .runlog import PipelineRunLog
    from .state import persist_recovered_image_outcome, persist_terminal_image_outcome

    if not image_id:
        raise click.UsageError("IMAGE_ID is required")
    try:
        config = load_pipeline_config(config_path)
        plan = plan_stages(selected=selected, force=force, skip=skip, config=config)
        if plan_only:
            for stage in plan:
                click.echo(stage.name)
            return
        if (
            through_silhouettes
            or through_parsing
            or through_pose
            or through_openvocab
            or through_sam2
            or through_densepose
            or through_drafts
            or through_autoqa
            or through_review_handoff
        ):
            if (
                sum(
                    (
                        through_silhouettes,
                        through_parsing,
                        through_pose,
                        through_openvocab,
                        through_sam2,
                        through_densepose,
                        through_drafts,
                        through_autoqa,
                        through_review_handoff,
                    )
                )
                > 1
            ):
                raise StageConfigurationError("through modes are mutually exclusive")
            if selected or force or skip:
                raise StageConfigurationError(
                    "multi-instance through modes own the exact stage plan; do not combine stage filters"
                )
            from .stages.production import run_multi_person_production

            outcome = run_multi_person_production(
                image_id,
                config=config,
                images_root=images_root,
                work_root=work_root,
                gpu_lock_path=DEFAULT_GPU_LOCK_PATH,
                through_autoqa=through_autoqa,
                through_review_handoff=through_review_handoff,
                database=database,
                silhouettes_only=through_silhouettes,
                parsing_only=through_parsing,
                pose_only=through_pose,
                openvocab_only=through_openvocab,
                sam2_only=through_sam2,
                densepose_only=through_densepose,
            )
            click.echo(f"S00/S01: {len(outcome.shared)} execution(s)")
            if outcome.terminal_outcome is not None:
                click.echo(
                    f"Pipeline terminal: {outcome.terminal_outcome} ({outcome.terminal_reason})"
                )
                return
            for instance, executions in sorted(outcome.per_instance.items()):
                if through_silhouettes:
                    click.echo(f"{instance}: {len(executions)} stage execution(s) S02")
                elif through_parsing:
                    click.echo(f"{instance}: {len(executions)} stage execution(s) S02-S03")
                elif through_pose:
                    click.echo(f"{instance}: {len(executions)} stage execution(s) S02-S04")
                elif through_openvocab:
                    click.echo(f"{instance}: {len(executions)} stage execution(s) S02-S06")
                elif through_sam2:
                    click.echo(f"{instance}: {len(executions)} stage execution(s) S02-S07")
                elif through_densepose:
                    click.echo(f"{instance}: {len(executions)} stage execution(s) S02-S08.5")
                else:
                    terminal = (
                        "S12" if through_review_handoff else "S10" if through_autoqa else "S09"
                    )
                    click.echo(f"{instance}: {len(executions)} stage execution(s) S02-{terminal}")
            if through_silhouettes:
                click.echo(f"S02 batch complete: {len(outcome.per_instance)} instance(s)")
                return
            if through_parsing:
                click.echo(f"S03 batch complete: {len(outcome.per_instance)} instance(s)")
                return
            if through_pose:
                click.echo(f"S04 batch complete: {len(outcome.per_instance)} instance(s)")
                return
            if through_openvocab:
                click.echo(f"S06 batch complete: {len(outcome.per_instance)} instance(s)")
                return
            if through_sam2:
                click.echo(f"S07 batch complete: {len(outcome.per_instance)} instance(s)")
                return
            if through_densepose:
                click.echo(f"S08.5 batch complete: {len(outcome.per_instance)} instance(s)")
                return
            click.echo(f"S09.5: {outcome.image_manifest_path} qc035={outcome.qc035_passed}")
            for contract in outcome.draft_contract_paths:
                click.echo(f"D1: {contract}")
            if through_review_handoff:
                task_ids = ",".join(str(task_id) for task_id in outcome.cvat_task_ids)
                click.echo(
                    "S12 CVAT tasks: " f"{task_ids}; status=pending_kevin_correction_and_approval"
                )
            return
        with PipelineRunLog(image_ids=(image_id,), config=config) as run_log:
            from .stages.production import build_production_runners

            results = run_pipeline(
                image_id,
                selected=selected,
                force=force,
                skip=skip,
                config=config,
                work_root=work_root,
                runners=build_production_runners(config, images_root=images_root),
                gpu_lock_path=DEFAULT_GPU_LOCK_PATH,
                run_log=run_log,
            )
        terminal = next((result for result in results if result.status == "terminal"), None)
        if terminal is not None and terminal.terminal_outcome in {"rejected", "quarantined"}:
            persist_terminal_image_outcome(
                database,
                image_id,
                str(terminal.terminal_outcome),
                reason=str(terminal.terminal_reason),
                current_stage=terminal.stage,
            )
        elif any(result.stage == "S01" and result.status == "complete" for result in results):
            persist_recovered_image_outcome(database, image_id, current_stage="S01")
    except (
        StageConfigurationError,
        StageRunnerMissingError,
        StagePolicyError,
        GpuLockError,
        SemanticStageError,
        ValueError,
    ) as exc:
        raise click.ClickException(str(exc)) from exc
    for result in results:
        click.echo(f"{result.stage}: {result.status} config={result.config_hash}")


@main.command()
@click.argument("package_root", type=click.Path(path_type=Path, file_okay=False, exists=True))
@click.option("--part-masks", type=click.Path(path_type=Path, file_okay=False))
@click.option("--material-masks", type=click.Path(path_type=Path, file_okay=False))
def fuse(package_root: Path, part_masks: Path | None, material_masks: Path | None) -> None:
    """S09: fuse sources into label_map_part/material (doc 03 §4)."""
    from .fusion.mapbuild import MapBuildError, fuse_package

    try:
        outputs = fuse_package(package_root, part_masks=part_masks, material_masks=material_masks)
    except (MapBuildError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    for output in outputs:
        click.echo(output)


@main.command("export-binaries")
@click.argument("package_root", type=click.Path(path_type=Path, file_okay=False, exists=True))
def export_binaries(package_root: Path) -> None:
    """Regenerate all binary atomics from the label maps (QC-030 parity)."""
    from .fusion.mapbuild import MapBuildError
    from .fusion.mapbuild import export_binaries as regenerate

    try:
        outputs = regenerate(package_root)
    except (MapBuildError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"generated {len(outputs)} binary views")


@main.command()
@click.argument("package_root", type=click.Path(path_type=Path, file_okay=False, exists=True))
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/derived.yaml"),
    show_default=True,
)
def derive(package_root: Path, config_path: Path) -> None:
    """Regenerate derived/union masks from the maps (script-only)."""
    from .derive import DeriveError, derive_package

    try:
        outputs = derive_package(package_root, config_path=config_path)
    except (DeriveError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"generated {len(outputs)} derived masks")


@main.command("derive-inpaint")
@click.argument("package_root", type=click.Path(path_type=Path, file_okay=False, exists=True))
@click.option("--label", "labels", multiple=True, help="Target label (repeatable).")
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/inpaint.yaml"),
    show_default=True,
)
def derive_inpaint(package_root: Path, labels: tuple[str, ...], config_path: Path) -> None:
    """Derive dilated/feathered inpaint masks (separate from gold)."""
    from .inpaint import InpaintError
    from .inpaint import derive_inpaint as generate

    try:
        outputs = generate(package_root, labels=labels, config_path=config_path)
    except (InpaintError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    for output in outputs:
        click.echo(output)


@main.command()
@click.argument("image_id", required=True)
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("configs/pipeline.yaml"),
    show_default=True,
)
@click.option(
    "--images-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("data/images"),
    show_default=True,
)
@click.option(
    "--work-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("work"),
    show_default=True,
)
@click.option(
    "--database",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("data/maskfactory.sqlite"),
    show_default=True,
)
def qa(
    image_id: str,
    config_path: Path,
    images_root: Path,
    work_root: Path,
    database: Path,
) -> None:
    """Force S10 auto-QA for every promoted instance and report BLOCK outcomes."""
    from .gpu import DEFAULT_GPU_LOCK_PATH, GpuLockError
    from .orchestrator import (
        SemanticStageError,
        StageConfigurationError,
        StagePolicyError,
        load_pipeline_config,
    )
    from .stages.production import run_multi_person_production
    from .validation import validate_document

    try:
        outcome = run_multi_person_production(
            image_id,
            config=load_pipeline_config(config_path),
            images_root=images_root,
            work_root=work_root,
            gpu_lock_path=DEFAULT_GPU_LOCK_PATH,
            through_autoqa=True,
            force_autoqa=True,
            database=database,
        )
        if outcome.terminal_outcome is not None:
            document = {
                "image_id": image_id,
                "instances": {},
                "status": outcome.terminal_outcome,
                "reason": outcome.terminal_reason,
            }
            click.echo(json.dumps(document, sort_keys=True))
            raise click.exceptions.Exit(1)
        instances = {}
        block_count = 0
        for instance in sorted(outcome.per_instance):
            report_path = work_root / "instances" / instance / "s10" / image_id / "qa_report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            issues = validate_document(report, "qa_report")
            if issues:
                raise ValueError(f"invalid S10 report {report_path}: {issues}")
            failed_blocks = [
                check["id"]
                for check in report["checks"]
                if check["result"] == "fail" and check["severity"] == "BLOCK"
            ]
            routed = [check["id"] for check in report["checks"] if check["result"] == "route"]
            block_count += len(failed_blocks)
            instances[instance] = {
                "failed_blocks": failed_blocks,
                "overall": report["overall"],
                "report": str(report_path),
                "routed": routed,
                "score": report["score"],
            }
        document = {
            "failed_block_count": block_count,
            "image_id": image_id,
            "instance_count": len(instances),
            "instances": instances,
            "qc035_passed": outcome.qc035_passed,
            "status": (
                "blocked"
                if block_count
                else (
                    "needs_human"
                    if any(item["overall"] != "pass" for item in instances.values())
                    else "pass"
                )
            ),
        }
        click.echo(json.dumps(document, sort_keys=True))
        if block_count:
            raise click.exceptions.Exit(1)
    except click.exceptions.Exit:
        raise
    except (
        GpuLockError,
        OSError,
        SemanticStageError,
        StageConfigurationError,
        StagePolicyError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise click.ClickException(str(exc)) from exc


@main.command("manifest-lint")
@click.option(
    "--packages-root",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path("data/packages"),
    show_default=True,
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("qa/reports/manifest_lint.json"),
    show_default=True,
)
@click.option(
    "--state",
    "state_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("qa/reports/manifest_lint_state.json"),
    show_default=True,
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/vlm.yaml"),
    show_default=True,
)
def manifest_lint(
    packages_root: Path, output_path: Path, state_path: Path, config_path: Path
) -> None:
    """Run the local text-only P-MANIFEST sweep across package manifests."""
    from .vlm.text import TextLlmError, run_manifest_lint_sweep

    try:
        report = run_manifest_lint_sweep(
            packages_root=packages_root,
            output_path=output_path,
            state_path=state_path,
            vlm_config_path=config_path,
        )
    except (OSError, KeyError, ValueError, TextLlmError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(report)


@main.command("active-learning")
@click.option(
    "--failure-queue",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("qa/failure_queue.jsonl"),
    show_default=True,
)
@click.option(
    "--coverage-matrix",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("qa/coverage_matrix.json"),
    show_default=True,
)
@click.option(
    "--packages-root",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path("data/packages"),
    show_default=True,
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("qa/reports"),
    show_default=True,
)
@click.option(
    "--certified-training-package-count",
    "--approved-gold-count",
    "certified_training_package_count",
    type=click.IntRange(min=0),
    default=None,
)
@click.option(
    "--champion-certified-package-count",
    "--champion-gold-count",
    "champion_certified_package_count",
    type=click.IntRange(min=0),
    default=0,
    show_default=True,
)
@click.option("--report-date", default=None, help="ISO date override for deterministic reruns.")
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/vlm.yaml"),
    show_default=True,
)
@click.option(
    "--reference-database",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path(r"C:\Temp\MaskFactory_Reference_Library\reference_working.sqlite"),
    show_default=True,
)
@click.option(
    "--reference-policy",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/reference_library.yaml"),
    show_default=True,
)
@click.option(
    "--reference-benchmark-manifest",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
)
def active_learning(
    failure_queue: Path,
    coverage_matrix: Path,
    packages_root: Path,
    output_dir: Path,
    certified_training_package_count: int | None,
    champion_certified_package_count: int,
    report_date: str | None,
    config_path: Path,
    reference_database: Path,
    reference_policy: Path,
    reference_benchmark_manifest: Path | None,
) -> None:
    """Run the governed weekly failure-mining and QA-summary batch."""
    from .datasets.active_learning import run_active_learning
    from .datasets.builder import approved_package_count
    from .qa.failure_mining import FailureMiningError
    from .vlm.client import VlmClientError
    from .vlm.text import TextLlmError

    count = (
        certified_training_package_count
        if certified_training_package_count is not None
        else approved_package_count(packages_root)
    )
    try:
        result = run_active_learning(
            failure_queue_path=failure_queue,
            coverage_matrix_path=coverage_matrix,
            output_dir=output_dir,
            certified_training_package_count=count,
            champion_certified_package_count=champion_certified_package_count,
            report_date=report_date,
            packages_root=packages_root,
            vlm_config_path=config_path,
            reference_database=reference_database,
            reference_policy_path=reference_policy,
            reference_benchmark_manifest=reference_benchmark_manifest,
        )
    except (FailureMiningError, OSError, ValueError, TextLlmError, VlmClientError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(result, indent=2, sort_keys=True))


@main.group()
def review() -> None:
    """Resolve queued early-stage semantic reviews with human authority."""


@review.command("resolve-s02")
@click.argument("image_id", required=True)
@click.argument("instance_id", required=True)
@click.option(
    "--mask",
    "reviewed_mask",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    required=True,
)
@click.option("--reviewer", required=True)
@click.option(
    "--decision",
    type=click.Choice(["confirmed_valid", "corrected"], case_sensitive=True),
    required=True,
)
@click.option("--note", required=True)
@click.option(
    "--work-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("work"),
    show_default=True,
)
@click.option(
    "--images-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("data/images"),
    show_default=True,
)
def review_resolve_s02(
    image_id: str,
    instance_id: str,
    reviewed_mask: Path,
    reviewer: str,
    decision: str,
    note: str,
    work_root: Path,
    images_root: Path,
) -> None:
    """Seal a reviewed S02 mask; the next draft run replays and verifies it."""
    from .review_resolution import ReviewResolutionError, create_s02_review_resolution

    try:
        resolution = create_s02_review_resolution(
            image_id,
            instance_id,
            reviewed_mask,
            reviewer=reviewer,
            decision=decision,
            note=note,
            work_root=work_root,
            images_root=images_root,
        )
    except (OSError, ReviewResolutionError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps({"resolution": str(resolution)}, sort_keys=True))


@review.command("prepare-s02")
@click.option(
    "--work-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("work"),
    show_default=True,
)
@click.option(
    "--images-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("data/images"),
    show_default=True,
)
@click.option(
    "--output-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("qa/review_handoffs/s02"),
    show_default=True,
)
def review_prepare_s02(work_root: Path, images_root: Path, output_root: Path) -> None:
    """Render panels and copy-ready commands for every queued S02 review."""
    from .review_resolution import ReviewResolutionError, build_s02_review_handoffs

    try:
        index = build_s02_review_handoffs(
            work_root=work_root, images_root=images_root, output_root=output_root
        )
        document = json.loads(index.read_text(encoding="utf-8"))
    except (OSError, ReviewResolutionError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        json.dumps(
            {
                "index": str(index),
                "count": document["count"],
                "awaiting_human_review": document["awaiting_human_review"],
            },
            sort_keys=True,
        )
    )


@main.group("second-review")
def second_review() -> None:
    """Stratified fresh-eyes review workflow (doc 11 §6)."""


@second_review.command("sample")
@click.option(
    "--packages-root",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path("data/packages"),
    show_default=True,
)
@click.option("--seed", required=True, help="Stable weekly selection seed, e.g. 2026-W28.")
def second_review_sample(packages_root: Path, seed: str) -> None:
    """Print the deterministic 15% approved-package sample as JSON."""
    from .qa.second_review import SecondReviewError, sample_approved_packages

    try:
        samples = sample_approved_packages(packages_root, seed=seed)
    except (OSError, ValueError, SecondReviewError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        json.dumps(
            [
                {
                    "image_id": sample.image_id,
                    "package_root": str(sample.package_root),
                    "part": sample.part,
                    "hard_class": sample.hard_class,
                }
                for sample in samples
            ],
            indent=2,
            sort_keys=True,
        )
    )


@second_review.command("record")
@click.argument("evidence_file", type=click.Path(path_type=Path, dir_okay=False, exists=True))
@click.option(
    "--iaa-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("qa/iaa"),
    show_default=True,
)
@click.option(
    "--failure-queue",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("qa/failure_queue.jsonl"),
    show_default=True,
)
def second_review_record(evidence_file: Path, iaa_root: Path, failure_queue: Path) -> None:
    """Validate and commit a JSON second-review evidence form."""
    from datetime import datetime

    from .qa.second_review import (
        PartVerdict,
        SecondReviewError,
        record_second_review,
    )

    try:
        form = json.loads(evidence_file.read_text(encoding="utf-8"))
        verdicts = tuple(
            PartVerdict(
                item["part"],
                item["result"],
                Path(item["original_mask"]),
                Path(item["reviewed_mask"]),
                item.get("correction", ""),
            )
            for item in form["verdicts"]
        )
        output = record_second_review(
            Path(form["package_root"]),
            verdicts,
            reviewer=form["reviewer"],
            panels_first_at=datetime.fromisoformat(form["panels_first_at"].replace("Z", "+00:00")),
            full_image_at=datetime.fromisoformat(form["full_image_at"].replace("Z", "+00:00")),
            completed_at=datetime.fromisoformat(form["completed_at"].replace("Z", "+00:00")),
            iaa_root=iaa_root,
            failure_queue_path=failure_queue,
        )
    except (
        KeyError,
        TypeError,
        OSError,
        ValueError,
        json.JSONDecodeError,
        SecondReviewError,
    ) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(output)


@second_review.command("report")
@click.option(
    "--iaa-root",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path("qa/iaa"),
    show_default=True,
)
@click.option("--iso-week", required=True, help="Report week in YYYY-Www format.")
@click.option(
    "--reports-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("qa/reports"),
    show_default=True,
)
def second_review_report(iaa_root: Path, iso_week: str, reports_root: Path) -> None:
    """Measure archived mask pairs and emit IAA plus human-ceiling input."""
    from .qa.second_review import SecondReviewError, write_weekly_iaa_report

    try:
        outputs = write_weekly_iaa_report(iaa_root, iso_week=iso_week, reports_root=reports_root)
    except (OSError, ValueError, SecondReviewError) as exc:
        raise click.ClickException(str(exc)) from exc
    for output in outputs:
        click.echo(output)


@main.group(invoke_without_command=True)
@click.pass_context
def vlmqa(context: click.Context) -> None:
    """S11: local VLM QA + routing (never authoritative)."""
    if context.invoked_subcommand is None:
        click.echo(context.get_help())


@vlmqa.command("run")
@click.argument("image_id", required=True)
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("configs/pipeline.yaml"),
    show_default=True,
)
@click.option(
    "--images-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("data/images"),
    show_default=True,
)
@click.option(
    "--work-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("work"),
    show_default=True,
)
@click.option(
    "--database",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("data/maskfactory.sqlite"),
    show_default=True,
)
def vlmqa_run(
    image_id: str,
    config_path: Path,
    images_root: Path,
    work_root: Path,
    database: Path,
) -> None:
    """Force S10+S11 for every promoted instance; refuse an unavailable VLM gate."""
    from .gpu import DEFAULT_GPU_LOCK_PATH, GpuLockError
    from .orchestrator import (
        SemanticStageError,
        StageConfigurationError,
        StagePolicyError,
        load_pipeline_config,
    )
    from .stages.production import run_multi_person_production
    from .validation import validate_document

    try:
        outcome = run_multi_person_production(
            image_id,
            config=load_pipeline_config(config_path),
            images_root=images_root,
            work_root=work_root,
            gpu_lock_path=DEFAULT_GPU_LOCK_PATH,
            through_vlmqa=True,
            force_autoqa=True,
            force_vlmqa=True,
            database=database,
        )
        if outcome.terminal_outcome is not None:
            click.echo(
                json.dumps(
                    {
                        "image_id": image_id,
                        "instances": {},
                        "reason": outcome.terminal_reason,
                        "status": outcome.terminal_outcome,
                    },
                    sort_keys=True,
                )
            )
            raise click.exceptions.Exit(1)
        instances = {}
        for instance in sorted(outcome.per_instance):
            directory = work_root / "instances" / instance / "s11" / image_id
            report_path = directory / "qa_report.json"
            routing_path = directory / "vlm_routing.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            routing = json.loads(routing_path.read_text(encoding="utf-8"))
            issues = validate_document(report, "qa_report")
            if issues:
                raise ValueError(f"invalid S11 report {report_path}: {issues}")
            route_counts = {}
            for route in routing.get("routes", {}).values():
                queue = str(route["queue"])
                route_counts[queue] = route_counts.get(queue, 0) + 1
            instances[instance] = {
                "enabled": bool(routing["enabled"]),
                "overall": report["overall"],
                "reason": routing.get("reason"),
                "report": str(report_path),
                "route_counts": dict(sorted(route_counts.items())),
                "routing": str(routing_path),
                "verdict_count": len(report["vlm_review"]["verdicts"]),
                "whole_image_status": routing["whole_image_review"]["status"],
            }
        blocked = any(item["overall"] == "fail" for item in instances.values())
        disabled = any(not item["enabled"] for item in instances.values())
        needs_human = any(item["overall"] == "needs_human" for item in instances.values())
        status = (
            "blocked"
            if blocked
            else (
                "disabled_gate_unavailable"
                if disabled
                else "needs_human" if needs_human else "pass"
            )
        )
        click.echo(
            json.dumps(
                {
                    "image_id": image_id,
                    "instance_count": len(instances),
                    "instances": instances,
                    "status": status,
                },
                sort_keys=True,
            )
        )
        if blocked or disabled:
            raise click.exceptions.Exit(1)
    except click.exceptions.Exit:
        raise
    except (
        GpuLockError,
        OSError,
        SemanticStageError,
        StageConfigurationError,
        StagePolicyError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise click.ClickException(str(exc)) from exc


@vlmqa.command("build-calibration")
@click.option(
    "--selection",
    "selection_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    required=True,
    help="Reviewed 20-case selection over frozen human-approved gold packages.",
)
@click.option(
    "--packages-root",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path("data/packages"),
    show_default=True,
)
@click.option(
    "--images-root",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path("data/images"),
    show_default=True,
)
@click.option(
    "--output",
    "output_root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("qa/vlm_eval"),
    show_default=True,
)
def vlmqa_build_calibration(
    selection_path: Path,
    packages_root: Path,
    images_root: Path,
    output_root: Path,
) -> None:
    """Build the fixed VLM gate corpus from verified human-approved gold only."""
    from .vlm.eval import VlmEvalError, build_calibration_from_gold_selection

    try:
        cases = build_calibration_from_gold_selection(
            selection_path,
            output_root,
            packages_root=packages_root,
            images_root=images_root,
        )
    except (OSError, ValueError, VlmEvalError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        json.dumps(
            {
                "output": str(output_root),
                "total": len(cases),
                "good": sum(not case.expected_defect for case in cases),
                "defect": sum(case.expected_defect for case in cases),
            },
            sort_keys=True,
        )
    )


@vlmqa.command("eval")
@click.option(
    "--calibration-root",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path("qa/vlm_eval"),
    show_default=True,
)
@click.option(
    "--predictions",
    "predictions_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    required=False,
    help="JSON object mapping every calibration case ID to pass/fail/uncertain.",
)
@click.option("--live", is_flag=True, help="Run all panels through local Ollama.")
@click.option("--model", required=True, help="Exact evaluated Ollama model identifier.")
@click.option("--prompt-version", default="v1", show_default=True)
@click.option(
    "--prompt",
    "prompt_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("src/maskfactory/vlm/prompts/p_part.txt"),
    show_default=True,
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("qa/vlm_eval/results"),
    show_default=True,
)
def vlmqa_eval(
    calibration_root: Path,
    predictions_path: Path,
    live: bool,
    model: str,
    prompt_version: str,
    prompt_path: Path,
    output_dir: Path,
) -> None:
    """Score the fixed 40-panel set and atomically update the production gate."""
    from .vlm.client import VlmClientError
    from .vlm.eval import VlmEvalError, evaluate_gate, load_cases, predict_live

    try:
        if live == (predictions_path is not None):
            raise VlmEvalError("choose exactly one of --live or --predictions")
        cases = load_cases(calibration_root)
        predictions = (
            predict_live(
                cases,
                calibration_root=calibration_root,
                model=model,
                prompt_path=prompt_path,
                output_dir=output_dir,
                gpu_lock_path=Path("runs/gpu.lock"),
            )
            if live
            else json.loads(predictions_path.read_text(encoding="utf-8"))
        )
        if not isinstance(predictions, dict):
            raise VlmEvalError("predictions JSON must be an object")
        report = evaluate_gate(
            cases,
            predictions,
            model=model,
            prompt_version=prompt_version,
            prompt_path=prompt_path,
            output_dir=output_dir,
        )
    except (OSError, ValueError, json.JSONDecodeError, VlmClientError, VlmEvalError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(report.__dict__, sort_keys=True))
    if not report.passed:
        raise click.ClickException("VLM production gate failed calibration thresholds")


@vlmqa.command("cloud-status")
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/cloud_teacher.yaml"),
    show_default=True,
)
def vlmqa_cloud_status(config_path: Path) -> None:
    """Report cloud-teacher readiness and spend without making an API call."""
    from .vlm.cloud_budget import CloudBudgetError, DailyBudgetLedger
    from .vlm.cloud_providers import credential_present
    from .vlm.cloud_teacher import CloudTeacherError, load_cloud_teacher_config

    try:
        config = load_cloud_teacher_config(config_path)
        budget = config["budget"]
        snapshot = DailyBudgetLedger(
            Path(budget["ledger_path"]),
            timezone_name=budget["timezone"],
            hard_limit_usd=budget["hard_limit_usd"],
            lock_timeout_sec=float(budget["lock_timeout_sec"]),
        ).snapshot()
        providers = {
            name: {
                "enabled": settings["enabled"],
                "model": settings["model"],
                "credential_present": credential_present(settings["api_key_env"], name),
            }
            for name, settings in config["providers"].items()
        }
    except (OSError, ValueError, CloudBudgetError, CloudTeacherError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        json.dumps(
            {
                "enabled": config["enabled"],
                "mode": config["mode"],
                "providers": providers,
                "budget": {
                    "local_date": snapshot.local_date,
                    "committed_usd": str(snapshot.committed_usd),
                    "reserved_usd": str(snapshot.reserved_usd),
                    "available_usd": str(snapshot.available_usd),
                    "hard_limit_usd": str(snapshot.hard_limit_usd),
                    "request_count": snapshot.request_count,
                },
            },
            sort_keys=True,
        )
    )


@vlmqa.command("harvest-teacher-resolution")
@click.argument("package_root", type=click.Path(path_type=Path, file_okay=False, exists=True))
@click.argument("teacher_report", type=click.Path(path_type=Path, dir_okay=False, exists=True))
@click.option(
    "--output",
    "output_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("qa/teacher_learning/resolutions.jsonl"),
    show_default=True,
)
def vlmqa_harvest_teacher_resolution(
    package_root: Path, teacher_report: Path, output_path: Path
) -> None:
    """Append one cloud-teacher learning record from frozen human-approved gold."""
    from .vlm.cloud_teacher import CloudTeacherError, harvest_human_teacher_resolution

    try:
        record = harvest_human_teacher_resolution(
            package_root=package_root,
            teacher_report_path=teacher_report,
            output_path=output_path,
        )
    except (OSError, ValueError, CloudTeacherError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(record, sort_keys=True))


@vlmqa.command("build-distillation")
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/cloud_teacher.yaml"),
    show_default=True,
)
@click.option(
    "--records",
    "records_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("qa/teacher_learning/resolutions.jsonl"),
    show_default=True,
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("qa/teacher_learning/distillation_manifest.json"),
    show_default=True,
)
def vlmqa_build_distillation(config_path: Path, records_path: Path, output_path: Path) -> None:
    """Build image-disjoint prompt/LoRA readiness evidence from human-gold records."""
    from .vlm.cloud_teacher import (
        CloudTeacherError,
        build_teacher_distillation_manifest,
        load_cloud_teacher_config,
    )

    try:
        config = load_cloud_teacher_config(config_path)
        learning = config["learning"]
        document = build_teacher_distillation_manifest(
            records_path=records_path,
            output_path=output_path,
            minimum_prompt_records=int(learning["minimum_balanced_records_for_prompt_exemplars"]),
            minimum_lora_records=int(learning["minimum_balanced_records_for_lora_candidate"]),
            holdout_fraction=float(learning["frozen_holdout_fraction"]),
        )
    except (OSError, ValueError, CloudTeacherError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(document, sort_keys=True))


@vlmqa.command("evaluate-cloud-teacher")
@click.argument("corpus", type=click.Path(path_type=Path, dir_okay=False, exists=True))
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/cloud_teacher.yaml"),
    show_default=True,
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("qa/teacher_learning/cloud_teacher_eval.json"),
    show_default=True,
)
def vlmqa_evaluate_cloud_teacher(corpus: Path, config_path: Path, output_path: Path) -> None:
    """Evaluate a provider offline against frozen human truth; never call an API."""
    from .vlm.cloud_eval import (
        CloudTeacherEvalError,
        evaluate_cloud_teacher_corpus,
        write_cloud_teacher_eval_report,
    )
    from .vlm.cloud_teacher import CloudTeacherError, load_cloud_teacher_config

    try:
        config = load_cloud_teacher_config(config_path)
        report = evaluate_cloud_teacher_corpus(corpus, thresholds=config["evaluation"])
        write_cloud_teacher_eval_report(report, output_path)
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        CloudTeacherError,
        CloudTeacherEvalError,
    ) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(report.__dict__, sort_keys=True))
    if not report.passed:
        raise click.ClickException("cloud teacher failed frozen human-truth thresholds")


@main.group()
def autonomy() -> None:
    """Progressive autonomous mask calibration and candidate tournaments."""


@autonomy.command("evaluate-stability")
@click.argument("manifest_path", type=click.Path(path_type=Path, dir_okay=False, exists=True))
@click.option(
    "--policy",
    "policy_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/autonomy_stability.yaml"),
    show_default=True,
)
@click.option("--output", type=click.Path(path_type=Path, dir_okay=False), required=True)
def autonomy_evaluate_stability(manifest_path: Path, policy_path: Path, output: Path) -> None:
    """Evaluate five inverse-aligned perturbations before certification."""
    from .autonomy.stability import (
        StabilityError,
        evaluate_candidate_stability,
        load_stability_policy,
    )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        required = {
            "base_mask_path",
            "candidate_id",
            "pipeline_fingerprint",
            "risk_bucket",
            "label",
            "variants",
        }
        if not isinstance(manifest, dict) or set(manifest) != required:
            raise StabilityError("stability manifest has the wrong contract")
        root = manifest_path.parent
        variants = []
        for row in manifest["variants"]:
            if not isinstance(row, dict):
                raise StabilityError("stability manifest variants must be objects")
            variant = dict(row)
            variant["mask_path"] = root / str(variant["mask_path"])
            variants.append(variant)
        evidence = evaluate_candidate_stability(
            root / str(manifest["base_mask_path"]),
            variants,
            candidate_id=manifest["candidate_id"],
            pipeline_fingerprint=manifest["pipeline_fingerprint"],
            risk_bucket=manifest["risk_bucket"],
            label=manifest["label"],
            policy=load_stability_policy(policy_path),
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (StabilityError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(evidence, sort_keys=True))


@autonomy.command("build-certificate")
@click.argument("audit", type=click.Path(path_type=Path, dir_okay=False, exists=True))
@click.option("--label", required=True)
@click.option("--context", required=True)
@click.option("--risk-bucket", required=False)
@click.option(
    "--pooling-evidence",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    required=False,
)
@click.option(
    "--stability-evidence",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    multiple=True,
)
@click.option("--pipeline-fingerprint", required=True)
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/autonomous_masks.yaml"),
    show_default=True,
)
@click.option(
    "--gold-packages-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("data/packages"),
    show_default=True,
)
@click.option(
    "--machine-artifacts-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("runs"),
    show_default=True,
)
@click.option("--output", type=click.Path(path_type=Path, dir_okay=False), required=True)
def autonomy_build_certificate(
    audit: Path,
    label: str,
    context: str,
    risk_bucket: str | None,
    pooling_evidence: Path | None,
    stability_evidence: tuple[Path, ...],
    pipeline_fingerprint: str,
    config_path: Path,
    gold_packages_root: Path,
    machine_artifacts_root: Path,
    output: Path,
) -> None:
    """Build a 95%-confidence label/context autoaccept certificate."""
    from .autonomy.calibration import (
        AutonomyCalibrationError,
        build_autonomy_certificate,
        load_autonomy_config,
    )

    try:
        config = load_autonomy_config(config_path)
        pooling_document = (
            json.loads(pooling_evidence.read_text(encoding="utf-8"))
            if pooling_evidence is not None
            else None
        )
        stability_documents = [
            json.loads(path.read_text(encoding="utf-8")) for path in stability_evidence
        ]
        certificate = build_autonomy_certificate(
            audit,
            label=label,
            context=context,
            risk_bucket=risk_bucket,
            pooling_evidence=pooling_document,
            stability_evidence=stability_documents,
            pipeline_fingerprint=pipeline_fingerprint,
            policy=config["calibration"],
            gold_packages_root=gold_packages_root,
            machine_artifacts_root=machine_artifacts_root,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(certificate, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except (AutonomyCalibrationError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(certificate, sort_keys=True))


@autonomy.command("tournament")
@click.argument("input_path", type=click.Path(path_type=Path, dir_okay=False, exists=True))
@click.option(
    "--certificate", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=False
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/autonomous_masks.yaml"),
    show_default=True,
)
@click.option("--output", type=click.Path(path_type=Path, dir_okay=False), required=True)
def autonomy_tournament(
    input_path: Path, certificate: Path | None, config_path: Path, output: Path
) -> None:
    """Select a hard-vetoed candidate and apply any valid autonomy certificate."""
    from .autonomy.calibration import load_autonomy_config
    from .autonomy.tournament import (
        AutonomyTournamentError,
        CandidateEvidence,
        run_candidate_tournament,
    )

    try:
        document = json.loads(input_path.read_text(encoding="utf-8"))
        config = load_autonomy_config(config_path)
        cert = json.loads(certificate.read_text(encoding="utf-8")) if certificate else None
        candidates = tuple(CandidateEvidence(**candidate) for candidate in document["candidates"])
        decision = run_candidate_tournament(
            candidates,
            label=document["label"],
            context=document["context"],
            pipeline_fingerprint=document["pipeline_fingerprint"],
            config=config,
            certificate=cert,
        )
        payload = decision.as_dict()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (
        AutonomyTournamentError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        json.JSONDecodeError,
    ) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(payload, sort_keys=True))


@autonomy.command("build-audit-queue")
@click.option(
    "--lifecycle-root",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path("work/instances"),
    show_default=True,
)
@click.option("--period-id", required=True, help="Stable ISO period such as 2026-W28.")
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/autonomous_masks.yaml"),
    show_default=True,
)
@click.option("--output", type=click.Path(path_type=Path, dir_okay=False), required=True)
def autonomy_build_audit_queue(
    lifecycle_root: Path, period_id: str, config_path: Path, output: Path
) -> None:
    """Select the deterministic weekly sample from calibrated autoaccepted masks."""
    from .autonomy.calibration import AutonomyCalibrationError, load_autonomy_config
    from .autonomy.operations import build_weekly_audit_queue

    try:
        config = load_autonomy_config(config_path)
        queue = build_weekly_audit_queue(
            lifecycle_root,
            output,
            period_id=period_id,
            operations_policy=config["operations"],
        )
    except (AutonomyCalibrationError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(queue, sort_keys=True))


@autonomy.command("process-audits")
@click.argument("queue", type=click.Path(path_type=Path, dir_okay=False, exists=True))
@click.argument("outcomes", type=click.Path(path_type=Path, dir_okay=False, exists=True))
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/autonomous_masks.yaml"),
    show_default=True,
)
@click.option(
    "--revocations-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("qa/autonomy/revocations"),
    show_default=True,
)
@click.option("--retraining-output", type=click.Path(path_type=Path, dir_okay=False), required=True)
def autonomy_process_audits(
    queue: Path,
    outcomes: Path,
    config_path: Path,
    revocations_root: Path,
    retraining_output: Path,
) -> None:
    """Ingest exact audit outcomes, revoke failures, and create a retraining plan."""
    from .autonomy.calibration import AutonomyCalibrationError, load_autonomy_config
    from .autonomy.operations import process_audit_outcomes

    try:
        config = load_autonomy_config(config_path)
        result = process_audit_outcomes(
            queue,
            outcomes,
            revocations_root=revocations_root,
            retraining_policy=config["retraining"],
            operations_policy=config["operations"],
            retraining_output_path=retraining_output,
        )
    except (AutonomyCalibrationError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(result, sort_keys=True))


@autonomy.command("serious-failure-drill")
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/autonomous_masks.yaml"),
    show_default=True,
)
@click.option(
    "--output-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("qa/autonomy/serious_failure_drills"),
    show_default=True,
)
def autonomy_serious_failure_drill(config_path: Path, output_root: Path) -> None:
    """Run an isolated serious false-accept revocation and retraining drill."""
    from .autonomy.calibration import AutonomyCalibrationError, load_autonomy_config
    from .autonomy.operations import run_serious_failure_drill

    try:
        config = load_autonomy_config(config_path)
        report = run_serious_failure_drill(
            output_root,
            operations_policy=config["operations"],
            retraining_policy=config["retraining"],
        )
    except (AutonomyCalibrationError, OSError, ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(report, sort_keys=True))


@autonomy.command("build-pseudo-dataset")
@click.option(
    "--lifecycle-root",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    required=True,
)
@click.option(
    "--certificate-root",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    required=True,
)
@click.option(
    "--revocations-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("qa/autonomy/revocations"),
    show_default=True,
)
@click.option(
    "--protected-anchor-ids",
    "--human-holdout-ids",
    "protected_anchor_ids",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    required=True,
    help="Image IDs from both human-anchor calibration and holdout partitions.",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/autonomous_masks.yaml"),
    show_default=True,
)
@click.option("--output", type=click.Path(path_type=Path, dir_okay=False), required=True)
def autonomy_build_pseudo_dataset(
    lifecycle_root: Path,
    certificate_root: Path,
    revocations_root: Path,
    protected_anchor_ids: Path,
    config_path: Path,
    output: Path,
) -> None:
    """Build a hash-verified train-only manifest for calibrated pseudo-labels."""
    from .autonomy.calibration import AutonomyCalibrationError, load_autonomy_config
    from .autonomy.pseudo_dataset import build_weighted_pseudo_manifest

    try:
        config = load_autonomy_config(config_path)
        manifest = build_weighted_pseudo_manifest(
            lifecycle_root,
            output,
            certificate_root=certificate_root,
            revocations_root=revocations_root,
            protected_anchor_ids_path=protected_anchor_ids,
            operations_policy=config["operations"],
        )
    except (AutonomyCalibrationError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(manifest, sort_keys=True))


@autonomy.group("review-decision")
def autonomy_review_decision() -> None:
    """Record a minimal approve/reject decision over prepared evidence."""


def _record_binary_review_cli(bundle: Path, reviewer: str, ledger: Path, decision: str) -> None:
    from .autonomy.decisions import BinaryReviewError, record_binary_review_decision

    try:
        record = record_binary_review_decision(
            bundle,
            decision=decision,
            reviewer=reviewer,
            ledger_path=ledger,
        )
    except (BinaryReviewError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(record, sort_keys=True))


@autonomy_review_decision.command("approve")
@click.argument("bundle", type=click.Path(path_type=Path, dir_okay=False, exists=True))
@click.option("--reviewer", required=True)
@click.option(
    "--ledger",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("qa/autonomy/review_decisions.jsonl"),
    show_default=True,
)
def autonomy_review_decision_approve(bundle: Path, reviewer: str, ledger: Path) -> None:
    """Approve a QA-complete human-anchor seal or autonomous audit."""
    _record_binary_review_cli(bundle, reviewer, ledger, "approve")


@autonomy_review_decision.command("reject")
@click.argument("bundle", type=click.Path(path_type=Path, dir_okay=False, exists=True))
@click.option("--reviewer", required=True)
@click.option(
    "--ledger",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("qa/autonomy/review_decisions.jsonl"),
    show_default=True,
)
def autonomy_review_decision_reject(bundle: Path, reviewer: str, ledger: Path) -> None:
    """Reject prepared evidence and route bounded repair/revocation."""
    _record_binary_review_cli(bundle, reviewer, ledger, "reject")


@main.group("golden-reference")
def golden_reference() -> None:
    """Audit and normalize user-authored mask reference collections."""


@main.group("external-supervision")
def external_supervision() -> None:
    """Inspect fail-closed admission of qualified external labels."""


@external_supervision.command("admission")
@click.argument("source")
@click.option(
    "--provenance",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/maskedwarehouse_provenance.yaml"),
    show_default=True,
)
@click.option(
    "--inventory",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/maskedwarehouse_inventory.json"),
    show_default=True,
)
@click.option("--completed-gate", multiple=True)
def external_supervision_admission(
    source: str,
    provenance: Path,
    inventory: Path,
    completed_gate: tuple[str, ...],
) -> None:
    """Report legal/technical train-only admission for one warehouse source."""
    from dataclasses import asdict

    from .external_supervision import (
        ExternalSupervisionError,
        evaluate_training_admission,
        load_external_supervision_registry,
    )

    try:
        registry = load_external_supervision_registry(provenance, inventory)
        decision = evaluate_training_admission(
            registry,
            source,
            completed_gates=frozenset(completed_gate),
        )
    except (ExternalSupervisionError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(asdict(decision), sort_keys=True))


@main.group("reference-library")
def reference_library() -> None:
    """Inspect and validate the governed benchmark/retrieval library."""


@reference_library.command("status")
@click.option(
    "--database",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path(r"C:\Temp\MaskFactory_Reference_Library\reference_working.sqlite"),
    show_default=True,
)
def reference_library_status(database: Path) -> None:
    """Read index progress without walking or mutating the image library."""
    from .reference_library import inspect_reference_database

    click.echo(json.dumps(inspect_reference_database(database), sort_keys=True))


@reference_library.command("validate-selection")
@click.option(
    "--database",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    required=True,
)
@click.option(
    "--policy",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/reference_library.yaml"),
    show_default=True,
)
def reference_library_validate_selection(database: Path, policy: Path) -> None:
    """Verify selection counts, disjointness, materialization, and hashes."""
    from .reference_library import (
        ReferenceLibraryError,
        load_reference_library_policy,
        validate_reference_selection,
    )

    try:
        report = validate_reference_selection(database, load_reference_library_policy(policy))
    except (ReferenceLibraryError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(report, sort_keys=True))
    if not report["passed"]:
        raise click.ClickException("reference selection validation failed")


@reference_library.command("selection-status")
@click.option(
    "--database",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path(r"C:\Temp\MaskFactory_Reference_Library\reference_working.sqlite"),
    show_default=True,
)
@click.option(
    "--policy",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/reference_library.yaml"),
    show_default=True,
)
def reference_library_selection_status(database: Path, policy: Path) -> None:
    """Verify near-dedup and exact tier selection without materializing files."""
    from .reference_library import (
        ReferenceLibraryError,
        inspect_reference_selection,
        load_reference_library_policy,
    )

    try:
        report = inspect_reference_selection(database, load_reference_library_policy(policy))
    except (ReferenceLibraryError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(report, sort_keys=True))
    if not report["passed"]:
        raise click.ClickException("reference selection status failed")


@reference_library.command("materialize")
@click.option(
    "--database",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path(r"C:\Temp\MaskFactory_Reference_Library\reference_working.sqlite"),
    show_default=True,
)
@click.option(
    "--policy",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/reference_library.yaml"),
    show_default=True,
)
@click.option(
    "--tier", type=click.Choice(("benchmark_reference", "retrieval_reference")), required=True
)
@click.option("--max-items", type=click.IntRange(min=1), default=100, show_default=True)
def reference_library_materialize(database: Path, policy: Path, tier: str, max_items: int) -> None:
    """Copy one bounded tier chunk with source hashes and shared-F capacity gates."""
    from .reference_library import (
        ReferenceLibraryError,
        load_reference_library_policy,
        materialize_reference_tier,
    )

    try:
        report = materialize_reference_tier(
            database,
            load_reference_library_policy(policy),
            tier,
            max_items=max_items,
        )
    except (ReferenceLibraryError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(report, sort_keys=True))
    if report["issues"]:
        raise click.ClickException("reference materialization failed")
    if report["capacity_hold"]:
        raise click.exceptions.Exit(75)


@reference_library.command("validate-tier")
@click.option(
    "--database",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path(r"C:\Temp\MaskFactory_Reference_Library\reference_working.sqlite"),
    show_default=True,
)
@click.option(
    "--policy",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/reference_library.yaml"),
    show_default=True,
)
@click.option(
    "--tier", type=click.Choice(("benchmark_reference", "retrieval_reference")), required=True
)
def reference_library_validate_tier(database: Path, policy: Path, tier: str) -> None:
    """Rehash every materialized file in exactly one selected tier."""
    from .reference_library import (
        ReferenceLibraryError,
        load_reference_library_policy,
        validate_reference_materialized_tier,
    )

    try:
        report = validate_reference_materialized_tier(
            database, load_reference_library_policy(policy), tier
        )
    except (ReferenceLibraryError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(report, sort_keys=True))
    if not report["passed"]:
        raise click.ClickException("reference materialized tier validation failed")


@reference_library.command("publish-database")
@click.option(
    "--database",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path(r"C:\Temp\MaskFactory_Reference_Library\reference_working.sqlite"),
    show_default=True,
)
@click.option(
    "--output",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path(
        r"F:\Reference_Images\Ultimate_Masking_Reference_Images"
        r"\manifests\reference_library.sqlite"
    ),
    show_default=True,
)
def reference_library_publish_database(database: Path, output: Path) -> None:
    """Atomically publish a quick-checked, transactionally consistent DB snapshot."""
    from .reference_library import (
        ReferenceLibraryError,
        publish_reference_database_snapshot,
    )

    try:
        report = publish_reference_database_snapshot(database, output)
    except (ReferenceLibraryError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(report, sort_keys=True))


@reference_library.command("freeze-benchmark")
@click.option(
    "--database",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path(r"C:\Temp\MaskFactory_Reference_Library\reference_working.sqlite"),
    show_default=True,
)
@click.option(
    "--policy",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/reference_library.yaml"),
    show_default=True,
)
@click.option("--versions-root", type=click.Path(path_type=Path, file_okay=False))
def reference_library_freeze_benchmark(
    database: Path, policy: Path, versions_root: Path | None
) -> None:
    """Freeze or idempotently verify one content-addressed benchmark version."""
    from .reference_library import (
        ReferenceLibraryError,
        freeze_reference_benchmark_version,
        load_reference_library_policy,
    )

    try:
        report = freeze_reference_benchmark_version(
            database,
            load_reference_library_policy(policy),
            versions_root=versions_root,
        )
    except (ReferenceLibraryError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(report, sort_keys=True))


@reference_library.command("benchmark-drift-report")
@click.option(
    "--database",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path(r"C:\Temp\MaskFactory_Reference_Library\reference_working.sqlite"),
    show_default=True,
)
@click.option(
    "--policy",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/reference_library.yaml"),
    show_default=True,
)
@click.option(
    "--manifest",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    required=True,
)
@click.option("--output", type=click.Path(path_type=Path, dir_okay=False))
def reference_library_benchmark_drift_report(
    database: Path, policy: Path, manifest: Path, output: Path | None
) -> None:
    """Write one immutable selection/coverage drift report for a frozen benchmark."""
    from .reference_library import (
        ReferenceLibraryError,
        evaluate_reference_benchmark_drift,
        load_reference_library_policy,
        write_reference_benchmark_drift_report,
    )

    try:
        policy_document = load_reference_library_policy(policy)
        report = evaluate_reference_benchmark_drift(database, policy_document, manifest)
        if output is None:
            captured = str(report["captured_at"]).replace(":", "").replace("-", "")
            output = (
                Path(str(policy_document["output_root"]))
                / str(policy_document["versioning"]["drift_reports_directory"])
                / f"{report['version_id']}__{captured}.json"
            )
        written = write_reference_benchmark_drift_report(report, output)
    except (ReferenceLibraryError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps({**report, "output": str(written)}, sort_keys=True))
    if not report["passed"]:
        raise click.exceptions.Exit(75)


@main.group("daz")
def daz() -> None:
    """Operate the optional default-disabled DAZ synthetic lane."""


def _emit_daz_error(exc: Exception) -> None:
    from .daz import DazControlError, DazErrorCode, result_envelope

    if isinstance(exc, DazControlError):
        document = exc.as_result()
        exit_code = int(exc.code)
    else:
        document = result_envelope(code=int(DazErrorCode.CONFIG_INVALID), reason=str(exc))
        exit_code = int(DazErrorCode.CONFIG_INVALID)
    click.echo(json.dumps(document, sort_keys=True))
    raise click.exceptions.Exit(exit_code)


@daz.command("doctor")
@click.option(
    "--config-root",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path("configs/daz"),
    show_default=True,
)
def daz_doctor(config_root: Path) -> None:
    """Run the read-only foundation doctor without launching DAZ."""
    from .daz import DazPolicyError, daz_foundation_doctor, result_envelope

    try:
        report = daz_foundation_doctor(config_root)
    except (DazPolicyError, OSError, ValueError) as exc:
        _emit_daz_error(exc)
    click.echo(
        json.dumps(
            result_envelope(
                code=0 if report["passed"] else 70,
                reason="doctor_passed" if report["passed"] else "doctor_failed",
                data=report,
            ),
            sort_keys=True,
        )
    )
    if not report["passed"]:
        raise click.exceptions.Exit(70)


@daz.group("config")
def daz_config() -> None:
    """Validate the closed DAZ configuration bundle."""


@daz_config.command("validate")
@click.option(
    "--config-root",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path("configs/daz"),
    show_default=True,
)
def daz_config_validate(config_root: Path) -> None:
    from .daz import load_control_configuration, result_envelope

    try:
        configuration = load_control_configuration(config_root)
    except (OSError, ValueError) as exc:
        _emit_daz_error(exc)
    click.echo(
        json.dumps(
            result_envelope(
                reason="configuration_valid",
                data={
                    "root": str(configuration.paths.root),
                    "profile_id": configuration.operating_profile.profile_id,
                    "default_disabled": configuration.worker.default_disabled,
                    "state_database": str(configuration.paths.state_database),
                },
            ),
            sort_keys=True,
        )
    )


@daz.group("roots")
def daz_roots() -> None:
    """Plan or apply the registered F:\\DAZ directory contract."""


@daz_roots.command("init")
@click.option(
    "--config-root",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path("configs/daz"),
    show_default=True,
)
@click.option(
    "--apply", "apply_changes", is_flag=True, help="Create missing directories and control records."
)
def daz_roots_init(config_root: Path, apply_changes: bool) -> None:
    from .daz import initialize_daz_root, load_control_configuration

    try:
        configuration = load_control_configuration(config_root)
        report = initialize_daz_root(configuration.paths.root, apply=apply_changes)
    except (OSError, ValueError) as exc:
        _emit_daz_error(exc)
    click.echo(json.dumps(report, sort_keys=True))


@daz.group("paths")
def daz_paths() -> None:
    """Resolve portable paths through the registered-root authority."""


@daz_paths.command("resolve")
@click.argument("root_id")
@click.argument("relative_path", required=False, default=".")
@click.option(
    "--config-root",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path("configs/daz"),
    show_default=True,
)
def daz_paths_resolve(root_id: str, relative_path: str, config_root: Path) -> None:
    from .daz import RegisteredRootResolver, load_control_configuration, result_envelope

    try:
        configuration = load_control_configuration(config_root)
        registry = configuration.paths.root / "00_control" / "path_registry.json"
        resolved = RegisteredRootResolver.load(registry).resolve(root_id, relative_path)
    except (OSError, ValueError) as exc:
        _emit_daz_error(exc)
    click.echo(
        json.dumps(
            result_envelope(
                reason="path_resolved",
                entity_ids=(root_id,),
                data={"relative_path": relative_path, "resolved_path": str(resolved)},
            ),
            sort_keys=True,
        )
    )


@daz.group("state")
def daz_state() -> None:
    """Initialize and verify the dedicated WAL state database."""


@daz_state.command("init")
@click.option(
    "--config-root",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path("configs/daz"),
    show_default=True,
)
@click.option("--apply", "apply_changes", is_flag=True, help="Create or migrate the database.")
def daz_state_init(config_root: Path, apply_changes: bool) -> None:
    from .daz import initialize_state_database, load_control_configuration, result_envelope

    try:
        configuration = load_control_configuration(config_root)
        path = configuration.paths.state_database
        report = (
            initialize_state_database(path)
            if apply_changes
            else result_envelope(
                reason="state_database_initialization_plan",
                evidence_paths=(str(path),),
                data={"apply": False, "exists": path.is_file(), "target_schema_version": 2},
            )
        )
    except (OSError, ValueError) as exc:
        _emit_daz_error(exc)
    click.echo(json.dumps(report, sort_keys=True))


@daz_state.command("integrity")
@click.option(
    "--config-root",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path("configs/daz"),
    show_default=True,
)
def daz_state_integrity(config_root: Path) -> None:
    from .daz import inspect_state_database, load_control_configuration, result_envelope

    try:
        configuration = load_control_configuration(config_root)
        report = inspect_state_database(configuration.paths.state_database)
    except (OSError, ValueError) as exc:
        _emit_daz_error(exc)
    click.echo(
        json.dumps(
            result_envelope(
                code=0 if report["passed"] else 73,
                reason="state_integrity_passed" if report["passed"] else "state_integrity_failed",
                evidence_paths=(str(configuration.paths.state_database),),
                data=report,
            ),
            sort_keys=True,
        )
    )
    if not report["passed"]:
        raise click.exceptions.Exit(73)


@daz.group("control")
def daz_control() -> None:
    """Read or atomically change the local DAZ enable/drain state."""


@daz.group("assets")
def daz_assets() -> None:
    """Build offline, privacy-safe DAZ asset-lineage observations."""


@daz.group("recipes")
def daz_recipes() -> None:
    """Seal and verify canonical fully resolved DAZ scene recipes."""


@daz_assets.command("dim-scan")
@click.option(
    "--source",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path(r"C:\Users\Public\Documents\DAZ 3D\InstallManager\ManifestFiles"),
    show_default=True,
)
@click.option("--output", type=click.Path(path_type=Path, file_okay=False))
def daz_assets_dim_scan(source: Path, output: Path | None) -> None:
    """Parse DIM DSX manifests without DAZ, CMS, login, or network access."""
    from .daz import DazErrorCode, result_envelope
    from .daz.assets import DimManifestError, publish_dim_snapshot, scan_dim_manifest_archive

    try:
        report = scan_dim_manifest_archive(source)
        publication = publish_dim_snapshot(report, output) if output is not None else None
    except (DimManifestError, OSError, ValueError) as exc:
        reason = exc.reason if isinstance(exc, DimManifestError) else str(exc)
        click.echo(
            json.dumps(
                result_envelope(code=int(DazErrorCode.DIM_MANIFEST_INVALID), reason=reason),
                sort_keys=True,
            )
        )
        raise click.exceptions.Exit(int(DazErrorCode.DIM_MANIFEST_INVALID))
    click.echo(
        json.dumps(
            result_envelope(
                reason="dim_manifest_scan_complete",
                entity_ids=(report["snapshot_id"],),
                data={"snapshot": report, "publication": publication},
            ),
            sort_keys=True,
        )
    )


@daz_assets.command("dim-config")
@click.option(
    "--account-settings",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path(r"C:\Users\kevin\AppData\Roaming\DAZ 3D\InstallManager\UserAccounts\Account.ini"),
    show_default=True,
)
@click.option("--apply", "apply_changes", is_flag=True)
def daz_assets_dim_config(account_settings: Path, apply_changes: bool) -> None:
    """Plan/apply governed DIM paths while preserving credential fields byte-for-byte."""
    from .daz import DazErrorCode, result_envelope
    from .daz.assets import DimManifestError, configure_dim_paths

    try:
        report = configure_dim_paths(account_settings, apply=apply_changes)
    except (DimManifestError, OSError, ValueError) as exc:
        reason = exc.reason if isinstance(exc, DimManifestError) else str(exc)
        click.echo(
            json.dumps(
                result_envelope(code=int(DazErrorCode.DIM_CONFIGURATION_INVALID), reason=reason),
                sort_keys=True,
            )
        )
        raise click.exceptions.Exit(int(DazErrorCode.DIM_CONFIGURATION_INVALID))
    click.echo(
        json.dumps(
            result_envelope(
                reason=(
                    "dim_configuration_applied" if report["applied"] else "dim_configuration_plan"
                ),
                data=report,
            ),
            sort_keys=True,
        )
    )


def _daz_content_roots(root_specs: tuple[str, ...]):
    from .daz.assets import ContentRoot

    specs = root_specs or (
        r"content_primary=F:\DAZ\03_content\libraries\MaskFactory_DAZ_Library",
        r"content_user=F:\DAZ\03_content\libraries\MaskFactory_User_Library",
        r"legacy_dim=C:\Users\Public\Documents\My DAZ 3D Library",
    )
    roots = []
    for priority, spec in enumerate(specs, start=1):
        root_id, separator, raw_path = spec.partition("=")
        if separator != "=" or not root_id or not raw_path:
            raise ValueError("content root must use ROOT_ID=PATH")
        source_kind = "legacy_dim" if root_id == "legacy_dim" else "governed"
        roots.append(ContentRoot(root_id, Path(raw_path), priority * 10, source_kind))
    return tuple(roots)


@daz_assets.command("filesystem-scan")
@click.option("--root", "root_specs", multiple=True, help="Repeat ROOT_ID=PATH.")
@click.option(
    "--state",
    "state_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path(r"F:\DAZ\05_registry\rebuild_evidence\filesystem_inventory.sqlite"),
    show_default=True,
)
@click.option("--max-entries", type=click.IntRange(min=1), default=50_000, show_default=True)
@click.option("--max-seconds", type=click.FloatRange(min=0.1), default=30.0, show_default=True)
@click.option("--reset", is_flag=True, help="Start a new scan state for the exact root set.")
@click.option(
    "--finalize", is_flag=True, help="Publish portable JSON only if the scan is complete."
)
@click.option(
    "--output",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path(r"F:\DAZ\05_registry\snapshots\filesystem"),
    show_default=True,
)
def daz_assets_filesystem_scan(
    root_specs: tuple[str, ...],
    state_path: Path,
    max_entries: int,
    max_seconds: float,
    reset: bool,
    finalize: bool,
    output: Path,
) -> None:
    """Resume a bounded content scan without following symlinks or junctions."""
    from .daz import DazErrorCode, result_envelope
    from .daz.assets import (
        FilesystemInventoryError,
        build_inventory_snapshot,
        initialize_inventory_state,
        inventory_state_summary,
        publish_inventory_snapshot,
        scan_inventory_chunk,
    )

    try:
        roots = _daz_content_roots(root_specs)
        initialize_inventory_state(state_path, roots, reset=reset)
        chunk = scan_inventory_chunk(
            state_path, roots, max_entries=max_entries, max_seconds=max_seconds
        )
        summary = inventory_state_summary(state_path)
        publication = None
        if finalize:
            snapshot = build_inventory_snapshot(state_path, roots=roots)
            target, published = publish_inventory_snapshot(snapshot, output)
            publication = {"path": str(target), "published": published}
    except (FilesystemInventoryError, OSError, ValueError) as exc:
        reason = exc.reason if isinstance(exc, FilesystemInventoryError) else str(exc)
        click.echo(
            json.dumps(
                result_envelope(code=int(DazErrorCode.FILESYSTEM_INVENTORY_INVALID), reason=reason),
                sort_keys=True,
            )
        )
        raise click.exceptions.Exit(int(DazErrorCode.FILESYSTEM_INVENTORY_INVALID))
    click.echo(
        json.dumps(
            result_envelope(
                reason="filesystem_inventory_chunk_complete",
                data={
                    "chunk": {
                        "scanned_directories": chunk.scanned_directories,
                        "observed_entries": chunk.observed_entries,
                        "file_count": chunk.file_count,
                        "skipped_reparse_points": chunk.skipped_reparse_points,
                    },
                    "summary": summary,
                    "state_path": str(state_path),
                    "publication": publication,
                },
            ),
            sort_keys=True,
        )
    )


@daz_assets.command("identity-index")
@click.option("--root", "root_specs", multiple=True, help="Repeat ROOT_ID=PATH.")
@click.option(
    "--inventory-state",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path(r"F:\DAZ\05_registry\rebuild_evidence\filesystem_inventory.sqlite"),
    show_default=True,
)
@click.option(
    "--state",
    "identity_state",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path(r"F:\DAZ\05_registry\rebuild_evidence\asset_identity.sqlite"),
    show_default=True,
)
@click.option("--max-files", type=click.IntRange(min=1), default=100, show_default=True)
@click.option("--max-bytes", type=click.IntRange(min=1), default=2 * 1024**3, show_default=True)
@click.option("--max-seconds", type=click.FloatRange(min=0.1), default=30.0, show_default=True)
@click.option("--reset", is_flag=True, help="Start a new hash state for the exact root set.")
@click.option(
    "--finalize", is_flag=True, help="Publish only after inventory and hashes are complete."
)
@click.option(
    "--output",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path(r"F:\DAZ\05_registry\snapshots\asset_identity"),
    show_default=True,
)
@click.option(
    "--previous",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    help="Optional prior immutable identity snapshot to diff at finalization.",
)
def daz_assets_identity_index(
    root_specs: tuple[str, ...],
    inventory_state: Path,
    identity_state: Path,
    max_files: int,
    max_bytes: int,
    max_seconds: float,
    reset: bool,
    finalize: bool,
    output: Path,
    previous: Path | None,
) -> None:
    """Incrementally hash files and make duplicate/shadow conflicts explicit."""
    from .daz import DazErrorCode, result_envelope
    from .daz.assets import (
        AssetIdentityError,
        asset_identity_state_summary,
        build_asset_identity_snapshot,
        diff_asset_identity_snapshots,
        publish_asset_identity_snapshot,
        resume_asset_identity_index,
    )

    try:
        roots = _daz_content_roots(root_specs)
        chunk = resume_asset_identity_index(
            inventory_state,
            identity_state,
            roots,
            max_files=max_files,
            max_bytes=max_bytes,
            max_seconds=max_seconds,
            reset=reset,
        )
        summary = asset_identity_state_summary(identity_state)
        publication = None
        difference = None
        if finalize:
            snapshot = build_asset_identity_snapshot(inventory_state, identity_state, roots)
            target, published = publish_asset_identity_snapshot(snapshot, output)
            publication = {
                "path": str(target),
                "published": published,
                "snapshot_id": snapshot["snapshot_id"],
                "summary": snapshot["summary"],
            }
            if previous is not None:
                prior = json.loads(previous.read_text(encoding="utf-8"))
                difference = diff_asset_identity_snapshots(prior, snapshot)
    except (AssetIdentityError, OSError, ValueError) as exc:
        reason = exc.reason if isinstance(exc, AssetIdentityError) else str(exc)
        click.echo(
            json.dumps(
                result_envelope(code=int(DazErrorCode.ASSET_IDENTITY_INVALID), reason=reason),
                sort_keys=True,
            )
        )
        raise click.exceptions.Exit(int(DazErrorCode.ASSET_IDENTITY_INVALID))
    click.echo(
        json.dumps(
            result_envelope(
                reason=(
                    "asset_identity_index_complete"
                    if chunk.complete
                    else "asset_identity_index_partial"
                ),
                data={
                    "chunk": chunk.as_dict(),
                    "summary": summary,
                    "state_path": str(identity_state),
                    "publication": publication,
                    "difference": difference,
                },
            ),
            sort_keys=True,
        )
    )


@daz_assets.command("catalog-graph")
@click.option(
    "--records",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    required=True,
    help="JSON array, or object with an assets array, of normalized static records.",
)
@click.option(
    "--vocabularies",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/daz/asset_vocabularies.yaml"),
    show_default=True,
)
@click.option(
    "--authoritative-vocabularies",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("Plan/Daz/Asset_Manifest/vocabularies/controlled_vocabularies.yaml"),
    show_default=True,
)
@click.option(
    "--plugins",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    help="Optional JSON object keyed by plugin ID.",
)
@click.option(
    "--output",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path(r"F:\DAZ\05_registry\snapshots\asset_catalog"),
    show_default=True,
)
def daz_assets_catalog_graph(
    records: Path,
    vocabularies: Path,
    authoritative_vocabularies: Path,
    plugins: Path | None,
    output: Path,
) -> None:
    """Validate closed taxonomy and publish a static compatibility graph."""
    from .daz import DazErrorCode, result_envelope
    from .daz.assets import (
        AssetCatalogError,
        build_asset_compatibility_graph,
        load_asset_vocabularies,
        publish_asset_compatibility_graph,
    )

    try:
        document = json.loads(records.read_text(encoding="utf-8"))
        assets = document.get("assets") if isinstance(document, dict) else document
        if not isinstance(assets, list):
            raise AssetCatalogError("catalog_records_invalid", "records must contain an asset list")
        plugin_document = (
            json.loads(plugins.read_text(encoding="utf-8")) if plugins is not None else {}
        )
        if not isinstance(plugin_document, dict):
            raise AssetCatalogError("catalog_plugins_invalid", "plugins must be a JSON object")
        vocabulary_document = load_asset_vocabularies(
            vocabularies, authoritative_source=authoritative_vocabularies
        )
        graph = build_asset_compatibility_graph(
            assets, vocabulary_document, plugins=plugin_document
        )
        target, published = publish_asset_compatibility_graph(graph, output)
    except (AssetCatalogError, json.JSONDecodeError, OSError, ValueError) as exc:
        reason = exc.reason if isinstance(exc, AssetCatalogError) else str(exc)
        click.echo(
            json.dumps(
                result_envelope(code=int(DazErrorCode.ASSET_CATALOG_INVALID), reason=reason),
                sort_keys=True,
            )
        )
        raise click.exceptions.Exit(int(DazErrorCode.ASSET_CATALOG_INVALID))
    click.echo(
        json.dumps(
            result_envelope(
                reason="asset_catalog_graph_complete",
                entity_ids=(graph["graph_id"],),
                evidence_paths=(str(target),),
                data={
                    "summary": graph["summary"],
                    "graph_sha256": graph["graph_sha256"],
                    "publication": {"path": str(target), "published": published},
                },
            ),
            sort_keys=True,
        )
    )


@daz_assets.command("pool-report")
@click.option(
    "--graph",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    required=True,
)
@click.option(
    "--policy",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/daz/asset_pools.yaml"),
    show_default=True,
)
@click.option(
    "--vocabularies",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/daz/asset_vocabularies.yaml"),
    show_default=True,
)
@click.option(
    "--output",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path(r"F:\DAZ\05_registry\snapshots\asset_pools"),
    show_default=True,
)
def daz_assets_pool_report(graph: Path, policy: Path, vocabularies: Path, output: Path) -> None:
    """Build immutable queryable pools without copying source assets."""
    from .daz import DazErrorCode, result_envelope
    from .daz.assets import (
        AssetPoolError,
        build_asset_pool_report,
        load_asset_pool_policy,
        load_asset_vocabularies,
        publish_asset_pool_report,
    )

    try:
        graph_document = json.loads(graph.read_text(encoding="utf-8"))
        vocabulary_document = load_asset_vocabularies(vocabularies)
        policy_document = load_asset_pool_policy(policy, vocabulary_document)
        report = build_asset_pool_report(graph_document, policy_document, vocabulary_document)
        target, published = publish_asset_pool_report(report, output)
    except (AssetPoolError, json.JSONDecodeError, OSError, ValueError) as exc:
        reason = exc.reason if isinstance(exc, AssetPoolError) else str(exc)
        click.echo(
            json.dumps(
                result_envelope(code=int(DazErrorCode.ASSET_POOL_INVALID), reason=reason),
                sort_keys=True,
            )
        )
        raise click.exceptions.Exit(int(DazErrorCode.ASSET_POOL_INVALID))
    click.echo(
        json.dumps(
            result_envelope(
                reason="asset_pool_report_complete",
                entity_ids=(report["report_id"],),
                evidence_paths=(str(target),),
                data={
                    "summary": report["summary"],
                    "report_sha256": report["report_sha256"],
                    "publication": {"path": str(target), "published": published},
                },
            ),
            sort_keys=True,
        )
    )


@daz_assets.command("smoke-plan")
@click.option(
    "--graph", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True
)
@click.option("--asset-id", required=True)
@click.option("--created-at", required=True, help="UTC RFC 3339 timestamp.")
@click.option("--bundle-version", required=True)
@click.option("--runtime-snapshot-sha256", required=True)
@click.option("--script-bundle-sha256", required=True)
@click.option(
    "--content-directory",
    "content_directories",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    multiple=True,
    required=True,
    help="Repeat exactly twice for governed primary and user libraries.",
)
@click.option("--mapping-bundle-id")
@click.option("--mapping-bundle-sha256")
@click.option(
    "--policy",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/daz/asset_smoke.yaml"),
    show_default=True,
)
@click.option(
    "--vocabularies",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/daz/asset_vocabularies.yaml"),
    show_default=True,
)
@click.option(
    "--output",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path(r"F:\DAZ\05_registry\smoke\plans"),
    show_default=True,
)
def daz_assets_smoke_plan(
    graph: Path,
    asset_id: str,
    created_at: str,
    bundle_version: str,
    runtime_snapshot_sha256: str,
    script_bundle_sha256: str,
    content_directories: tuple[Path, ...],
    mapping_bundle_id: str | None,
    mapping_bundle_sha256: str | None,
    policy: Path,
    vocabularies: Path,
    output: Path,
) -> None:
    """Build two hash-bound, clean-process smoke recipes for one asset."""
    from .daz import DazErrorCode, result_envelope
    from .daz.assets import (
        AssetSmokeError,
        build_asset_smoke_plan,
        load_asset_smoke_policy,
        load_asset_vocabularies,
        publish_asset_smoke_document,
    )

    try:
        if len(content_directories) != 2:
            raise AssetSmokeError(
                "smoke_content_directories_invalid", "exactly two directories required"
            )
        graph_document = json.loads(graph.read_text(encoding="utf-8"))
        vocabulary_document = load_asset_vocabularies(vocabularies)
        policy_document = load_asset_smoke_policy(
            policy, asset_classes=vocabulary_document["primary_asset_classes"]
        )
        plan = build_asset_smoke_plan(
            graph_document,
            policy_document,
            asset_id=asset_id,
            created_at=created_at,
            bundle_version=bundle_version,
            runtime_snapshot_sha256=runtime_snapshot_sha256,
            script_bundle_sha256=script_bundle_sha256,
            content_directories=(content_directories[0], content_directories[1]),
            mapping_bundle_id=mapping_bundle_id,
            mapping_bundle_sha256=mapping_bundle_sha256,
        )
        target, published = publish_asset_smoke_document(plan, output, document_id=plan["plan_id"])
    except (AssetSmokeError, json.JSONDecodeError, OSError, ValueError) as exc:
        reason = exc.reason if isinstance(exc, AssetSmokeError) else str(exc)
        click.echo(
            json.dumps(
                result_envelope(code=int(DazErrorCode.ASSET_SMOKE_INVALID), reason=reason),
                sort_keys=True,
            )
        )
        raise click.exceptions.Exit(int(DazErrorCode.ASSET_SMOKE_INVALID))
    click.echo(
        json.dumps(
            result_envelope(
                reason="asset_smoke_plan_complete",
                entity_ids=(plan["plan_id"], asset_id),
                evidence_paths=(str(target),),
                data={
                    "plan_sha256": plan["plan_sha256"],
                    "recipe_ids": [recipe["recipe_id"] for recipe in plan["recipes"]],
                    "publication": {"path": str(target), "published": published},
                },
            ),
            sort_keys=True,
        )
    )


@daz_assets.command("smoke-evaluate")
@click.option("--plan", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True)
@click.option(
    "--result", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True
)
@click.option(
    "--policy",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/daz/asset_smoke.yaml"),
    show_default=True,
)
@click.option(
    "--vocabularies",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/daz/asset_vocabularies.yaml"),
    show_default=True,
)
@click.option(
    "--output",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path(r"F:\DAZ\05_registry\smoke\evaluations"),
    show_default=True,
)
def daz_assets_smoke_evaluate(
    plan: Path, result: Path, policy: Path, vocabularies: Path, output: Path
) -> None:
    """Evaluate bindings, artifacts, checks, and two-process repeatability."""
    from .daz import DazErrorCode, result_envelope
    from .daz.assets import (
        AssetSmokeError,
        evaluate_asset_smoke_result,
        load_asset_smoke_policy,
        load_asset_vocabularies,
        publish_asset_smoke_document,
    )

    try:
        plan_document = json.loads(plan.read_text(encoding="utf-8"))
        result_document = json.loads(result.read_text(encoding="utf-8"))
        vocabulary_document = load_asset_vocabularies(vocabularies)
        policy_document = load_asset_smoke_policy(
            policy, asset_classes=vocabulary_document["primary_asset_classes"]
        )
        evaluation = evaluate_asset_smoke_result(plan_document, result_document, policy_document)
        evaluation_id = f"dsme_{evaluation['evaluation_sha256'][:24]}"
        target, published = publish_asset_smoke_document(
            evaluation, output, document_id=evaluation_id
        )
    except (AssetSmokeError, json.JSONDecodeError, OSError, ValueError) as exc:
        reason = exc.reason if isinstance(exc, AssetSmokeError) else str(exc)
        click.echo(
            json.dumps(
                result_envelope(code=int(DazErrorCode.ASSET_SMOKE_INVALID), reason=reason),
                sort_keys=True,
            )
        )
        raise click.exceptions.Exit(int(DazErrorCode.ASSET_SMOKE_INVALID))
    click.echo(
        json.dumps(
            result_envelope(
                code=0 if evaluation["passed"] else int(DazErrorCode.ASSET_SMOKE_INVALID),
                reason=("asset_smoke_passed" if evaluation["passed"] else "asset_smoke_failed"),
                entity_ids=(evaluation_id, evaluation["plan_id"]),
                evidence_paths=(str(target),),
                data={
                    "evaluation": evaluation,
                    "publication": {"path": str(target), "published": published},
                },
            ),
            sort_keys=True,
        )
    )
    if not evaluation["passed"]:
        raise click.exceptions.Exit(int(DazErrorCode.ASSET_SMOKE_INVALID))


@daz_assets.command("smoke-certify")
@click.option("--plan", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True)
@click.option(
    "--result", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True
)
@click.option(
    "--evaluation", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True
)
@click.option(
    "--graph", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True
)
@click.option("--created-at", required=True, help="UTC RFC 3339 timestamp.")
@click.option("--limitation", "limitations", multiple=True)
@click.option(
    "--output",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path(r"F:\DAZ\08_asset_tests\certificates"),
    show_default=True,
)
def daz_assets_smoke_certify(
    plan: Path,
    result: Path,
    evaluation: Path,
    graph: Path,
    created_at: str,
    limitations: tuple[str, ...],
    output: Path,
) -> None:
    """Issue an immutable certificate only for exact passing smoke evidence."""
    from .daz import DazErrorCode, result_envelope
    from .daz.assets import (
        AssetQualificationError,
        AssetSmokeError,
        issue_asset_smoke_certificate,
        publish_asset_smoke_document,
    )

    try:
        certificate = issue_asset_smoke_certificate(
            json.loads(plan.read_text(encoding="utf-8")),
            json.loads(result.read_text(encoding="utf-8")),
            json.loads(evaluation.read_text(encoding="utf-8")),
            json.loads(graph.read_text(encoding="utf-8")),
            created_at=created_at,
            limitations=limitations,
        )
        target, published = publish_asset_smoke_document(
            certificate, output, document_id=certificate["certificate_id"]
        )
    except (
        AssetQualificationError,
        AssetSmokeError,
        json.JSONDecodeError,
        OSError,
        ValueError,
    ) as exc:
        reason = getattr(exc, "reason", str(exc))
        click.echo(
            json.dumps(
                result_envelope(code=int(DazErrorCode.ASSET_SMOKE_INVALID), reason=reason),
                sort_keys=True,
            )
        )
        raise click.exceptions.Exit(int(DazErrorCode.ASSET_SMOKE_INVALID))
    click.echo(
        json.dumps(
            result_envelope(
                reason="asset_smoke_certificate_issued",
                entity_ids=(certificate["certificate_id"], certificate["asset_id"]),
                evidence_paths=(str(target),),
                data={
                    "certificate_sha256": certificate["certificate_sha256"],
                    "publication": {"path": str(target), "published": published},
                },
            ),
            sort_keys=True,
        )
    )


@daz_assets.command("smoke-quarantine")
@click.option("--plan", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True)
@click.option(
    "--result", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True
)
@click.option(
    "--evaluation", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True
)
@click.option("--observed-at", required=True, help="UTC RFC 3339 timestamp.")
@click.option("--log-excerpt-sha256", required=True)
@click.option("--retry-count", type=click.IntRange(min=0), default=0, show_default=True)
@click.option(
    "--output",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path(r"F:\DAZ\08_asset_tests\quarantine"),
    show_default=True,
)
def daz_assets_smoke_quarantine(
    plan: Path,
    result: Path,
    evaluation: Path,
    observed_at: str,
    log_excerpt_sha256: str,
    retry_count: int,
    output: Path,
) -> None:
    """Seal failed smoke evidence into a reason-coded quarantine record."""
    from .daz import DazErrorCode, result_envelope
    from .daz.assets import (
        AssetQualificationError,
        AssetSmokeError,
        build_asset_quarantine_record,
        publish_asset_smoke_document,
    )

    try:
        quarantine = build_asset_quarantine_record(
            json.loads(plan.read_text(encoding="utf-8")),
            json.loads(result.read_text(encoding="utf-8")),
            json.loads(evaluation.read_text(encoding="utf-8")),
            observed_at=observed_at,
            log_excerpt_sha256=log_excerpt_sha256,
            retry_count=retry_count,
        )
        target, published = publish_asset_smoke_document(
            quarantine, output, document_id=quarantine["quarantine_id"]
        )
    except (
        AssetQualificationError,
        AssetSmokeError,
        json.JSONDecodeError,
        OSError,
        ValueError,
    ) as exc:
        reason = getattr(exc, "reason", str(exc))
        click.echo(
            json.dumps(
                result_envelope(code=int(DazErrorCode.ASSET_SMOKE_INVALID), reason=reason),
                sort_keys=True,
            )
        )
        raise click.exceptions.Exit(int(DazErrorCode.ASSET_SMOKE_INVALID))
    click.echo(
        json.dumps(
            result_envelope(
                reason="asset_smoke_quarantine_created",
                entity_ids=(quarantine["quarantine_id"], quarantine["asset_id"]),
                evidence_paths=(str(target),),
                data={
                    "quarantine_codes": quarantine["quarantine_codes"],
                    "publication": {"path": str(target), "published": published},
                },
            ),
            sort_keys=True,
        )
    )


@daz_assets.command("qualification-impact")
@click.option(
    "--graph", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True
)
@click.option(
    "--certificates", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True
)
@click.option(
    "--queued-recipes", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True
)
@click.option("--changed-asset-id", "changed_asset_ids", multiple=True)
@click.option("--changed-plugin-id", "changed_plugin_ids", multiple=True)
@click.option("--runtime-snapshot-sha256", required=True)
@click.option("--script-bundle-sha256", required=True)
@click.option(
    "--mapping-bundle-hashes",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    help="Optional JSON object mapping bundle IDs to current SHA-256 values.",
)
@click.option(
    "--output",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path(r"F:\DAZ\08_asset_tests\retest"),
    show_default=True,
)
def daz_assets_qualification_impact(
    graph: Path,
    certificates: Path,
    queued_recipes: Path,
    changed_asset_ids: tuple[str, ...],
    changed_plugin_ids: tuple[str, ...],
    runtime_snapshot_sha256: str,
    script_bundle_sha256: str,
    mapping_bundle_hashes: Path | None,
    output: Path,
) -> None:
    """Propagate asset/plugin/input changes into certificate and queue revocations."""
    from .daz import DazErrorCode, result_envelope
    from .daz.assets import (
        AssetQualificationError,
        AssetSmokeError,
        build_asset_change_impact,
        publish_asset_smoke_document,
    )

    try:
        certificate_documents = json.loads(certificates.read_text(encoding="utf-8"))
        queued_documents = json.loads(queued_recipes.read_text(encoding="utf-8"))
        mapping_hashes = (
            json.loads(mapping_bundle_hashes.read_text(encoding="utf-8"))
            if mapping_bundle_hashes is not None
            else {}
        )
        if not isinstance(certificate_documents, list) or not isinstance(queued_documents, list):
            raise AssetQualificationError(
                "qualification_impact_input_invalid", "certificates and recipes must be arrays"
            )
        if not isinstance(mapping_hashes, dict):
            raise AssetQualificationError(
                "qualification_impact_input_invalid", "mapping hashes must be an object"
            )
        impact = build_asset_change_impact(
            json.loads(graph.read_text(encoding="utf-8")),
            certificate_documents,
            queued_documents,
            changed_asset_ids=changed_asset_ids,
            changed_plugin_ids=changed_plugin_ids,
            runtime_snapshot_sha256=runtime_snapshot_sha256,
            script_bundle_sha256=script_bundle_sha256,
            mapping_bundle_hashes=mapping_hashes,
        )
        impact_id = f"dazi_{impact['impact_sha256'][:24]}"
        target, published = publish_asset_smoke_document(impact, output, document_id=impact_id)
    except (
        AssetQualificationError,
        AssetSmokeError,
        json.JSONDecodeError,
        OSError,
        ValueError,
    ) as exc:
        reason = getattr(exc, "reason", str(exc))
        click.echo(
            json.dumps(
                result_envelope(code=int(DazErrorCode.ASSET_SMOKE_INVALID), reason=reason),
                sort_keys=True,
            )
        )
        raise click.exceptions.Exit(int(DazErrorCode.ASSET_SMOKE_INVALID))
    click.echo(
        json.dumps(
            result_envelope(
                reason="asset_qualification_change_propagated",
                entity_ids=(impact_id,),
                evidence_paths=(str(target),),
                data={
                    "impact": impact,
                    "publication": {"path": str(target), "published": published},
                },
            ),
            sort_keys=True,
        )
    )


@daz_recipes.command("seal")
@click.argument("draft", type=click.Path(path_type=Path, dir_okay=False, exists=True))
@click.option(
    "--output",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path(r"F:\DAZ\09_generation\scene_recipes"),
    show_default=True,
)
def daz_recipes_seal(draft: Path, output: Path) -> None:
    """Derive named streams, validate, hash, and immutably publish a resolved recipe."""
    from .daz import DazErrorCode, result_envelope
    from .daz.scenes import (
        SceneRecipeError,
        publish_resolved_scene_recipe,
        seal_resolved_scene_recipe,
    )

    try:
        document = json.loads(draft.read_text(encoding="utf-8"))
        sealed = seal_resolved_scene_recipe(document)
        target, published = publish_resolved_scene_recipe(sealed, output)
    except (SceneRecipeError, json.JSONDecodeError, OSError, ValueError) as exc:
        reason = exc.reason if isinstance(exc, SceneRecipeError) else str(exc)
        click.echo(
            json.dumps(
                result_envelope(code=int(DazErrorCode.SCENE_RECIPE_INVALID), reason=reason),
                sort_keys=True,
            )
        )
        raise click.exceptions.Exit(int(DazErrorCode.SCENE_RECIPE_INVALID))
    click.echo(
        json.dumps(
            result_envelope(
                reason="daz_scene_recipe_sealed",
                entity_ids=(sealed["scene_id"], sealed["scene_family_id"]),
                evidence_paths=(str(target),),
                data={
                    "recipe_sha256": sealed["recipe_sha256"],
                    "publication": {"path": str(target), "published": published},
                },
            ),
            sort_keys=True,
        )
    )


@daz_recipes.command("validate")
@click.argument("recipe", type=click.Path(path_type=Path, dir_okay=False, exists=True))
def daz_recipes_validate(recipe: Path) -> None:
    """Verify schema, invariants, named streams, and canonical recipe SHA-256."""
    from .daz import DazErrorCode, result_envelope
    from .daz.scenes import SceneRecipeError, validate_resolved_scene_recipe

    try:
        report = validate_resolved_scene_recipe(json.loads(recipe.read_text(encoding="utf-8")))
    except (SceneRecipeError, json.JSONDecodeError, OSError, ValueError) as exc:
        reason = exc.reason if isinstance(exc, SceneRecipeError) else str(exc)
        click.echo(
            json.dumps(
                result_envelope(code=int(DazErrorCode.SCENE_RECIPE_INVALID), reason=reason),
                sort_keys=True,
            )
        )
        raise click.exceptions.Exit(int(DazErrorCode.SCENE_RECIPE_INVALID))
    click.echo(
        json.dumps(
            result_envelope(
                reason="daz_scene_recipe_valid",
                entity_ids=(report["scene_id"], report["scene_family_id"]),
                evidence_paths=(str(recipe),),
                data=report,
            ),
            sort_keys=True,
        )
    )


@daz_assets.command("acquisition-index")
@click.option(
    "--source",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path(r"F:\DAZ\05_registry\manifests\assets"),
    show_default=True,
)
@click.option(
    "--output",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path(r"F:\DAZ\05_registry\live\autonomous_acquisition.sqlite"),
    show_default=True,
)
@click.option(
    "--inventory-state",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path(r"F:\DAZ\05_registry\rebuild_evidence\filesystem_inventory.sqlite"),
    show_default=True,
)
@click.option("--max-manifests", type=click.IntRange(min=1), default=25, show_default=True)
@click.option("--reset", is_flag=True, help="Start a new resumable index for the live source set.")
@click.option(
    "--revision-archive",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path(r"F:\DAZ\01_source_records\install_manifests\autonomous"),
    show_default=True,
)
def daz_assets_acquisition_index(
    source: Path,
    output: Path,
    inventory_state: Path,
    max_manifests: int,
    reset: bool,
    revision_archive: Path,
) -> None:
    """Index autonomous-downloader manifests as a source independent of DIM."""
    from .daz import DazErrorCode, result_envelope
    from .daz.assets import (
        AcquisitionManifestError,
        inventory_state_summary,
        reconcile_acquisition_with_inventory,
        resume_acquisition_manifest_index,
    )

    try:
        progress = resume_acquisition_manifest_index(
            source,
            output,
            max_manifests=max_manifests,
            reset=reset,
            revision_archive_root=revision_archive,
        )
        inventory_summary = (
            inventory_state_summary(inventory_state) if inventory_state.is_file() else None
        )
        if progress.complete and inventory_summary and inventory_summary["complete"]:
            comparison = reconcile_acquisition_with_inventory(output, inventory_state)
        else:
            comparison = {
                "authoritative": False,
                "reason_code": "source_or_inventory_incomplete",
                "acquisition_complete": progress.complete,
                "inventory_complete": bool(inventory_summary and inventory_summary["complete"]),
            }
    except (AcquisitionManifestError, OSError, ValueError) as exc:
        reason = exc.reason if isinstance(exc, AcquisitionManifestError) else str(exc)
        click.echo(
            json.dumps(
                result_envelope(code=int(DazErrorCode.ACQUISITION_MANIFEST_INVALID), reason=reason),
                sort_keys=True,
            )
        )
        raise click.exceptions.Exit(int(DazErrorCode.ACQUISITION_MANIFEST_INVALID))
    click.echo(
        json.dumps(
            result_envelope(
                reason=(
                    "autonomous_acquisition_index_complete"
                    if progress.complete
                    else "autonomous_acquisition_index_partial"
                ),
                data={"progress": progress.as_dict(), "filesystem_comparison": comparison},
            ),
            sort_keys=True,
        )
    )


@daz_assets.command("cms-scan")
@click.option("--root", "root_specs", multiple=True, help="Repeat ROOT_ID=PATH.")
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path(r"C:\Users\kevin\AppData\Roaming\DAZ 3D\cms\cmscfg.json"),
    show_default=True,
)
@click.option(
    "--psql",
    "psql_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path(r"C:\Program Files\DAZ 3D\PostgreSQL CMS\bin\psql.exe"),
    show_default=True,
)
@click.option(
    "--inventory-state",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path(r"F:\DAZ\05_registry\rebuild_evidence\filesystem_inventory.sqlite"),
    show_default=True,
)
@click.option("--offline", is_flag=True, help="Force the declared filesystem-only fallback.")
@click.option(
    "--output",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path(r"F:\DAZ\05_registry\snapshots\cms"),
    show_default=True,
)
def daz_assets_cms_scan(
    root_specs: tuple[str, ...],
    config_path: Path,
    psql_path: Path,
    inventory_state: Path,
    offline: bool,
    output: Path,
) -> None:
    """Query local CMS read-only and fall back explicitly to filesystem authority."""
    from .daz import DazErrorCode, result_envelope
    from .daz.assets import (
        CmsObservationError,
        build_offline_cms_fallback,
        compare_cms_with_inventory,
        publish_cms_snapshot,
        query_cms_snapshot,
    )

    try:
        roots = _daz_content_roots(root_specs)
        online_failure = None
        if offline:
            snapshot = build_offline_cms_fallback(
                registered_roots=roots,
                inventory_state=inventory_state,
                failure_reason_code="offline_forced",
            )
        else:
            try:
                snapshot = query_cms_snapshot(
                    registered_roots=roots,
                    config_path=config_path,
                    psql_path=psql_path,
                )
            except CmsObservationError as exc:
                online_failure = exc.reason_code
                snapshot = build_offline_cms_fallback(
                    registered_roots=roots,
                    inventory_state=inventory_state,
                    failure_reason_code=exc.reason_code,
                )
        comparison = (
            compare_cms_with_inventory(snapshot, inventory_state)
            if snapshot["cms_available"] and inventory_state.is_file()
            else None
        )
        target, published = publish_cms_snapshot(snapshot, output)
    except (CmsObservationError, OSError, ValueError) as exc:
        reason = exc.reason if isinstance(exc, CmsObservationError) else str(exc)
        click.echo(
            json.dumps(
                result_envelope(code=int(DazErrorCode.CMS_OBSERVATION_INVALID), reason=reason),
                sort_keys=True,
            )
        )
        raise click.exceptions.Exit(int(DazErrorCode.CMS_OBSERVATION_INVALID))
    click.echo(
        json.dumps(
            result_envelope(
                reason="cms_observation_complete",
                entity_ids=(snapshot["snapshot_id"],),
                data={
                    "cms_available": snapshot["cms_available"],
                    "online_failure": online_failure,
                    "product_count": len(snapshot.get("products", [])),
                    "content_count": len(snapshot.get("contents", [])),
                    "filesystem_comparison": comparison,
                    "publication": {"path": str(target), "published": published},
                },
            ),
            sort_keys=True,
        )
    )


@daz.group("mappings")
def daz_mappings() -> None:
    """Build immutable ontology and figure-mapping inputs."""


@daz_mappings.command("ontology-snapshot")
@click.option(
    "--source",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/ontology.yaml"),
    show_default=True,
)
@click.option(
    "--output",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path(r"F:\DAZ\07_mappings\genesis9\body_parts_v1\ontology_snapshots"),
    show_default=True,
)
def daz_mappings_ontology_snapshot(source: Path, output: Path) -> None:
    """Freeze canonical MaskFactory v1 IDs for downstream DAZ mapping jobs."""
    from .daz import DazErrorCode, result_envelope
    from .daz.mapping import (
        OntologySnapshotError,
        build_v1_ontology_snapshot,
        publish_ontology_snapshot,
    )

    try:
        snapshot = build_v1_ontology_snapshot(source)
        target, published = publish_ontology_snapshot(snapshot, output)
    except (OntologySnapshotError, OSError, ValueError) as exc:
        reason = exc.reason if isinstance(exc, OntologySnapshotError) else str(exc)
        click.echo(
            json.dumps(
                result_envelope(code=int(DazErrorCode.ONTOLOGY_SNAPSHOT_INVALID), reason=reason),
                sort_keys=True,
            )
        )
        raise click.exceptions.Exit(int(DazErrorCode.ONTOLOGY_SNAPSHOT_INVALID))
    click.echo(
        json.dumps(
            result_envelope(
                reason="daz_ontology_snapshot_complete",
                entity_ids=(snapshot["snapshot_id"],),
                data={
                    "snapshot": snapshot,
                    "publication": {"path": str(target), "published": published},
                },
            ),
            sort_keys=True,
        )
    )


@daz_control.command("status")
@click.option(
    "--config-root",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path("configs/daz"),
    show_default=True,
)
def daz_control_status(config_root: Path) -> None:
    from .daz import load_control_configuration, read_control_state, result_envelope

    try:
        configuration = load_control_configuration(config_root)
        state = read_control_state(configuration)
    except (OSError, ValueError) as exc:
        _emit_daz_error(exc)
    click.echo(json.dumps(result_envelope(reason="control_status", data=state), sort_keys=True))


def _change_daz_control(config_root: Path, action: str, reason: str, apply_changes: bool) -> None:
    from .daz import load_control_configuration, set_control_state

    try:
        configuration = load_control_configuration(config_root)
        report = set_control_state(
            configuration,
            action,
            reason=reason,
            apply=apply_changes,
        )
    except (OSError, ValueError) as exc:
        _emit_daz_error(exc)
    click.echo(json.dumps(report, sort_keys=True))


def _daz_control_options(function):
    function = click.option("--apply", "apply_changes", is_flag=True)(function)
    function = click.option("--reason", required=True)(function)
    function = click.option(
        "--config-root",
        type=click.Path(path_type=Path, file_okay=False, exists=True),
        default=Path("configs/daz"),
        show_default=True,
    )(function)
    return function


@daz_control.command("enable")
@_daz_control_options
def daz_control_enable(config_root: Path, reason: str, apply_changes: bool) -> None:
    """Plan or enable leasing; storage gates can still refuse it."""
    _change_daz_control(config_root, "enable", reason, apply_changes)


@daz_control.command("disable")
@_daz_control_options
def daz_control_disable(config_root: Path, reason: str, apply_changes: bool) -> None:
    """Plan or disable new leasing and drain outstanding work."""
    _change_daz_control(config_root, "disable", reason, apply_changes)


@daz_control.command("stop")
@_daz_control_options
def daz_control_stop(config_root: Path, reason: str, apply_changes: bool) -> None:
    """Plan or request a controlled stop without killing a process tree."""
    _change_daz_control(config_root, "stop", reason, apply_changes)


@golden_reference.command("import")
@click.argument("source_root", type=click.Path(path_type=Path, file_okay=False, exists=True))
@click.option(
    "--mapping",
    "mapping_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    required=True,
)
@click.option(
    "--output", "output_root", type=click.Path(path_type=Path, file_okay=False), required=True
)
def golden_reference_import(source_root: Path, mapping_path: Path, output_root: Path) -> None:
    """Losslessly normalize strict BW masks and produce an authority audit."""
    from .golden_reference import GoldenReferenceError, import_golden_reference

    try:
        manifest = import_golden_reference(source_root, output_root, mapping_path=mapping_path)
    except (GoldenReferenceError, OSError, ValueError, yaml.YAMLError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        json.dumps(
            {
                "authority": manifest["authority"],
                "blocker_count": len(manifest["blockers"]),
                "collection_id": manifest["collection_id"],
                "eligible_for_package_gold": manifest["eligible_for_package_gold"],
                "layer_count": manifest["layer_count"],
                "missing_part_count": len(manifest["missing_part_targets"]),
                "overlap_count": len(manifest["part_candidate_overlaps"]),
                "output": str(output_root),
            },
            sort_keys=True,
        )
    )


@golden_reference.command("verify")
@click.argument("output_root", type=click.Path(path_type=Path, file_okay=False, exists=True))
def golden_reference_verify(output_root: Path) -> None:
    """Verify all normalized reference hashes and strict binary-mask invariants."""
    from .golden_reference import GoldenReferenceError, verify_golden_reference

    try:
        issues = verify_golden_reference(output_root)
    except (GoldenReferenceError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps({"issues": issues, "passed": not issues}, sort_keys=True))
    if issues:
        raise click.ClickException("golden reference verification failed")


@golden_reference.command("cloud-benchmark")
@click.argument("reference_root", type=click.Path(path_type=Path, file_okay=False, exists=True))
@click.option("--label", "labels", multiple=True, required=True)
@click.option(
    "--provider",
    "provider_names",
    multiple=True,
    type=click.Choice(["gemini", "openai", "anthropic"]),
    help="Restrict a diagnostic run to named providers; default is all three.",
)
@click.option(
    "--cloud-config",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/cloud_teacher.yaml"),
    show_default=True,
)
@click.option(
    "--output", "output_root", type=click.Path(path_type=Path, file_okay=False), required=True
)
def golden_reference_cloud_benchmark(
    reference_root: Path,
    labels: tuple[str, ...],
    provider_names: tuple[str, ...],
    cloud_config: Path,
    output_root: Path,
) -> None:
    """Run explicitly authorized shadow teacher calls on selected reference labels."""
    from .golden_reference import GoldenReferenceError, run_reference_cloud_benchmark
    from .vlm.cloud_budget import CloudBudgetError
    from .vlm.cloud_teacher import CloudTeacherError

    try:
        summary = run_reference_cloud_benchmark(
            reference_root,
            labels=labels,
            cloud_config_path=cloud_config,
            output_root=output_root,
            provider_names=provider_names or ("gemini", "openai", "anthropic"),
        )
    except (GoldenReferenceError, CloudBudgetError, CloudTeacherError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        json.dumps(
            {
                "budget": summary["budget"],
                "completed": sum(
                    result["status"] == "complete" for result in summary["provider_results"]
                ),
                "failed": sum(
                    result["status"] != "complete" for result in summary["provider_results"]
                ),
                "output": str(output_root),
                "result_count": len(summary["provider_results"]),
            },
            sort_keys=True,
        )
    )


@main.group()
def cvat() -> None:
    """CVAT bridge (push drafts / pull corrections)."""


@cvat.command("init-project")
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/cvat.yaml"),
    show_default=True,
)
def cvat_init_project(config_path: Path) -> None:
    """Create or validate the canonical ontology-backed CVAT project."""
    from .cvat_bridge.client import CvatApiError, CvatClient
    from .cvat_bridge.project import init_project

    try:
        result = init_project(CvatClient.from_config(config_path), config_path=config_path)
    except (CvatApiError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        json.dumps(
            {
                "project_id": result["project_id"],
                "created": result["created"],
                "mapping": str(result["mapping"]),
            },
            sort_keys=True,
        )
    )


@cvat.command("push")
@click.argument("image_ids", nargs=-1, required=True)
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/cvat.yaml"),
    show_default=True,
)
@click.option(
    "--packages-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("data/packages"),
    show_default=True,
)
@click.option(
    "--task-records",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("data/cvat/tasks"),
    show_default=True,
)
def cvat_push(
    image_ids: tuple[str, ...], config_path: Path, packages_root: Path, task_records: Path
) -> None:
    """Push draft tasks into CVAT."""
    from .cvat_bridge.client import CvatApiError, CvatClient
    from .cvat_bridge.push import push_images

    try:
        task_ids = push_images(
            CvatClient.from_config(config_path),
            image_ids,
            config_path=config_path,
            packages_root=packages_root,
            task_records=task_records,
        )
    except (CvatApiError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps({"task_ids": task_ids}, sort_keys=True))


@cvat.command("publish-review-draft")
@click.option("--task-id", type=click.IntRange(min=1), required=True)
@click.option(
    "--review-draft",
    "review_draft_dir",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    required=True,
)
@click.option(
    "--audit-dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("data/cvat/autonomy_publications"),
    show_default=True,
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/cvat.yaml"),
    show_default=True,
)
def cvat_publish_review_draft(
    task_id: int, review_draft_dir: Path, audit_dir: Path, config_path: Path
) -> None:
    """Publish a reversible non-gold machine repair into an untouched CVAT draft."""
    from .cvat_bridge.autonomy_publish import publish_autonomous_review_draft
    from .cvat_bridge.client import CvatApiError, CvatClient

    try:
        result = publish_autonomous_review_draft(
            CvatClient.from_config(config_path),
            task_id=task_id,
            review_draft_dir=review_draft_dir,
            audit_dir=audit_dir,
            config_path=config_path,
        )
    except (CvatApiError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(result, sort_keys=True))


@cvat.command("pull")
@click.argument("image_ids", nargs=-1, required=True)
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/cvat.yaml"),
    show_default=True,
)
@click.option(
    "--task-records",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("data/cvat/tasks"),
    show_default=True,
)
@click.option(
    "--database",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("data/maskfactory.sqlite"),
    show_default=True,
)
def cvat_pull(
    image_ids: tuple[str, ...], config_path: Path, task_records: Path, database: Path
) -> None:
    """Pull human-corrected annotations from CVAT."""
    from .cvat_bridge.client import CvatApiError, CvatClient
    from .cvat_bridge.pull import pull_images

    try:
        task_ids = pull_images(
            CvatClient.from_config(config_path),
            image_ids,
            config_path=config_path,
            task_records=task_records,
            database=database,
        )
    except (CvatApiError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps({"task_ids": task_ids}, sort_keys=True))


@main.command()
@click.argument("image_id", required=True)
@click.option("--reviewer", required=True)
@click.option("--minutes", type=click.FloatRange(min=0), required=True)
@click.option(
    "--root",
    "packages_root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("data/packages"),
    show_default=True,
)
@click.option(
    "--database",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("data/maskfactory.sqlite"),
    show_default=True,
)
def package(
    image_id: str,
    reviewer: str,
    minutes: float,
    packages_root: Path,
    database: Path,
) -> None:
    """S13: package + freeze an approved gold image (re-runs QA)."""
    from .packager import (
        ApprovalRequiredError,
        PackageBlockedError,
        approve_package,
        approve_packages_atomically,
    )

    image_root = packages_root / image_id
    instances = sorted(
        (path for path in (image_root / "instances").glob("p*") if path.name[1:].isdigit()),
        key=lambda path: int(path.name[1:]),
    )
    if not instances and (image_root / "manifest.json").is_file():
        instances = [image_root]
    if not instances:
        raise click.ClickException(f"no package instances found for {image_id}")
    try:
        for instance in instances:
            try:
                approve_package(
                    instance,
                    reviewer=reviewer,
                    review_minutes=minutes,
                    approved=False,
                    dvc_add=lambda _path: None,
                )
            except ApprovalRequiredError:
                pass
        if not click.confirm(
            f"Approve {len(instances)} instance package(s) as gold?", default=False
        ):
            raise click.ClickException("approval cancelled")
        approve_packages_atomically(
            tuple(instances),
            reviewer=reviewer,
            review_minutes=minutes,
            approved=True,
        )
        from .state import persist_image_progress

        persist_image_progress(database, image_id, "approved_gold")
    except PackageBlockedError as exc:
        for result in exc.results:
            if not result.passed:
                click.echo(f"{result.qc_id}: {result.detail}", err=True)
        for panel in exc.panels:
            click.echo(f"panel: {panel}", err=True)
        raise click.ClickException(str(exc)) from exc
    except (OSError, RuntimeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"approved and frozen: {image_id}")


@main.command("autonomous-certify-package")
@click.argument("image_id")
@click.option("--instance", default="p0", show_default=True)
@click.option(
    "--certificate",
    "certificate_paths",
    multiple=True,
    required=True,
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
)
@click.option("--context", required=True)
@click.option("--pipeline-fingerprint", required=True)
@click.option(
    "--evidence", type=click.Path(path_type=Path, dir_okay=False, exists=True), required=True
)
@click.option("--training-loss-weight", type=click.FloatRange(min=0.5, max=0.75), default=0.65)
@click.option(
    "--root",
    "packages_root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("data/packages"),
    show_default=True,
)
@click.option(
    "--database",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("data/maskfactory.sqlite"),
    show_default=True,
)
def autonomous_certify_package_command(
    image_id: str,
    instance: str,
    certificate_paths: tuple[Path, ...],
    context: str,
    pipeline_fingerprint: str,
    evidence: Path,
    training_loss_weight: float,
    packages_root: Path,
    database: Path,
) -> None:
    """S13 autonomous path: hard-QA and freeze certificate-covered machine truth."""
    from .packager import PackageBlockedError, certify_autonomous_package
    from .state import persist_image_progress, upsert_package_truth

    package_root = _correction_package_root(packages_root, image_id, instance)
    try:
        certificates = tuple(
            json.loads(path.read_text(encoding="utf-8")) for path in certificate_paths
        )
        certify_autonomous_package(
            package_root,
            certificates=certificates,
            context=context,
            pipeline_fingerprint=pipeline_fingerprint,
            evidence_path=evidence,
            training_loss_weight=training_loss_weight,
        )
        persist_image_progress(database, image_id, "approved_gold")
        bindings = json.loads((package_root / "manifest.json").read_text(encoding="utf-8"))[
            "certification"
        ]["certificates"]
        upsert_package_truth(
            database,
            image_id=image_id,
            package_path=package_root.relative_to(packages_root).as_posix(),
            truth_tier="autonomous_certified_gold",
            truth_partition="train",
            training_loss_weight=training_loss_weight,
            certificate_bundle_sha256=hashlib.sha256(
                json.dumps(bindings, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        )
    except PackageBlockedError as exc:
        raise click.ClickException(str(exc)) from exc
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"autonomous certified and frozen: {image_id}/{instance}")


@main.group()
def correction() -> None:
    """Create, refresh, and atomically promote post-gold mask versions."""


def _correction_package_root(packages_root: Path, image_id: str, instance: str) -> Path:
    image_root = packages_root / image_id
    package_root = image_root / "instances" / instance
    if package_root.is_dir():
        return package_root
    if instance == "p0" and (image_root / "manifest.json").is_file():
        return image_root
    raise click.ClickException(f"package instance does not exist: {image_id}/{instance}")


@correction.command("begin")
@click.argument("image_id")
@click.option("--instance", default="p0", show_default=True)
@click.option(
    "--root",
    "packages_root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("data/packages"),
    show_default=True,
)
def correction_begin(image_id: str, instance: str, packages_root: Path) -> None:
    """Branch the current frozen maps into the next editable masks@vN workspace."""
    from .versioning import VersioningError, begin_correction

    package_root = _correction_package_root(packages_root, image_id, instance)
    try:
        candidate = begin_correction(package_root)
    except (OSError, ValueError, VersioningError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(candidate)


@correction.command("refresh")
@click.argument("image_id")
@click.option("--instance", default="p0", show_default=True)
@click.option("--version", type=click.IntRange(min=2), required=True)
@click.option(
    "--root",
    "packages_root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("data/packages"),
    show_default=True,
)
def correction_refresh(image_id: str, instance: str, version: int, packages_root: Path) -> None:
    """Regenerate candidate binary views after its authoritative maps are edited."""
    from .versioning import VersioningError, refresh_correction_branch

    package_root = _correction_package_root(packages_root, image_id, instance)
    try:
        candidate = refresh_correction_branch(package_root, version)
    except (OSError, ValueError, VersioningError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(candidate)


@correction.command("promote")
@click.argument("image_id")
@click.option("--instance", default="p0", show_default=True)
@click.option("--version", type=click.IntRange(min=2), required=True)
@click.option("--reviewer", required=True)
@click.option("--minutes", type=click.FloatRange(min=0), required=True)
@click.option(
    "--root",
    "packages_root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("data/packages"),
    show_default=True,
)
@click.option(
    "--database",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("data/maskfactory.sqlite"),
    show_default=True,
)
def correction_promote(
    image_id: str,
    instance: str,
    version: int,
    reviewer: str,
    minutes: float,
    packages_root: Path,
    database: Path,
) -> None:
    """QA, approve, DVC-add, and activate one corrected package version."""
    from .dvc_runtime import DvcRuntimeError, run_dvc
    from .versioning import VersioningError, promote_correction

    package_root = _correction_package_root(packages_root, image_id, instance)
    image_root = packages_root / image_id
    if not click.confirm(
        f"Promote {image_id}/{instance} masks@v{version} as corrected gold?", default=False
    ):
        raise click.ClickException("correction promotion cancelled")

    def dvc_add(_package: Path) -> None:
        result = run_dvc(("add", str(image_root.resolve())), timeout=300)
        if result.returncode:
            raise RuntimeError(f"dvc add failed: {result.stderr.strip()}")

    try:
        promote_correction(
            package_root,
            version,
            human_approved=True,
            reviewer=reviewer,
            review_minutes=minutes,
            database=database,
            dvc_add=dvc_add,
        )
    except (DvcRuntimeError, OSError, RuntimeError, ValueError, VersioningError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"promoted corrected gold: {image_id}/{instance} masks@v{version}")


@main.command("verify-package")
@click.argument("image_id", required=False)
@click.option(
    "--root",
    type=click.Path(path_type=Path, exists=True),
    default=Path("data/packages"),
    show_default=True,
)
@click.option("--sample", type=click.IntRange(min=1))
def verify_package(image_id: str | None, root: Path, sample: int | None) -> None:
    """Verify hashes and QCs selected by each package manifest ontology."""
    from .packager import verify_packages

    target = root / image_id if image_id else root
    try:
        verifications = verify_packages(target, sample=sample)
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    failed = [verification for verification in verifications if not verification.passed]
    for verification in verifications:
        click.echo(f"{'PASS' if verification.passed else 'FAIL'} {verification.package_root}")
        for result in verification.results:
            if not result.passed:
                click.echo(f"  {result.qc_id}: {result.detail}")
    if failed:
        raise click.ClickException(f"{len(failed)} package(s) failed verification")


@main.group()
def dataset() -> None:
    """Dataset operations."""


@dataset.command("build")
@click.option("--name", default="bodyparts", show_default=True)
@click.option(
    "--ontology",
    type=click.Choice(("body_parts_v1", "body_parts_v2"), case_sensitive=True),
    default="body_parts_v1",
    show_default=True,
    help="Build exactly one governed ontology; v2 remains gated until activation.",
)
@click.option(
    "--packages-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("data/packages"),
    show_default=True,
)
@click.option(
    "--output-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("datasets"),
    show_default=True,
)
@click.option("--publish/--no-publish", default=True, show_default=True)
@click.option(
    "--database",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("data/maskfactory.sqlite"),
    show_default=True,
)
@click.option(
    "--reference-database",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path(r"C:\Temp\MaskFactory_Reference_Library\reference_working.sqlite"),
    show_default=True,
)
def dataset_build(
    name: str,
    ontology: str,
    packages_root: Path,
    output_root: Path,
    publish: bool,
    database: Path,
    reference_database: Path,
) -> None:
    """S14: build the training dataset from gold packages."""
    from .datasets.builder import (
        approved_package_count,
        build_dataset,
        mark_dataset_exported,
        plan_dataset_publication,
    )
    from .dvc_runtime import DvcRuntimeError, run_dvc

    if name != "bodyparts" or ontology not in {"body_parts_v1", "body_parts_v2"}:
        raise click.ClickException(
            "S14 supports bodyparts with an explicit body_parts_v1 or body_parts_v2 ontology"
        )
    count = approved_package_count(packages_root, ontology_version=ontology)
    if count < 200:
        raise click.ClickException(
            f"P5 entry gate requires >=200 approved gold instances; found {count}"
        )
    try:
        existing_tags: tuple[str, ...] = ()
        if publish:
            import subprocess

            listed = subprocess.run(
                ["git", "tag", "--list", "dataset/bodyparts-v*"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if listed.returncode:
                raise RuntimeError(f"git tag preflight failed: {listed.stderr.strip()}")
            existing_tags = tuple(
                line.strip() for line in listed.stdout.splitlines() if line.strip()
            )
        plan = plan_dataset_publication(
            output_root,
            ontology_version=ontology,
            existing_tags=existing_tags,
        )
        path = build_dataset(
            packages_root=packages_root,
            output_root=output_root,
            version=plan.version,
            reference_database=reference_database,
            hard_case_file=output_root / "hard_case_holdout.txt",
            ontology_version=ontology,
        )
        if publish:
            add = run_dvc(("add", str(path.resolve())), timeout=1800)
            if add.returncode:
                raise RuntimeError(f"dvc add failed: {add.stderr.strip()}")
            push = run_dvc(("push",), timeout=1800)
            if push.returncode:
                raise RuntimeError(f"dvc push failed: {push.stderr.strip()}")
            tag = subprocess.run(
                ["git", "tag", plan.git_tag],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if tag.returncode:
                raise RuntimeError(f"git tag failed: {tag.stderr.strip()}")
            mark_dataset_exported(path, packages_root=packages_root, database=database)
    except (DvcRuntimeError, OSError, RuntimeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(path)


@main.group()
def coverage() -> None:
    """Coverage-matrix operations."""


@coverage.command("report")
@click.option(
    "--matrix",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("qa/coverage_matrix.json"),
    show_default=True,
)
@click.option("--target-per-cell", type=click.IntRange(min=1), default=5, show_default=True)
def coverage_report(matrix: Path, target_per_cell: int) -> None:
    """Report label x pose coverage (>=80% cells, D5)."""
    from .datasets.coverage import coverage_deficit_report

    try:
        document = json.loads(matrix.read_text(encoding="utf-8"))
        report = coverage_deficit_report(document, target_per_cell=target_per_cell)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(report, indent=2, sort_keys=True))


@coverage.command("v2-report")
@click.option(
    "--matrix",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("qa/coverage_matrix_v2.json"),
    show_default=True,
)
def coverage_v2_report(matrix: Path) -> None:
    """Report inactive v2 per-class state/view/pose/occlusion deficits."""
    from .datasets.coverage_v2 import (
        OntologyV2OperationsError,
        coverage_v2_deficit_report,
    )

    try:
        document = json.loads(matrix.read_text(encoding="utf-8"))
        report = coverage_v2_deficit_report(document)
    except (OSError, OntologyV2OperationsError, json.JSONDecodeError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(report, indent=2, sort_keys=True))


@coverage.command("v2-acquisition")
@click.option("--reason", required=True, help="Canonical ontology-v2 failure reason.")
@click.option("--label", required=True, help="Canonical body_parts_v2 foreground label.")
def coverage_v2_acquisition(reason: str, label: str) -> None:
    """Resolve one v2 failure into its governed hard-case acquisition action."""
    from .datasets.coverage_v2 import (
        OntologyV2OperationsError,
        acquisition_action_for_v2_failure,
    )

    try:
        action = acquisition_action_for_v2_failure(reason, label=label)
    except (OSError, OntologyV2OperationsError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(action, indent=2, sort_keys=True))


@main.command()
@click.argument("model", required=True)
@click.option(
    "--dataset", "dataset_root", type=click.Path(path_type=Path, file_okay=False), required=True
)
@click.option(
    "--config", "config_path", type=click.Path(path_type=Path, dir_okay=False), required=True
)
@click.option("--dvc-md5", required=True, help="Exact DVC md5 for the immutable dataset version.")
@click.option(
    "--runs-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("runs"),
    show_default=True,
)
@click.option(
    "--initialize-only",
    is_flag=True,
    help="Create the governed run tree without launching the gated trainer.",
)
def train(
    model: str,
    dataset_root: Path,
    config_path: Path,
    dvc_md5: str,
    runs_root: Path,
    initialize_only: bool,
) -> None:
    """Fine-tune a specialist model (doc 12 §6)."""
    from .training.run import TrainingRunError, initialize_training_run

    try:
        if initialize_only:
            path = initialize_training_run(
                model=model,
                dataset_root=dataset_root,
                config_path=config_path,
                dvc_md5=dvc_md5,
                runs_root=runs_root,
            )
        else:
            from .training.launch import launch_training

            path = launch_training(
                model=model,
                dataset_root=dataset_root,
                config_path=config_path,
                dvc_md5=dvc_md5,
                runs_root=runs_root,
            )
    except (FileExistsError, OSError, TrainingRunError, ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(path)


@main.command("training-doctor")
@click.option(
    "--lock",
    "lock_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("env/openmmlab_training_stack.lock.json"),
    show_default=True,
)
def training_doctor(lock_path: Path) -> None:
    """Verify the exact MMSeg/MMCV/CUDA training runtime."""
    from .training.runtime import TrainingRuntimeError, probe_openmmlab_runtime

    try:
        report = probe_openmmlab_runtime(lock_path)
    except (OSError, ValueError, json.JSONDecodeError, TrainingRuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    if not report.ready:
        raise click.ClickException("OpenMMLab training runtime is not ready")


@main.command()
@click.option("--compare", nargs=2, metavar="RUN_A RUN_B")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]), default="table")
@click.option(
    "--path",
    "leaderboard_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("runs/leaderboard.jsonl"),
    show_default=True,
)
def leaderboard(
    compare: tuple[str, str] | None, output_format: str, leaderboard_path: Path
) -> None:
    """Show the model leaderboard + champion (D6/G7)."""
    from .training.leaderboard import compare_runs, format_comparison_table, load_leaderboard

    try:
        rows = load_leaderboard(leaderboard_path)
        output: object = compare_runs(rows, *compare) if compare else rows
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    if compare and output_format == "table":
        click.echo(format_comparison_table(output))
    else:
        click.echo(json.dumps(output, indent=2, sort_keys=True))


@main.command()
@click.option("--dry-run", is_flag=True, help="Report manifest/database drift without writing.")
@click.option("--rebuild", is_flag=True, help="Explicitly rebuild (also the no-flag default).")
@click.option(
    "--packages-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("data/packages"),
    show_default=True,
)
@click.option(
    "--database",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("data/maskfactory.sqlite"),
    show_default=True,
)
def reindex(dry_run: bool, rebuild: bool, packages_root: Path, database: Path) -> None:
    """Diff or rebuild the SQLite image index from package manifests."""
    from .reindex import ReindexError, reindex_packages
    from .validation import ArtifactValidationError

    if dry_run and rebuild:
        raise click.UsageError("choose only one of --dry-run or --rebuild")
    try:
        difference = reindex_packages(
            packages_root=packages_root,
            database=database,
            dry_run=dry_run,
        )
    except (ReindexError, ArtifactValidationError, OSError, json.JSONDecodeError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(difference.as_dict(), indent=2, sort_keys=True))
    if not dry_run:
        click.echo("rebuild=complete")


@main.group()
def incident() -> None:
    """Run non-destructive incident-response drills."""


@incident.command("reindex-drill")
@click.option(
    "--database",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("data/maskfactory.sqlite"),
    show_default=True,
)
@click.option(
    "--packages-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("data/packages"),
    show_default=True,
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("qa/live_verification/ip3"),
    show_default=True,
)
def incident_reindex_drill(database: Path, packages_root: Path, output_dir: Path) -> None:
    """Exercise IP-3 by rebuilding an isolated copy of state.db."""
    from .reindex import ReindexError, run_reindex_incident_drill

    try:
        report = run_reindex_incident_drill(
            source_database=database, packages_root=packages_root, output_dir=output_dir
        )
    except (OSError, ReindexError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(report)


@main.command()
@click.option("--apply", "apply_changes", is_flag=True, help="Apply the reviewed plan.")
@click.option("--yes", is_flag=True, help="Confirm apply non-interactively.")
@click.option(
    "--packages-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("data/packages"),
    show_default=True,
)
@click.option(
    "--logs-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("logs"),
    show_default=True,
)
def gc(apply_changes: bool, yes: bool, packages_root: Path, logs_root: Path) -> None:
    """Garbage-collect deprecated package versions (runbook §6)."""
    from datetime import UTC, datetime

    from .gc import apply_gc_plan, build_gc_plan, write_gc_log

    plan = build_gc_plan(packages_root)
    click.echo(f"plan_hash={plan.plan_hash} candidates={len(plan.candidates)}")
    for candidate in plan.candidates:
        action = "REMOVE" if apply_changes else "WOULD REMOVE"
        click.echo(f"{action} {Path(candidate.package_root) / candidate.relative_path}")
    removed = ()
    if apply_changes:
        if not yes and not click.confirm("Apply this exact GC plan?", default=False):
            raise click.Abort()
        removed = apply_gc_plan(plan, packages_root=packages_root)
    date = datetime.now(UTC).date().isoformat()
    log = write_gc_log(logs_root / f"gc_{date}.log", plan, applied=apply_changes, removed=removed)
    click.echo(f"log={log}")


@main.group()
def comfy() -> None:
    """ComfyUI node-pack operations."""


@comfy.command("install")
@click.option(
    "--comfy-root",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    required=True,
)
@click.option(
    "--packages-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("data/packages"),
    show_default=True,
)
def comfy_install(comfy_root: Path, packages_root: Path) -> None:
    """Install/update the dependency-light read-only MaskFactory node pack."""
    from .serve.comfy_install import install_node_pack

    try:
        target = install_node_pack(comfy_root, packages_root=packages_root)
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(target)


@main.command()
@click.option("--port", type=click.IntRange(min=1, max=65535), default=8765, show_default=True)
def serve(port: int) -> None:
    """Run the localhost-only MaskFactory Mode-B API."""
    try:
        import uvicorn

        from .serve.api import create_app

        app = create_app()
    except (ImportError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


@main.command("benchmark-serving")
@click.argument("image", type=click.Path(path_type=Path, dir_okay=False, exists=True))
@click.option("--port", type=click.IntRange(min=1, max=65535), default=8765, show_default=True)
@click.option("--repetitions", type=click.IntRange(min=3), default=5, show_default=True)
@click.option("--single-label", default="left_forearm", show_default=True)
@click.option("--output", type=click.Path(path_type=Path, dir_okay=False))
def benchmark_serving(
    image: Path, port: int, repetitions: int, single_label: str, output: Path | None
) -> None:
    """Cold-launch and measure every MF-P6-02.05 serving latency target."""
    from .serve.benchmark import (
        LatencyBenchmarkError,
        default_latency_output,
        run_latency_benchmark,
    )

    target = output or default_latency_output()
    try:
        report_path = run_latency_benchmark(
            image,
            target,
            port=port,
            repetitions=repetitions,
            single_label=single_label,
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (FileExistsError, OSError, LatencyBenchmarkError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(report_path)
    if not report["passed"]:
        raise click.ClickException("one or more MF-P6-02.05 latency targets failed")


@main.command("verify-serving-workflows")
@click.argument("report", type=click.Path(path_type=Path, dir_okay=False, exists=True))
@click.option(
    "--policy",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("qa/governance/serving_workflow_performance_v1.json"),
    show_default=True,
)
@click.option(
    "--artifact-root",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path("."),
    show_default=True,
)
def verify_serving_workflows(report: Path, policy: Path, artifact_root: Path) -> None:
    """Verify complete MF-P6-06.08 Mode A/Mode B and rollback evidence."""
    from .serve.workflow_performance import (
        WorkflowPerformanceError,
        verify_workflow_performance_report,
    )

    try:
        document = json.loads(report.read_text(encoding="utf-8"))
        result = verify_workflow_performance_report(
            document,
            policy_path=policy,
            artifact_root=artifact_root,
        )
    except (OSError, json.JSONDecodeError, WorkflowPerformanceError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(result, sort_keys=True))


@main.command("preflight-serving-workflows")
@click.argument("input_document", type=click.Path(path_type=Path, dir_okay=False, exists=True))
@click.option(
    "--policy",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("qa/governance/serving_workflow_performance_v1.json"),
    show_default=True,
)
@click.option(
    "--artifact-root",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path("."),
    show_default=True,
)
@click.option(
    "--registry",
    "registry_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("models/model_registry.json"),
    show_default=True,
)
@click.option(
    "--pipeline",
    "pipeline_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/pipeline.yaml"),
    show_default=True,
)
@click.option(
    "--external-registry",
    "external_registry_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/external_sources.yaml"),
    show_default=True,
)
@click.option(
    "--packages-root",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path("data/packages"),
    show_default=True,
)
@click.option("--output", type=click.Path(path_type=Path, dir_okay=False))
def preflight_serving_workflows(
    input_document: Path,
    policy: Path,
    artifact_root: Path,
    registry_path: Path,
    pipeline_path: Path,
    external_registry_path: Path,
    packages_root: Path,
    output: Path | None,
) -> None:
    """Fail closed before launching the frozen MF-P6-06.08 workflow run."""
    from .serve.workflow_preflight import WorkflowPreflightError, preflight_workflow_execution

    try:
        document = json.loads(input_document.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise WorkflowPreflightError("workflow execution input must be a JSON object")
        report = preflight_workflow_execution(
            document,
            artifact_root=artifact_root,
            policy_path=policy,
            registry_path=registry_path,
            pipeline_path=pipeline_path,
            external_registry_path=external_registry_path,
            packages_root=packages_root,
        )
        rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(rendered)
    except (FileExistsError, OSError, json.JSONDecodeError, WorkflowPreflightError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(rendered, nl=False)
    if not report["ready"]:
        raise click.exceptions.Exit(1)


# --- environment / model management (P0) ---
@main.command()
def doctor() -> None:
    """Environment health checks (MF-P0-07)."""
    emitted = 0

    def emit(result) -> None:
        nonlocal emitted
        click.echo(f"[{result.status}] {result.name}: {result.detail}")
        if result.hint:
            click.echo(f"  FIX: {result.hint}")
        emitted += 1

    click.echo(
        "doctor: running bounded local checks "
        f"({LOCAL_INFERENCE_TIMEOUT_SECONDS}s maximum per inference request)"
    )
    results = run_doctor(on_result=emit)
    for result in results[emitted:]:
        emit(result)
    statuses = ("PASS", "WARN", "SKIP", "FAIL")
    counts = {status: sum(result.status == status for result in results) for status in statuses}
    click.echo("doctor summary: " + " ".join(f"{status}={counts[status]}" for status in statuses))
    if counts["FAIL"]:
        raise click.exceptions.Exit(1)


@main.group()
def models() -> None:
    """Model checkpoint registry operations."""


@models.command("fetch")
@click.argument("key", required=False)
@click.option("--all", "fetch_all", is_flag=True, help="Fetch every registered model.")
@click.option(
    "--catalog",
    "catalog_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=DEFAULT_CATALOG,
    show_default=True,
)
@click.option(
    "--registry",
    "registry_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=DEFAULT_REGISTRY,
    show_default=True,
)
@click.option(
    "--models-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=DEFAULT_REGISTRY.parent,
    show_default=True,
)
def models_fetch(
    key: str | None,
    fetch_all: bool,
    catalog_path: Path,
    registry_path: Path,
    models_root: Path,
) -> None:
    """Download + register a model checkpoint (SHA-256 + smoke test)."""
    if bool(key) == fetch_all:
        raise click.UsageError("provide exactly one model KEY or --all")
    try:
        if fetch_all:
            keys = catalog_model_keys(catalog_path)
            if not keys:
                raise ModelFetchError(f"model catalog contains no entries: {catalog_path}")
        else:
            keys = [key]  # type: ignore[list-item]
        results = fetch_models(
            keys,
            catalog_path=catalog_path,
            registry_path=registry_path,
            models_root=models_root,
        )
    except (OSError, ValueError, ModelFetchError, ModelRegistryError) as exc:
        raise click.ClickException(str(exc)) from exc
    for result in results:
        click.echo(
            f"{result['key']}: {result['fetch_status']} sha256={result['sha256']} "
            f"verified={str(result['verified']).lower()}"
        )


@models.command("register-ollama")
@click.option(
    "--registry",
    "registry_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=DEFAULT_REGISTRY,
    show_default=True,
)
def models_register_ollama(registry_path: Path) -> None:
    """Register locally managed Ollama models after API/CLI digest cross-checks."""
    try:
        entries = register_ollama_models(registry_path=registry_path)
    except (OSError, ValueError, ModelRegistryError) as exc:
        raise click.ClickException(str(exc)) from exc
    for entry in entries:
        click.echo(
            f"{entry['key']}: {entry['register_status']} managed=true digest={entry['digest']} "
            f"ollama_list_id={entry['ollama_list_id']} verified=true"
        )


@models.command("register-training-candidate")
@click.argument("run_root", type=click.Path(path_type=Path, file_okay=False, exists=True))
@click.option("--key", "candidate_key", required=True, help="Stable registry key for this run.")
@click.option(
    "--registry",
    "registry_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=DEFAULT_REGISTRY,
    show_default=True,
)
@click.option(
    "--models-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=DEFAULT_REGISTRY.parent,
    show_default=True,
)
def models_register_training_candidate(
    run_root: Path, candidate_key: str, registry_path: Path, models_root: Path
) -> None:
    """Register one sealed completed MMSeg run as a non-champion candidate."""
    try:
        entry = register_training_candidate(
            run_root,
            candidate_key,
            registry_path=registry_path,
            models_root=models_root,
        )
    except (OSError, ValueError, ModelRegistryError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"{entry['key']}: role={entry['role']} run={entry['training_run']} "
        f"sha256={entry['sha256']} verified=true"
    )


@models.command("champions")
@click.option(
    "--registry",
    "registry_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=DEFAULT_REGISTRY,
    show_default=True,
)
@click.option(
    "--history",
    "history_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("runs/champion_history.jsonl"),
    show_default=True,
)
def models_champions(registry_path: Path, history_path: Path) -> None:
    """Show current champion role pointers and promotion history."""
    from .models.registry import champion_status

    try:
        status = champion_status(registry_path=registry_path, history_path=history_path)
    except (OSError, ModelRegistryError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(status, indent=2, sort_keys=True))


@models.command("promote-custom-segmenter")
@click.argument("candidate_key")
@click.option(
    "--matrix-bundle",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    required=True,
    help="Complete signed ten-role matrix promotion bundle.",
)
@click.option(
    "--registry",
    "registry_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=DEFAULT_REGISTRY,
    show_default=True,
)
@click.option(
    "--models-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=DEFAULT_REGISTRY.parent,
    show_default=True,
)
@click.option(
    "--history",
    "history_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("runs/champion_history.jsonl"),
    show_default=True,
)
def models_promote_custom_segmenter(
    candidate_key: str,
    matrix_bundle: Path,
    registry_path: Path,
    models_root: Path,
    history_path: Path,
) -> None:
    """Transactionally promote a certified custom body-part segmenter."""
    from .models.registry import promote_custom_segmenter_role

    try:
        record = promote_custom_segmenter_role(
            candidate_key,
            matrix_bundle_root=matrix_bundle,
            registry_path=registry_path,
            models_root=models_root,
            history_path=history_path,
        )
    except (OSError, ValueError, json.JSONDecodeError, ModelRegistryError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(record, indent=2, sort_keys=True))


@models.command("promote-specialist")
@click.argument("candidate_key")
@click.option(
    "--role",
    type=click.Choice(["champion_hand", "champion_clothing"]),
    required=True,
)
@click.option(
    "--matrix-bundle",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    required=True,
)
@click.option(
    "--registry",
    "registry_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=DEFAULT_REGISTRY,
    show_default=True,
)
@click.option(
    "--models-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=DEFAULT_REGISTRY.parent,
    show_default=True,
)
@click.option(
    "--history",
    "history_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("runs/champion_history.jsonl"),
    show_default=True,
)
def models_promote_specialist(
    candidate_key: str,
    role: str,
    matrix_bundle: Path,
    registry_path: Path,
    models_root: Path,
    history_path: Path,
) -> None:
    """Promote a matrix-certified hand or clothing specialist transactionally."""
    from .models.registry import promote_model_role

    try:
        record = promote_model_role(
            candidate_key,
            role,
            matrix_bundle_root=matrix_bundle,
            registry_path=registry_path,
            models_root=models_root,
            history_path=history_path,
        )
    except (OSError, ValueError, ModelRegistryError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(record, indent=2, sort_keys=True))


@models.command("rollback-specialist")
@click.argument("transaction_id")
@click.option(
    "--registry",
    "registry_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=DEFAULT_REGISTRY,
    show_default=True,
)
@click.option(
    "--models-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=DEFAULT_REGISTRY.parent,
    show_default=True,
)
@click.option(
    "--history",
    "history_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("runs/champion_history.jsonl"),
    show_default=True,
)
def models_rollback_specialist(
    transaction_id: str,
    registry_path: Path,
    models_root: Path,
    history_path: Path,
) -> None:
    """Rollback one specialist promotion by immutable transaction id."""
    from .models.registry import load_specialist_promotion_transaction, rollback_model_role

    try:
        record = load_specialist_promotion_transaction(transaction_id, history_path=history_path)
        rollback = rollback_model_role(
            record,
            registry_path=registry_path,
            models_root=models_root,
            history_path=history_path,
        )
    except (OSError, ValueError, ModelRegistryError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(rollback, indent=2, sort_keys=True))


@models.command("rollback-custom-segmenter")
@click.argument("transaction_id")
@click.option(
    "--registry",
    "registry_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=DEFAULT_REGISTRY,
    show_default=True,
)
@click.option(
    "--models-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=DEFAULT_REGISTRY.parent,
    show_default=True,
)
@click.option(
    "--history",
    "history_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("runs/champion_history.jsonl"),
    show_default=True,
)
def models_rollback_custom_segmenter(
    transaction_id: str,
    registry_path: Path,
    models_root: Path,
    history_path: Path,
) -> None:
    """Rollback one custom-segmenter promotion by immutable transaction id."""
    from .models.registry import load_promotion_transaction, rollback_custom_segmenter_role

    try:
        record = load_promotion_transaction(transaction_id, history_path=history_path)
        rollback = rollback_custom_segmenter_role(
            record,
            registry_path=registry_path,
            models_root=models_root,
            history_path=history_path,
        )
    except (OSError, ValueError, ModelRegistryError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(rollback, indent=2, sort_keys=True))


@models.command("promote-interactive")
@click.argument("candidate_key")
@click.option(
    "--promotion-certificate",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    required=True,
)
@click.option(
    "--matrix-bundle",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    required=True,
)
@click.option(
    "--candidate-checkpoint",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    required=True,
)
@click.option(
    "--candidate-runtime-lock",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    required=True,
)
@click.option(
    "--smoke-evidence",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    required=True,
    help="Exact-input live smoke receipt for the proposed three-file state.",
)
@click.option(
    "--pipeline",
    "pipeline_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/pipeline.yaml"),
    show_default=True,
)
@click.option(
    "--external-registry",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/external_sources.yaml"),
    show_default=True,
)
@click.option(
    "--model-registry",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("models/model_registry.json"),
    show_default=True,
)
@click.option(
    "--history",
    "history_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("runs/interactive_provider_history.jsonl"),
    show_default=True,
)
@click.option(
    "--snapshot-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=Path("runs/interactive_provider_transactions"),
    show_default=True,
)
@click.option(
    "--project-root",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path("."),
    show_default=True,
)
def models_promote_interactive(
    candidate_key: str,
    promotion_certificate: Path,
    matrix_bundle: Path,
    candidate_checkpoint: Path,
    candidate_runtime_lock: Path,
    smoke_evidence: Path,
    pipeline_path: Path,
    external_registry: Path,
    model_registry: Path,
    history_path: Path,
    snapshot_root: Path,
    project_root: Path,
) -> None:
    """Promote one signed, matrix-bound interactive provider transactionally."""
    from .providers.interactive_transaction import (
        InteractiveProviderTransactionError,
        load_smoke_evidence_runner,
        promote_interactive_provider,
    )

    try:
        certificate = json.loads(promotion_certificate.read_text(encoding="utf-8"))
        smoke_runner = load_smoke_evidence_runner(smoke_evidence)
        record = promote_interactive_provider(
            candidate_key,
            promotion_certificate=certificate,
            matrix_bundle_root=matrix_bundle,
            candidate_checkpoint_path=candidate_checkpoint,
            candidate_runtime_lock_path=candidate_runtime_lock,
            smoke_runner=smoke_runner,
            pipeline_path=pipeline_path,
            external_registry_path=external_registry,
            model_registry_path=model_registry,
            history_path=history_path,
            snapshot_root=snapshot_root,
            project_root=project_root,
        )
    except (OSError, ValueError, json.JSONDecodeError, InteractiveProviderTransactionError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(record, indent=2, sort_keys=True))


@models.command("rollback-interactive")
@click.argument("transaction_id")
@click.option(
    "--smoke-evidence",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    required=True,
    help="Exact-input live smoke receipt for the restored three-file state.",
)
@click.option(
    "--pipeline",
    "pipeline_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/pipeline.yaml"),
    show_default=True,
)
@click.option(
    "--external-registry",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/external_sources.yaml"),
    show_default=True,
)
@click.option(
    "--model-registry",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("models/model_registry.json"),
    show_default=True,
)
@click.option(
    "--history",
    "history_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("runs/interactive_provider_history.jsonl"),
    show_default=True,
)
@click.option(
    "--snapshot-root",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path("runs/interactive_provider_transactions"),
    show_default=True,
)
def models_rollback_interactive(
    transaction_id: str,
    smoke_evidence: Path,
    pipeline_path: Path,
    external_registry: Path,
    model_registry: Path,
    history_path: Path,
    snapshot_root: Path,
) -> None:
    """Rollback all interactive provider files by immutable transaction id."""
    from .providers.interactive_transaction import (
        InteractiveProviderTransactionError,
        load_smoke_evidence_runner,
        rollback_interactive_provider,
    )

    try:
        smoke_runner = load_smoke_evidence_runner(smoke_evidence)
        record = rollback_interactive_provider(
            transaction_id,
            smoke_runner=smoke_runner,
            pipeline_path=pipeline_path,
            external_registry_path=external_registry,
            model_registry_path=model_registry,
            history_path=history_path,
            snapshot_root=snapshot_root,
        )
    except (OSError, ValueError, json.JSONDecodeError, InteractiveProviderTransactionError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(record, indent=2, sort_keys=True))


@main.group()
def external() -> None:
    """External foundation provider operations (doc 16)."""


@external.command("import-discovery")
@click.argument("discovery_path", type=click.Path(path_type=Path, dir_okay=False, exists=True))
@click.option(
    "--registry",
    "external_registry_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=DEFAULT_CONFIG,
    show_default=True,
)
@click.option(
    "--pipeline",
    "pipeline_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/pipeline.yaml"),
    show_default=True,
)
@click.option(
    "--models",
    "model_registry_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=DEFAULT_REGISTRY,
    show_default=True,
)
@click.option(
    "--history",
    "history_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("runs/provider_discoveries.jsonl"),
    show_default=True,
)
def external_import_discovery(
    discovery_path: Path,
    external_registry_path: Path,
    pipeline_path: Path,
    model_registry_path: Path,
    history_path: Path,
) -> None:
    """Import one hash-bound discovery as a planned challenger only."""
    from .providers.discovery import ProviderDiscoveryError, import_planned_challenger

    try:
        discovery = json.loads(discovery_path.read_text(encoding="utf-8"))
        record = import_planned_challenger(
            discovery,
            external_registry_path=external_registry_path,
            pipeline_path=pipeline_path,
            model_registry_path=model_registry_path,
            history_path=history_path,
        )
    except (OSError, json.JSONDecodeError, ProviderDiscoveryError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"provider={record['provider_key']} lifecycle=planned "
        f"record_sha256={record['record_sha256']}"
    )


@external.command("probe")
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=DEFAULT_CONFIG,
    show_default=True,
)
@click.option(
    "--workflows",
    "workflow_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=DEFAULT_WORKFLOWS,
    show_default=True,
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=DEFAULT_OUTPUT,
    show_default=True,
)
def external_probe(config_path: Path, workflow_path: Path, output_path: Path) -> None:
    """Report installed/missing providers and hash local artifacts; never download."""
    report = probe_external_sources(
        config_path=config_path,
        workflow_path=workflow_path,
        output_path=output_path,
    )
    summary = report["summary"]
    click.echo(
        f"providers={summary['provider_count']} available={summary['available']} "
        f"missing={summary['missing']} reference_only={summary['reference_only']}"
    )
    click.echo(f"downloads_attempted={report['downloads_attempted']} output={output_path}")


@external.command("run-fixtures")
@click.option(
    "--fixtures-dir",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=DEFAULT_FIXTURES,
    show_default=True,
)
@click.option(
    "--output-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=DEFAULT_FIXTURE_OUTPUT,
    show_default=True,
)
@click.option(
    "--self-test",
    is_flag=True,
    help="Exercise the fixture infrastructure with deterministic non-model outputs.",
)
def external_run_fixtures(fixtures_dir: Path, output_root: Path, self_test: bool) -> None:
    """Save raw provider fixture outputs and side-by-side QA panels."""
    runners = [SelfTestRunner()] if self_test else None
    manifest = run_external_fixtures(
        fixtures_dir=fixtures_dir,
        output_root=output_root,
        runners=runners,
    )
    click.echo(
        f"fixtures={manifest['fixture_count']} runners={manifest['runner_count']} "
        f"raw_before_visualization={manifest['raw_outputs_preserved_before_visualization']}"
    )
    click.echo(f"promoted_to_gold={manifest['promoted_to_gold']} output={output_root}")


@main.group()
def governance() -> None:
    """Run signed, fail-closed technology governance operations."""


@governance.command("init-currency-key")
@click.option(
    "--private-key",
    type=click.Path(path_type=Path, dir_okay=False),
    required=True,
    help="Private Ed25519 key path outside the repository.",
)
@click.option(
    "--public-key",
    type=click.Path(path_type=Path, dir_okay=False),
    required=True,
    help="Public Ed25519 verification key path.",
)
def governance_init_currency_key(private_key: Path, public_key: Path) -> None:
    """Create a non-overwriting Ed25519 currency-review signing keypair."""
    from .providers.currency import CurrencyReviewError, generate_currency_signing_key

    try:
        key_id = generate_currency_signing_key(private_key, public_key)
    except (CurrencyReviewError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps({"public_key_sha256": key_id}, sort_keys=True))


def _currency_dependency_paths() -> dict[str, Path]:
    return {
        "conda_environment": Path("env/maskfactory_env.yml"),
        "governance_decisions": Path("Plan/DECISIONS_LOG.md"),
        "python_lock": Path("env/requirements.lock.txt"),
        "python_project": Path("pyproject.toml"),
    }


@governance.command("build-currency-review")
@click.option(
    "--event",
    type=click.Choice(
        ["scheduled_90_day", "dataset_freeze", "training", "promotion", "major_release"]
    ),
    required=True,
)
@click.option("--reviewer", required=True)
@click.option(
    "--private-key",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    required=True,
)
@click.option(
    "--pipeline",
    "pipeline_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/pipeline.yaml"),
    show_default=True,
)
@click.option(
    "--external-registry",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/external_sources.yaml"),
    show_default=True,
)
@click.option(
    "--model-registry",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("models/model_registry.json"),
    show_default=True,
)
@click.option(
    "--rollback-evidence",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    required=True,
)
@click.option("--previous-review-sha256", required=False)
@click.option("--output", type=click.Path(path_type=Path, dir_okay=False), required=True)
def governance_build_currency_review(
    event: str,
    reviewer: str,
    private_key: Path,
    pipeline_path: Path,
    external_registry: Path,
    model_registry: Path,
    rollback_evidence: Path,
    previous_review_sha256: str | None,
    output: Path,
) -> None:
    """Derive and sign a current review; findings cannot be overridden."""
    from .providers.currency import CurrencyReviewError, build_currency_review

    try:
        review = build_currency_review(
            event=event,
            reviewer=reviewer,
            private_key_path=private_key,
            pipeline_path=pipeline_path,
            external_registry_path=external_registry,
            model_registry_path=model_registry,
            rollback_evidence_path=rollback_evidence,
            dependency_paths=_currency_dependency_paths(),
            previous_review_sha256=previous_review_sha256,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(review, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (CurrencyReviewError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        json.dumps(
            {
                "review_id": review["review_id"],
                "review_sha256": review["review_sha256"],
                "status": review["status"],
            },
            sort_keys=True,
        )
    )


@governance.command("verify-currency-review")
@click.argument("review_path", type=click.Path(path_type=Path, dir_okay=False, exists=True))
@click.option(
    "--public-key",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    required=True,
)
@click.option(
    "--pipeline",
    "pipeline_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/pipeline.yaml"),
    show_default=True,
)
@click.option(
    "--external-registry",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/external_sources.yaml"),
    show_default=True,
)
@click.option(
    "--model-registry",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("models/model_registry.json"),
    show_default=True,
)
@click.option(
    "--rollback-evidence",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    required=True,
)
@click.option(
    "--required-event",
    type=click.Choice(
        ["scheduled_90_day", "dataset_freeze", "training", "promotion", "major_release"]
    ),
    required=False,
)
@click.option("--allow-failed-review", is_flag=True, default=False)
def governance_verify_currency_review(
    review_path: Path,
    public_key: Path,
    pipeline_path: Path,
    external_registry: Path,
    model_registry: Path,
    rollback_evidence: Path,
    required_event: str | None,
    allow_failed_review: bool,
) -> None:
    """Verify signature, current inputs, age, roles, certificates, and rollback."""
    from .providers.currency import CurrencyReviewError, verify_currency_review

    try:
        review = json.loads(review_path.read_text(encoding="utf-8"))
        result = verify_currency_review(
            review,
            public_key_path=public_key,
            pipeline_path=pipeline_path,
            external_registry_path=external_registry,
            model_registry_path=model_registry,
            rollback_evidence_path=rollback_evidence,
            dependency_paths=_currency_dependency_paths(),
            required_event=required_event,
            require_pass=not allow_failed_review,
        )
    except (CurrencyReviewError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
