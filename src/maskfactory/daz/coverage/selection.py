"""Hard-gated deterministic utility scoring for DAZ candidate batches."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import yaml

from ...validation import require_valid_document
from .candidates import validate_candidate_batch

SHA256 = re.compile(r"^[0-9a-f]{64}$")
TOKEN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
EXPECTED_POLICY_SHA256 = "ecd14f52d077d8c4d45c4e45d4a107f43567fb2cd3354d517290933fb9e2ea1b"
FEATURES = (
    "canonical_coverage_deficit_gain",
    "high_risk_intersection_gain",
    "label_visibility_gain",
    "asset_diversity_gain",
    "failure_mining_priority",
    "domain_randomization_gain",
    "multi_person_identity_gain",
    "recency_need",
)
PENALTIES = (
    "incompatibility_penalty",
    "dominance_penalty",
    "recent_repetition_penalty",
    "predicted_rejection_cost",
)
GATES = (
    "registry_complete",
    "mapping_eligible",
    "compatibility_eligible",
    "capacity_eligible",
    "ontology_eligible",
)


class CandidateSelectionError(ValueError):
    """Utility policy, qualification input, selection report, or publication is invalid."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


def load_candidate_utility_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_candidate_utility_policy(document)
    return document


def validate_candidate_utility_policy(policy: Mapping[str, Any]) -> None:
    if not isinstance(policy, Mapping) or set(policy) != {
        "schema_version",
        "ranker_version",
        "positive_weights",
        "penalties",
        "hard_constraints",
        "ranking",
        "authority",
        "publication",
    }:
        raise CandidateSelectionError("candidate_utility_policy_fields_invalid", str(policy))
    if policy["schema_version"] != "1.0.0" or policy["ranker_version"] != "1.0.0":
        raise CandidateSelectionError("candidate_utility_policy_identity_invalid", str(policy))
    if (
        policy["positive_weights"]
        != dict(zip(FEATURES, (0.30, 0.20, 0.15, 0.10, 0.10, 0.05, 0.05, 0.05), strict=True))
        or sum(policy["positive_weights"].values()) != 1.0
    ):
        raise CandidateSelectionError("candidate_utility_weights_invalid", str(policy))
    if policy["penalties"] != list(PENALTIES) or policy["hard_constraints"] != list(GATES):
        raise CandidateSelectionError("candidate_utility_terms_invalid", str(policy))
    if policy["ranking"] != {
        "order": ["utility_desc", "asset_diversity_gain_desc", "candidate_id_asc"],
        "select_count": 1,
        "nonfinite_rejected": True,
        "all_infeasible_is_honest_unsatisfied": True,
    }:
        raise CandidateSelectionError("candidate_utility_ranking_invalid", str(policy))
    if policy["authority"] != {
        "stage": "technical_candidate_selection",
        "selection_is_recipe": False,
        "selection_is_render_authority": False,
        "selection_creates_gold": False,
        "synthetic_counts_close_real_deficits": False,
    } or policy["publication"] != {"immutable": True, "atomic": True}:
        raise CandidateSelectionError("candidate_utility_authority_invalid", str(policy))


