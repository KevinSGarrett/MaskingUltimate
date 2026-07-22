#!/usr/bin/env python3
"""Operate the durable RunPod autonomous work-cell queue."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from maskfactory.autonomy.work_cell import AutonomousWorkCell
from maskfactory.autonomy.work_cell_command_handlers import CommandStageHandler
from maskfactory.autonomy.work_cell_runner import WorkCellRunner


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class _ManifestStageHandler:
    def __init__(self, implementation_sha256: str, function: Any) -> None:
        self.implementation_sha256 = implementation_sha256
        self._function = function

    def __call__(self, work: dict[str, Any]) -> Any:
        return self._function(work)


def _load_handlers(path: Path) -> dict[str, Any]:
    document = _read(path)
    schema_path = (
        Path(__file__).parents[1]
        / "src"
        / "maskfactory"
        / "schemas"
        / "runpod_work_cell_handlers.schema.json"
    )
    schema = _read(schema_path)
    problems = sorted(
        Draft202012Validator(schema).iter_errors(document), key=lambda item: list(item.path)
    )
    if problems:
        pointer = "/".join(str(part) for part in problems[0].path)
        raise SystemExit(
            f"handler manifest schema invalid at {pointer or '<root>'}: {problems[0].message}"
        )
    handlers = document.get("handlers")
    if not isinstance(handlers, dict):
        raise SystemExit("handler manifest requires object handlers")

    loaded: dict[str, Any] = {}
    base = path.parent
    for stage, spec in handlers.items():
        if not isinstance(spec, dict):
            raise SystemExit(f"handler spec invalid: {stage}")
        if spec["kind"] == "subprocess_json":
            try:
                loaded[stage] = CommandStageHandler.from_spec(stage, spec, base=base)
            except Exception as exc:
                raise SystemExit(str(exc)) from exc
            continue
        source_path = spec.get("source_path")
        callable_name = spec.get("callable")
        implementation_sha256 = spec.get("implementation_sha256")
        if (
            not isinstance(source_path, str)
            or not isinstance(callable_name, str)
            or not isinstance(implementation_sha256, str)
            or len(implementation_sha256) != 64
        ):
            raise SystemExit(f"handler binding fields invalid: {stage}")
        resolved_source = Path(source_path)
        if not resolved_source.is_absolute():
            resolved_source = base / resolved_source
        resolved_source = resolved_source.resolve()
        if _sha256_file(resolved_source) != implementation_sha256:
            raise SystemExit(f"handler source hash mismatch: {stage}")

        module_name = f"maskfactory_runpod_stage_{stage}_{implementation_sha256[:12]}"
        module_spec = importlib.util.spec_from_file_location(module_name, resolved_source)
        if module_spec is None or module_spec.loader is None:
            raise SystemExit(f"handler source cannot be loaded: {stage}")
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_name] = module
        module_spec.loader.exec_module(module)
        function = getattr(module, callable_name, None)
        if not callable(function):
            raise SystemExit(f"handler callable missing: {stage}")
        loaded[stage] = _ManifestStageHandler(implementation_sha256, function)
    return loaded


def _write_milestone_snapshot(output_dir: Path, report: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    count = int(report["terminal_record_count"])
    path = output_dir / f"{report['mission_id']}_terminal_{count:08d}.json"
    if path.exists():
        existing = _read(path)
        if existing != report:
            raise SystemExit(f"milestone snapshot collision: {path}")
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)

    admit = commands.add_parser("admit")
    admit.add_argument("--manifest", type=Path, required=True)

    seed = commands.add_parser("seed")
    seed.add_argument("--mission-id", required=True)
    seed.add_argument("--records", type=Path, required=True)

    claim = commands.add_parser("claim")
    claim.add_argument("--mission-id", required=True)
    claim.add_argument("--owner", required=True)

    heartbeat = commands.add_parser("heartbeat")
    heartbeat.add_argument("--mission-id", required=True)
    heartbeat.add_argument("--record-id", required=True)
    heartbeat.add_argument("--lease-token", required=True)

    result = commands.add_parser("result")
    result.add_argument("--mission-id", required=True)
    result.add_argument("--record-id", required=True)
    result.add_argument("--lease-token", required=True)
    result.add_argument("--receipt", type=Path, required=True)

    recover = commands.add_parser("recover")
    recover.add_argument("--mission-id", required=True)

    run = commands.add_parser("run")
    run.add_argument("--mission-id", required=True)
    run.add_argument("--owner", required=True)
    run.add_argument("--handlers", type=Path, required=True)
    run.add_argument("--failure-root", type=Path)
    run.add_argument("--milestone-output-dir", type=Path)
    run.add_argument("--max-stage-operations", type=int)
    run.add_argument("--idle-polls", type=int, default=1)
    run.add_argument("--idle-seconds", type=float, default=0.0)

    report = commands.add_parser("report")
    report.add_argument("--mission-id", required=True)
    report.add_argument("--output", type=Path)

    args = parser.parse_args()
    cell = AutonomousWorkCell(args.root)
    if args.command == "admit":
        output = cell.admit(_read(args.manifest))
    elif args.command == "seed":
        output = cell.seed_records(args.mission_id, _read(args.records))
    elif args.command == "claim":
        output = cell.claim(args.mission_id, owner=args.owner)
    elif args.command == "heartbeat":
        output = {
            "lease_expires_at": cell.heartbeat(args.mission_id, args.record_id, args.lease_token)
        }
    elif args.command == "result":
        output = cell.apply_result(
            args.mission_id, args.record_id, args.lease_token, _read(args.receipt)
        )
    elif args.command == "recover":
        output = cell.recover_expired(args.mission_id)
    elif args.command == "run":
        milestone_callback = (
            (lambda report: _write_milestone_snapshot(args.milestone_output_dir, dict(report)))
            if args.milestone_output_dir
            else None
        )
        runner = WorkCellRunner(
            cell,
            _load_handlers(args.handlers),
            owner=args.owner,
            failure_root=args.failure_root,
            milestone_callback=milestone_callback,
        )
        output = runner.run(
            args.mission_id,
            max_stage_operations=args.max_stage_operations,
            idle_polls=args.idle_polls,
            idle_seconds=args.idle_seconds,
        )
    else:
        output = (
            cell.write_report(args.mission_id, args.output)
            if args.output
            else cell.report(args.mission_id)
        )
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
