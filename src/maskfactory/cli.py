"""maskfactory command-line interface (doc 05 §3, MF-P0-08.08).

Production console entry point ``maskfactory = maskfactory.cli:main``.
"""

from __future__ import annotations

import json
from pathlib import Path

import click

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
    """MaskFactory — body-part mask factory pipeline (Plan/ docs 00–17)."""


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
    """D1: ingest one governed incoming file and emit all 56 atomic drafts in one command."""
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
    from .state import persist_terminal_image_outcome

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
                else "needs_human"
                if any(item["overall"] != "pass" for item in instances.values())
                else "pass"
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
@click.option("--approved-gold-count", type=click.IntRange(min=0), default=None)
@click.option("--champion-gold-count", type=click.IntRange(min=0), default=0, show_default=True)
@click.option("--report-date", default=None, help="ISO date override for deterministic reruns.")
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    default=Path("configs/vlm.yaml"),
    show_default=True,
)
def active_learning(
    failure_queue: Path,
    coverage_matrix: Path,
    packages_root: Path,
    output_dir: Path,
    approved_gold_count: int | None,
    champion_gold_count: int,
    report_date: str | None,
    config_path: Path,
) -> None:
    """Run the governed weekly failure-mining and QA-summary batch."""
    from .datasets.active_learning import run_active_learning
    from .datasets.builder import approved_package_count
    from .qa.failure_mining import FailureMiningError
    from .vlm.client import VlmClientError
    from .vlm.text import TextLlmError

    count = (
        approved_gold_count
        if approved_gold_count is not None
        else approved_package_count(packages_root)
    )
    try:
        result = run_active_learning(
            failure_queue_path=failure_queue,
            coverage_matrix_path=coverage_matrix,
            output_dir=output_dir,
            approved_gold_count=count,
            champion_gold_count=champion_gold_count,
            report_date=report_date,
            packages_root=packages_root,
            vlm_config_path=config_path,
        )
    except (FailureMiningError, OSError, ValueError, TextLlmError, VlmClientError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(json.dumps(result, indent=2, sort_keys=True))


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
            else "disabled_gate_unavailable"
            if disabled
            else "needs_human"
            if needs_human
            else "pass"
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
def cvat_pull(image_ids: tuple[str, ...], config_path: Path, task_records: Path) -> None:
    """Pull human-corrected annotations from CVAT."""
    from .cvat_bridge.client import CvatApiError, CvatClient
    from .cvat_bridge.pull import pull_images

    try:
        task_ids = pull_images(
            CvatClient.from_config(config_path),
            image_ids,
            config_path=config_path,
            task_records=task_records,
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
def package(image_id: str, reviewer: str, minutes: float, packages_root: Path) -> None:
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
    """Verify a gold package (all hashes + format QCs)."""
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
@click.option("--ontology", default="body_parts_v1", show_default=True)
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
def dataset_build(
    name: str, ontology: str, packages_root: Path, output_root: Path, publish: bool
) -> None:
    """S14: build the training dataset from gold packages."""
    from .datasets.builder import approved_package_count, build_dataset, next_dataset_version
    from .dvc_runtime import DvcRuntimeError, run_dvc

    if name != "bodyparts" or ontology != "body_parts_v1":
        raise click.ClickException("S14 v1 supports exactly bodyparts/body_parts_v1")
    count = approved_package_count(packages_root)
    if count < 200:
        raise click.ClickException(
            f"P5 entry gate requires >=200 approved gold instances; found {count}"
        )
    version = next_dataset_version(output_root)
    try:
        path = build_dataset(
            packages_root=packages_root,
            output_root=output_root,
            version=version,
            hard_case_file=output_root / "hard_case_holdout.txt",
        )
        if publish:
            add = run_dvc(("add", str(path.resolve())), timeout=1800)
            if add.returncode:
                raise RuntimeError(f"dvc add failed: {add.stderr.strip()}")
            import subprocess

            tag = subprocess.run(
                ["git", "tag", f"dataset/bodyparts-v{version}"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if tag.returncode:
                raise RuntimeError(f"git tag failed: {tag.stderr.strip()}")
            push = run_dvc(("push",), timeout=1800)
            if push.returncode:
                raise RuntimeError(f"dvc push failed: {push.stderr.strip()}")
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


@main.group()
def external() -> None:
    """External foundation provider operations (doc 16)."""


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


if __name__ == "__main__":
    main()
