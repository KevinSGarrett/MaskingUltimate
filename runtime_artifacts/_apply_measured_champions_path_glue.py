"""Idempotently apply measured-champions-path production glue edits.

Concurrent sessions clobber unstaged tracked edits. Re-run this before commit.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _patch(path: Path, old: str, new: str, label: str) -> str:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return f"{label}: already-applied"
    if old not in text:
        return f"{label}: ANCHOR-MISSING"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return f"{label}: applied"


def _ensure_contains(path: Path, needle: str, label: str) -> str:
    text = path.read_text(encoding="utf-8")
    if needle in text:
        return f"{label}: present"
    return f"{label}: MISSING"


def main() -> int:
    results: list[str] = []
    results.append(
        _ensure_contains(
            ROOT / "src/maskfactory/autonomy/production_audit.py",
            "build_production_weekly_audit_queue",
            "production-audit-module",
        )
    )

    # Fix accidental missing json import reference in patch context — operations already imports json.
    results.append(
        _patch(
            ROOT / "src/maskfactory/cli.py",
            """@autonomy.command("build-audit-queue")
@click.option(
    "--lifecycle-root",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path("work/instances"),
    show_default=True,
)
""",
            """@autonomy.command("build-audit-queue")
@click.option(
    "--lifecycle-root",
    type=click.Path(path_type=Path, file_okay=False, exists=True),
    default=Path("runs"),
    show_default=True,
    help=(
        "Root containing autonomy lifecycle sidecars. Production path is runs/ "
        "(discovers **/autonomy/*.json). Demo/test roots may be a flat lifecycle dir."
    ),
)
""",
            "cli-audit-default-runs",
        )
    )
    results.append(
        _patch(
            ROOT / "src/maskfactory/cli.py",
            """    from .autonomy.calibration import AutonomyCalibrationError, load_autonomy_config
    from .autonomy.operations import build_weekly_audit_queue

    try:
        config = load_autonomy_config(config_path)
        queue = build_weekly_audit_queue(
""",
            """    from .autonomy.calibration import AutonomyCalibrationError, load_autonomy_config
    from .autonomy.production_audit import build_production_weekly_audit_queue

    try:
        config = load_autonomy_config(config_path)
        queue = build_production_weekly_audit_queue(
""",
            "cli-audit-production-builder",
        )
    )

    results.append(
        _patch(
            ROOT / "tools/weekly_qa.ps1",
            '"--lifecycle-root work/instances"',
            '"--lifecycle-root runs"',
            "weekly-qa-runs",
        )
    )

    results.append(
        _patch(
            ROOT / "src/maskfactory/vlm/production.py",
            """from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import numpy as np
import yaml
from PIL import Image

from ..autonomy.adapters import MaskCandidateInput, build_mask_candidate_evidence
from ..autonomy.calibration import (
    build_autonomy_pipeline_fingerprint,
    load_autonomy_config,
)
from ..autonomy.lifecycle import (
    certificate_is_revoked,
    load_scoped_certificate,
    write_lifecycle_sidecar,
)
""",
            """from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import numpy as np
import yaml
from PIL import Image

from ..autonomy.adapters import MaskCandidateInput, build_mask_candidate_evidence
from ..autonomy.calibration import (
    build_autonomy_pipeline_fingerprint,
    load_autonomy_config,
)
from ..autonomy.corpus import AutonomousCorpusError, corpus_record_from_decision
from ..autonomy.lifecycle import (
    certificate_is_revoked,
    load_scoped_certificate,
    write_lifecycle_sidecar,
)
""",
            "production-imports",
        )
    )

    results.append(
        _patch(
            ROOT / "src/maskfactory/vlm/production.py",
            """            lifecycle = write_lifecycle_sidecar(
                output_dir / "autonomy" / f"{label}.json",
                image_id=str(report["image_id"]),
                instance_id=failure_instance_id,
                pipeline_fingerprint=autonomy_pipeline_fingerprint,
                decision=autonomy_decision,
            )
            autonomy_lifecycle.append(lifecycle)
            review_selection = select_pre_review_candidate(
""",
            """            lifecycle_path = output_dir / "autonomy" / f"{label}.json"
            lifecycle = write_lifecycle_sidecar(
                lifecycle_path,
                image_id=str(report["image_id"]),
                instance_id=failure_instance_id,
                pipeline_fingerprint=autonomy_pipeline_fingerprint,
                decision=autonomy_decision,
            )
            autonomy_lifecycle.append(lifecycle)
            try:
                machine_root = Path(os.environ.get("MASKFACTORY_MACHINE_ROOT", "runs")).resolve()
                corpus_record_from_decision(
                    lifecycle_path,
                    machine_root=machine_root,
                    image_id=str(report["image_id"]),
                    decision=autonomy_decision,
                    pipeline_fingerprint=autonomy_pipeline_fingerprint,
                )
            except (AutonomousCorpusError, OSError, ValueError):
                pass
            review_selection = select_pre_review_candidate(
""",
            "production-corpus-envelope",
        )
    )

    results.append(
        _patch(
            ROOT / "src/maskfactory/stages/production.py",
            """import hashlib
import json
import shutil
import uuid
""",
            """import hashlib
import json
import os
import shutil
import uuid
""",
            "stages-os-import",
        )
    )

    results.append(
        _patch(
            ROOT / "src/maskfactory/stages/production.py",
            """        status = run_s11_production(
            source_crop_path=s01_dir / instance_name / "person_ctx.png",
            part_map_path=context.prior_stage_dir("S09") / "label_map_part.png",
            s10_report_path=context.prior_stage_dir("S10") / "qa_report.json",
            output_dir=context.output_dir,
            gate_path=ROOT / "qa/vlm_eval/results/production_gate.json",
            failure_queue_path=ROOT / "qa/failure_queue.jsonl",
            pose_angle=str(pose["view"]),
            failure_instance_id=instance_name,
            workhorse_enabled=True,
            auto_load_correction_refiner=True,
            map_qa_validator=validate_autonomy_map,
            auxiliary_dir=context.prior_stage_dir("S06") / "auxiliary",
            repair_hints_path=context.prior_stage_dir("S05") / "prompts.json",
            person_bbox_xyxy=local_person_box,
            pose_path=context.prior_stage_dir("S04") / "pose133.json",
            context_origin_xy=(int(context_box[0]), int(context_box[1])),
        )
""",
            """        autonomy_allow_autonomous_profile = os.environ.get(
            "MASKFACTORY_AUTONOMY_ALLOW_AUTONOMOUS_PROFILE", ""
        ).strip().lower() in {"1", "true", "yes", "on"}
        status = run_s11_production(
            source_crop_path=s01_dir / instance_name / "person_ctx.png",
            part_map_path=context.prior_stage_dir("S09") / "label_map_part.png",
            s10_report_path=context.prior_stage_dir("S10") / "qa_report.json",
            output_dir=context.output_dir,
            gate_path=ROOT / "qa/vlm_eval/results/production_gate.json",
            failure_queue_path=ROOT / "qa/failure_queue.jsonl",
            pose_angle=str(pose["view"]),
            failure_instance_id=instance_name,
            workhorse_enabled=True,
            auto_load_correction_refiner=True,
            map_qa_validator=validate_autonomy_map,
            auxiliary_dir=context.prior_stage_dir("S06") / "auxiliary",
            repair_hints_path=context.prior_stage_dir("S05") / "prompts.json",
            person_bbox_xyxy=local_person_box,
            pose_path=context.prior_stage_dir("S04") / "pose133.json",
            context_origin_xy=(int(context_box[0]), int(context_box[1])),
            autonomy_allow_autonomous_profile=autonomy_allow_autonomous_profile,
        )
""",
            "stages-s11-autonomous-profile",
        )
    )

    # Intentionally do not mutate models/__init__.py — concurrent agents clobber it.
    # Callers import mark_benchmarked_candidate from maskfactory.models.benchmark.

    results.append(
        _patch(
            ROOT / "tools/build_autonomous_gold_admission.py",
            """def scan_verified_candidates(machine_root: Path) -> dict[str, Any]:
    root = Path(machine_root)
    verified = 0
    calibrated = 0
    total = 0
    if root.is_dir():
        for path in root.rglob("*.json"):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            status = doc.get("status")
            if status == "machine_verified_candidate":
                total += 1
                verified += 1
            elif status == "calibrated_auto_accepted":
                total += 1
                calibrated += 1
    return {
        "machine_root": str(root),
        "machine_verified_candidate_count": verified,
        "calibrated_auto_accepted_count": calibrated,
        "lifecycle_sidecars_seen": total,
    }
""",
            """def scan_verified_candidates(machine_root: Path) -> dict[str, Any]:
    \"\"\"Scan only autonomy lifecycle sidecars (not every JSON under runs/).\"\"\"
    from maskfactory.autonomy.corpus import scan_lifecycle_pool

    return scan_lifecycle_pool(Path(machine_root))
""",
            "admission-scan-lifecycle",
        )
    )

    benchmark_mod = ROOT / "src/maskfactory/models/benchmark.py"
    if benchmark_mod.is_file() and "def mark_benchmarked_candidate(" in benchmark_mod.read_text(
        encoding="utf-8"
    ):
        results.append("benchmark-module: present")
    else:
        results.append("benchmark-module: MISSING")

    # CLI mark-benchmarked command
    cli = ROOT / "src/maskfactory/cli.py"
    cli_text = cli.read_text(encoding="utf-8")
    if "@models.command(\"mark-benchmarked\")" in cli_text:
        results.append("cli-mark-benchmarked: already-applied")
    else:
        anchor = '@models.command("champions")'
        if anchor not in cli_text:
            results.append("cli-mark-benchmarked: ANCHOR-MISSING")
        else:
            cmd = '''
@models.command("mark-benchmarked")
@click.argument("candidate_key")
@click.option(
    "--certificate",
    "certificate_path",
    type=click.Path(path_type=Path, dir_okay=False, exists=True),
    required=True,
    help="Validated custom-segmenter promotion certificate (lifecycle_state=benchmarked).",
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
def models_mark_benchmarked(
    candidate_key: str, certificate_path: Path, registry_path: Path, models_root: Path
) -> None:
    """Raise an installed challenger to lifecycle benchmarked (never assigns champion_*)."""
    from .models.benchmark import mark_benchmarked_candidate

    try:
        entry = mark_benchmarked_candidate(
            candidate_key,
            certificate=certificate_path,
            registry_path=registry_path,
            models_root=models_root,
        )
    except (OSError, ValueError, json.JSONDecodeError, ModelRegistryError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"{entry['key']}: role={entry['role']} lifecycle_state={entry['lifecycle_state']} "
        f"benchmarked_at={entry.get('benchmarked_at')}"
    )


'''
            cli.write_text(cli_text.replace(anchor, cmd + anchor, 1), encoding="utf-8")
            results.append("cli-mark-benchmarked: applied")

    results.append(
        _ensure_contains(
            ROOT / "src/maskfactory/autonomy/corpus.py",
            "def assemble_autonomous_verification_corpus",
            "corpus-module",
        )
    )
    results.append(
        _ensure_contains(
            ROOT / "tools/run_measured_champions_path.py",
            "measured_champions_path_production",
            "orchestrator-tool",
        )
    )

    for line in results:
        print(line)
    bad = [line for line in results if "ANCHOR-MISSING" in line or line.endswith(": MISSING")]
    return 0 if not bad else 3


if __name__ == "__main__":
    raise SystemExit(main())