def build_candidate_selection(
    *,
    candidate_batch: Mapping[str, Any],
    vocabulary_report: Mapping[str, Any],
    qualification_snapshot: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    validate_candidate_utility_policy(policy)
    validate_candidate_batch(candidate_batch, vocabulary_report=vocabulary_report)
    observations, snapshot_record = _validate_qualifications(
        qualification_snapshot, candidate_batch
    )
    rows = []
    for candidate in candidate_batch["candidates"]:
        observation = observations[candidate["candidate_id"]]
        gates = {
            "registry_complete": candidate["registry_complete"],
            **observation["hard_constraints"],
        }
        failures = [gate for gate in GATES if not gates[gate]]
        if failures:
            positive = penalty = utility = None
        else:
            positive = _rounded(
                sum(
                    policy["positive_weights"][name] * observation["features"][name]
                    for name in FEATURES
                )
            )
            penalty = _rounded(sum(observation["penalties"][name] for name in PENALTIES))
            utility = _rounded(positive - penalty)
        rows.append(
            {
                "candidate_id": candidate["candidate_id"],
                "features": dict(observation["features"]),
                "penalties": dict(observation["penalties"]),
                "hard_constraints": gates,
                "hard_failures": failures,
                "feasible": not failures,
                "positive_utility": positive,
                "penalty_total": penalty,
                "utility": utility,
                "rank": None,
                "selected": False,
            }
        )
    ranked = sorted(
        (row for row in rows if row["feasible"]),
        key=lambda row: (
            -row["utility"],
            -row["features"]["asset_diversity_gain"],
            row["candidate_id"],
        ),
    )
    for rank, row in enumerate(ranked, 1):
        row["rank"] = rank
    selected_id = ranked[0]["candidate_id"] if ranked else None
    if ranked:
        ranked[0]["selected"] = True
    failure_counts = Counter(reason for row in rows for reason in row["hard_failures"])
    summary = {
        "candidate_count": len(rows),
        "feasible_count": len(ranked),
        "infeasible_count": len(rows) - len(ranked),
        "scored_count": len(ranked),
        "selected_count": int(selected_id is not None),
        "hard_failure_counts": dict(sorted(failure_counts.items())),
        "maximum_utility": ranked[0]["utility"] if ranked else None,
    }
    content = {
        "ranker_version": policy["ranker_version"],
        "policy_sha256": _sha(policy),
        "candidate_batch": {
            "batch_id": candidate_batch["batch_id"],
            "batch_sha256": candidate_batch["batch_sha256"],
            "demand_id": candidate_batch["demand"]["demand_id"],
        },
        "qualification_snapshot": snapshot_record,
        "rows": rows,
        "selected_candidate_id": selected_id,
        "satisfied": selected_id is not None,
        "summary": summary,
        "authority": dict(policy["authority"]),
        "publication": dict(policy["publication"]),
    }
    digest = _sha(content)
    report = {
        "schema_version": "1.0.0",
        "selection_id": f"dcsr_{digest[:24]}",
        "selection_sha256": digest,
        **content,
    }
    validate_candidate_selection(
        report, candidate_batch=candidate_batch, vocabulary_report=vocabulary_report
    )
    return report


def validate_candidate_selection(
    report: Mapping[str, Any],
    *,
    candidate_batch: Mapping[str, Any],
    vocabulary_report: Mapping[str, Any],
) -> None:
    require_valid_document(report, "daz_candidate_selection_report")
    validate_candidate_batch(candidate_batch, vocabulary_report=vocabulary_report)
    _verify(report)
    if report["policy_sha256"] != EXPECTED_POLICY_SHA256:
        raise CandidateSelectionError(
            "candidate_selection_policy_hash_invalid", report["selection_id"]
        )
    expected_batch = {
        "batch_id": candidate_batch["batch_id"],
        "batch_sha256": candidate_batch["batch_sha256"],
        "demand_id": candidate_batch["demand"]["demand_id"],
    }
    if report["candidate_batch"] != expected_batch or [
        row["candidate_id"] for row in report["rows"]
    ] != [row["candidate_id"] for row in candidate_batch["candidates"]]:
        raise CandidateSelectionError("candidate_selection_binding_invalid", report["selection_id"])
    qualification = report["qualification_snapshot"]
    reconstructed_rows = [
        {
            "candidate_id": row["candidate_id"],
            "features": row["features"],
            "penalties": row["penalties"],
            "hard_constraints": {gate: row["hard_constraints"][gate] for gate in GATES[1:]},
        }
        for row in report["rows"]
    ]
    if qualification["snapshot_sha256"] != _sha(
        {
            "snapshot_id": qualification["snapshot_id"],
            "source": qualification["source"],
            "rows": reconstructed_rows,
        }
    ):
        raise CandidateSelectionError(
            "candidate_selection_qualification_hash_invalid", report["selection_id"]
        )
    batch_by_id = {row["candidate_id"]: row for row in candidate_batch["candidates"]}
    feasible = []
    failures = Counter()
    for row in report["rows"]:
        if (
            set(row["features"]) != set(FEATURES)
            or set(row["penalties"]) != set(PENALTIES)
            or any(
                not math.isfinite(value) or not 0 <= value <= 1
                for value in (*row["features"].values(), *row["penalties"].values())
            )
        ):
            raise CandidateSelectionError("candidate_selection_values_invalid", row["candidate_id"])
        gates = row["hard_constraints"]
        expected_failures = [gate for gate in GATES if not gates[gate]]
        positive = _rounded(
            sum(
                dict(zip(FEATURES, (0.30, 0.20, 0.15, 0.10, 0.10, 0.05, 0.05, 0.05), strict=True))[
                    name
                ]
                * row["features"][name]
                for name in FEATURES
            )
        )
        penalty = _rounded(sum(row["penalties"].values()))
        expected_values = (
            (positive, penalty, _rounded(positive - penalty))
            if not expected_failures
            else (None, None, None)
        )
        if (
            gates["registry_complete"] != batch_by_id[row["candidate_id"]]["registry_complete"]
            or row["hard_failures"] != expected_failures
            or row["feasible"] != (not expected_failures)
            or (row["positive_utility"], row["penalty_total"], row["utility"]) != expected_values
        ):
            raise CandidateSelectionError(
                "candidate_selection_semantics_invalid", row["candidate_id"]
            )
        failures.update(expected_failures)
        if not expected_failures:
            feasible.append(row)
    ranked = sorted(
        feasible,
        key=lambda row: (
            -row["utility"],
            -row["features"]["asset_diversity_gain"],
            row["candidate_id"],
        ),
    )
    selected_id = ranked[0]["candidate_id"] if ranked else None
    for rank, row in enumerate(ranked, 1):
        if row["rank"] != rank or row["selected"] != (rank == 1):
            raise CandidateSelectionError(
                "candidate_selection_ranking_invalid", row["candidate_id"]
            )
    if any(
        row["rank"] is not None or row["selected"] for row in report["rows"] if not row["feasible"]
    ):
        raise CandidateSelectionError(
            "candidate_selection_infeasible_ranked", report["selection_id"]
        )
    expected_summary = {
        "candidate_count": len(report["rows"]),
        "feasible_count": len(ranked),
        "infeasible_count": len(report["rows"]) - len(ranked),
        "scored_count": len(ranked),
        "selected_count": int(selected_id is not None),
        "hard_failure_counts": dict(sorted(failures.items())),
        "maximum_utility": ranked[0]["utility"] if ranked else None,
    }
    if (
        report["selected_candidate_id"] != selected_id
        or report["satisfied"] != (selected_id is not None)
        or report["summary"] != expected_summary
    ):
        raise CandidateSelectionError("candidate_selection_summary_invalid", report["selection_id"])


def publish_candidate_selection(
    report: Mapping[str, Any],
    output_root: Path,
    *,
    candidate_batch: Mapping[str, Any],
    vocabulary_report: Mapping[str, Any],
) -> tuple[Path, bool]:
    validate_candidate_selection(
        report, candidate_batch=candidate_batch, vocabulary_report=vocabulary_report
    )
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{report['selection_id']}.json"
    payload = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != payload:
            raise CandidateSelectionError("candidate_selection_publication_conflict", str(target))
        return target, False
    descriptor, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=root)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target, True


