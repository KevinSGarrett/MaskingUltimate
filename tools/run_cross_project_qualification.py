"""Run or validate MF-P6-12.05 producer cross-project qualification matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.bridge.cross_project_qualification import (
    EXTERNAL_MAIN_DEPENDENCIES,
    build_cross_project_qualification_evidence,
    run_cross_project_qualification,
    validate_cross_project_qualification_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", type=Path, required=False)
    parser.add_argument("--output", type=Path, required=False)
    parser.add_argument("--observation", type=Path, required=False)
    parser.add_argument("--decided-at", default="2026-07-19T20:00:00Z")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--list-main-dependencies", action="store_true")
    parser.add_argument(
        "--allow-producer-partial",
        action="store_true",
        help="Exit 0 when status is producer_partial (default for producer demos).",
    )
    args = parser.parse_args()

    if args.list_main_dependencies:
        print(
            json.dumps({"external_main_dependencies": list(EXTERNAL_MAIN_DEPENDENCIES)}, indent=2)
        )
        return 0

    if args.verify:
        if args.output is None:
            raise SystemExit("--output is required with --verify")
        evidence = json.loads(args.output.read_text(encoding="utf-8"))
        issues = validate_cross_project_qualification_evidence(evidence)
        if issues:
            raise SystemExit(f"cross project qualification evidence invalid: {', '.join(issues)}")
    else:
        observation = None
        if args.observation is not None:
            observation = json.loads(args.observation.read_text(encoding="utf-8"))
        if args.workdir is not None:
            evidence = run_cross_project_qualification(
                args.workdir,
                observation=observation,
                decided_at=args.decided_at,
            )
            output = args.output or (args.workdir / "cross_project_qualification_evidence.json")
        else:
            evidence = build_cross_project_qualification_evidence(
                observation, decided_at=args.decided_at
            )
            if args.output is None:
                raise SystemExit("--output or --workdir is required")
            output = args.output
        issues = validate_cross_project_qualification_evidence(evidence)
        if issues:
            raise SystemExit(f"cross project qualification evidence invalid: {', '.join(issues)}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "status": evidence["status"],
                "decision_sha256": evidence["decision_sha256"],
                "producer_matrix_executable": evidence["claim_boundary"][
                    "producer_matrix_executable"
                ],
                "mf_p6_12_05_complete": evidence["claim_boundary"]["mf_p6_12_05_complete"],
                "establishes_production_qualification": evidence["claim_boundary"][
                    "establishes_production_qualification"
                ],
                "rejection_reasons": evidence["rejection_reasons"],
                "failed_matrix_rows": [
                    row["row_id"]
                    for row in evidence["matrix_results"]
                    if row.get("result") != "pass"
                ],
                "external_main_prerequisites": evidence["external_main_prerequisites"],
                "remaining_blockers": [
                    "accepted_mf_p6_12_01_through_12_04_production_inputs",
                    "pinned_main_runtime_git_commit",
                    "main_adoption_receipt",
                    "main_qualification_bundle_signature",
                    "main_adapter_execution_receipt",
                    "comfyui_result_history_receipt",
                    "release_capability_requirements_hashes",
                    "currency_policy_pass_with_benchmark_and_rollback_evidence",
                ],
            },
            sort_keys=True,
        )
    )
    if evidence["status"] == "accepted":
        return 0
    if evidence["status"] == "producer_partial" and args.allow_producer_partial:
        return 0
    if evidence["status"] == "producer_partial":
        return 0  # producer-owned progress is the expected terminal for this slice
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