def _validate_qualifications(
    snapshot: Mapping[str, Any], batch: Mapping[str, Any]
) -> tuple[dict[str, Mapping[str, Any]], dict[str, Any]]:
    if (
        not isinstance(snapshot, Mapping)
        or set(snapshot) != {"snapshot_id", "snapshot_sha256", "source", "rows"}
        or not TOKEN.fullmatch(str(snapshot.get("snapshot_id")))
        or snapshot.get("source") != "versioned_d3_d5_feasibility_observations"
        or not SHA256.fullmatch(str(snapshot.get("snapshot_sha256")))
    ):
        raise CandidateSelectionError("candidate_qualification_snapshot_invalid", str(snapshot))
    content = {
        "snapshot_id": snapshot["snapshot_id"],
        "source": snapshot["source"],
        "rows": snapshot["rows"],
    }
    if snapshot["snapshot_sha256"] != _sha(content) or not isinstance(snapshot["rows"], list):
        raise CandidateSelectionError(
            "candidate_qualification_hash_invalid", str(snapshot.get("snapshot_id"))
        )
    rows = {}
    expected_ids = [row["candidate_id"] for row in batch["candidates"]]
    for row in snapshot["rows"]:
        if (
            not isinstance(row, Mapping)
            or set(row) != {"candidate_id", "features", "penalties", "hard_constraints"}
            or row["candidate_id"] in rows
            or set(row["features"]) != set(FEATURES)
            or set(row["penalties"]) != set(PENALTIES)
            or set(row["hard_constraints"]) != set(GATES[1:])
            or any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or not 0 <= value <= 1
                for value in (*row["features"].values(), *row["penalties"].values())
            )
            or any(not isinstance(value, bool) for value in row["hard_constraints"].values())
        ):
            raise CandidateSelectionError("candidate_qualification_row_invalid", str(row))
        rows[row["candidate_id"]] = row
    if list(rows) != expected_ids:
        raise CandidateSelectionError("candidate_qualification_rows_incomplete", str(len(rows)))
    record = {
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_sha256": snapshot["snapshot_sha256"],
        "source": snapshot["source"],
    }
    return rows, record


def _rounded(value: float) -> float:
    if not math.isfinite(value):
        raise CandidateSelectionError("candidate_utility_nonfinite", str(value))
    return round(value, 12)


def _sha(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def _verify(report: Mapping[str, Any]) -> None:
    content = {
        key: value
        for key, value in report.items()
        if key not in {"schema_version", "selection_id", "selection_sha256"}
    }
    digest = _sha(content)
    if report["selection_sha256"] != digest or report["selection_id"] != f"dcsr_{digest[:24]}":
        raise CandidateSelectionError(
            "candidate_selection_hash_invalid", str(report.get("selection_id"))
        )
