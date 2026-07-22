"""Fail-closed semantic alignment for autonomous-certified training packages.

Structural mask QA and multi-provider pixel consensus cannot prove that a mask
represents the label written beside it.  This module binds each package to a
package-specific, current, independent self-hosted critic quorum before the
package may be frozen or consumed as autonomous-certified training truth.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from ..io.hashing import sha256_file, sha256_file_map
from ..io.png_strict import read_mask, write_label_map
from ..ontology import OntologyError, load_ontology

SHA256 = re.compile(r"^[a-f0-9]{64}$")
REPORT_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "authority_claimed",
        "package_identity",
        "targets",
        "deterministic_hard_veto",
        "deterministic_qa_sha256",
        "panel_set_sha256",
        "critic_decisions",
        "quorum_sha256",
        "report_sha256",
    }
)
IDENTITY_KEYS = frozenset(
    {
        "image_id",
        "instance_id",
        "ontology_version",
        "source_sha256",
        "final_mask_set_sha256",
    }
)
TARGET_KEYS = frozenset({"label_id", "mask_sha256", "verdict", "decision_sha256"})
DECISION_KEYS = frozenset(
    {
        "certificate_sha256",
        "role_id",
        "model_id",
        "family_id",
        "verdict",
        "cited_labels",
        "decision_sha256",
    }
)
BATCH_REVIEW_KEYS = frozenset(
    {
        "schema_version",
        "plan_sha256",
        "batch_sha256",
        "role_id",
        "certificate_sha256",
        "model_id",
        "family_id",
        "case_decisions",
        "review_sha256",
    }
)
BATCH_CASE_DECISION_KEYS = frozenset({"case_id", "targets", "decision_sha256"})
BATCH_TARGET_DECISION_KEYS = frozenset(
    {
        "label_id",
        "mask_sha256",
        "panel_sha256",
        "verdict",
        "proposed_label_id",
    }
)
BATCH_TARGET_VERDICTS = frozenset({"pass", "relabel", "reject", "abstain"})


class PackageSemanticAlignmentError(ValueError):
    """A package-specific label/pixel alignment proof is absent or invalid."""


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise PackageSemanticAlignmentError(f"{field} must be a SHA-256")
    return value


def semantic_alignment_report_sha256(report: Mapping[str, Any]) -> str:
    """Return the canonical self-hash for a semantic-alignment report."""

    return _canonical_sha256(
        {key: value for key, value in report.items() if key != "report_sha256"}
    )


def deterministic_qa_sha256(results: Sequence[Any]) -> str:
    """Bind the exact deterministic QC rows that preceded semantic review."""

    rows = []
    for result in results:
        if hasattr(result, "__dataclass_fields__"):
            rows.append(asdict(result))
        elif isinstance(result, Mapping):
            rows.append(dict(result))
        else:
            raise PackageSemanticAlignmentError("deterministic QA row is not serializable")
    return _canonical_sha256(rows)


def final_mask_set_sha256(package_root: Path, manifest: Mapping[str, Any]) -> str:
    """Hash authoritative maps and every active part mask exactly as S13 does."""

    package = Path(package_root)
    paths = [
        package / name
        for name in ("label_map_part.png", "label_map_material.png")
        if (package / name).is_file()
    ]
    for entry in manifest.get("parts", {}).values():
        relative = entry.get("mask_file") if isinstance(entry, Mapping) else None
        if isinstance(relative, str) and (package / relative).is_file():
            paths.append(package / relative)
    file_map = sha256_file_map(package, paths)
    return hashlib.sha256(
        json.dumps(file_map, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _package_source(package: Path) -> Path:
    for name in ("source.png", "source.jpg", "source.jpeg", "source.webp"):
        path = package / name
        if path.is_file():
            return path
    raise PackageSemanticAlignmentError("semantic alignment package source is missing")


def _instance_id(package: Path) -> str:
    return package.name if package.parent.name == "instances" else "p0"


def _active_target_rows(package: Path, manifest: Mapping[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for label, entry in sorted((manifest.get("parts") or {}).items()):
        if (
            not isinstance(entry, Mapping)
            or entry.get("status") == "n/a"
            or not isinstance(entry.get("mask_file"), str)
        ):
            continue
        mask_relative = str(entry["mask_file"])
        mask = package / mask_relative
        if not mask.is_file():
            raise PackageSemanticAlignmentError(f"active mask is missing: {mask_relative}")
        panel_relative = f"qa_panels/{Path(mask_relative).stem}.png"
        panel = package / panel_relative
        if not panel.is_file():
            raise PackageSemanticAlignmentError(
                f"label-aware QA panel is missing: {panel_relative}"
            )
        rows.append(
            {
                "label_id": str(label),
                "mask_file": mask_relative.replace("\\", "/"),
                "mask_sha256": sha256_file(mask),
                "panel_file": panel_relative,
                "panel_sha256": sha256_file(panel),
            }
        )
    if not rows:
        raise PackageSemanticAlignmentError("package has no active semantic targets")
    return rows


def build_semantic_requalification_plan(
    packages_root: Path,
    *,
    batch_size: int = 32,
) -> dict[str, Any]:
    """Build deterministic bulk critic work with compact exception handling.

    A malformed package becomes one exception row; it does not force an operator to
    restart or review the rest of the corpus one package at a time. The returned
    batches are provider-neutral and may be consumed by the promoted primary critic
    and independent-family juror without granting either model mask authority.
    """

    root = Path(packages_root)
    if not root.is_dir():
        raise PackageSemanticAlignmentError(f"semantic requalification root is missing: {root}")
    if not 1 <= batch_size <= 128:
        raise PackageSemanticAlignmentError("semantic batch_size must be 1..128")

    candidates = sorted(root.glob("img_*/instances/p*"))
    candidates.extend(
        sorted(path for path in root.glob("img_*") if (path / "manifest.json").is_file())
    )
    cases: list[dict[str, Any]] = []
    exceptions: list[dict[str, str]] = []
    for package in candidates:
        relative = package.relative_to(root).as_posix()
        try:
            manifest_path = package / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            source = _package_source(package)
            targets = _active_target_rows(package, manifest)
            lineage_path = package / "caa_lineage.json"
            lineage_sha256 = sha256_file(lineage_path) if lineage_path.is_file() else None
            case = {
                "case_id": _canonical_sha256(
                    {
                        "package": relative,
                        "manifest_sha256": sha256_file(manifest_path),
                        "source_sha256": sha256_file(source),
                        "targets": targets,
                    }
                )[:24],
                "package": relative,
                "image_id": str(manifest.get("image_id", package.parents[1].name)),
                "instance_id": _instance_id(package),
                "current_truth_tier": str(manifest.get("truth_tier", "unknown")),
                "manifest_sha256": sha256_file(manifest_path),
                "lineage_sha256": lineage_sha256,
                "source_file": source.relative_to(package).as_posix(),
                "source_sha256": sha256_file(source),
                "targets": targets,
                "allowed_outcomes": [
                    "accept_exact_label",
                    "relabel_new_immutable_version",
                    "reject",
                    "abstain",
                ],
            }
            cases.append(case)
        except (OSError, json.JSONDecodeError, PackageSemanticAlignmentError) as exc:
            exceptions.append(
                {
                    "package": relative,
                    "reason": str(exc),
                    "action": "abstain_and_report",
                }
            )

    batches: list[dict[str, Any]] = []
    for offset in range(0, len(cases), batch_size):
        batch_cases = cases[offset : offset + batch_size]
        batch = {
            "batch_index": len(batches),
            "required_roles": ["primary_visual_critic", "independent_juror"],
            "case_ids": [case["case_id"] for case in batch_cases],
        }
        batch["batch_sha256"] = _canonical_sha256(batch)
        batches.append(batch)

    plan: dict[str, Any] = {
        "schema_version": "1.0.0",
        "authority_claimed": False,
        "execution_mode": "bulk_by_default",
        "packages_root": root.as_posix(),
        "batch_size": batch_size,
        "case_count": len(cases),
        "exception_count": len(exceptions),
        "operator_interruption_policy": "compact_exception_report_only",
        "human_review_policy": "optional_exception_path_not_default_throughput",
        "mutation_policy": "never_mutate_frozen_package; publish_new_version_only",
        "cases": cases,
        "batches": batches,
        "exceptions": exceptions,
    }
    plan["plan_sha256"] = _canonical_sha256(plan)
    return plan


def render_semantic_requalification_contact_sheets(
    plan: Mapping[str, Any],
    *,
    packages_root: Path,
    output_root: Path,
    columns: int = 4,
    tile_width: int = 480,
) -> dict[str, Any]:
    """Render compact batch overviews without replacing authoritative panels."""

    expected_plan_sha256 = _canonical_sha256(
        {key: value for key, value in plan.items() if key != "plan_sha256"}
    )
    if plan.get("plan_sha256") != expected_plan_sha256:
        raise PackageSemanticAlignmentError("semantic bulk plan hash mismatch")
    if not 1 <= columns <= 8 or not 160 <= tile_width <= 1024:
        raise PackageSemanticAlignmentError("contact-sheet geometry is out of bounds")

    packages = Path(packages_root)
    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)
    cases = {
        str(case["case_id"]): case
        for case in plan.get("cases", ())
        if isinstance(case, Mapping) and isinstance(case.get("case_id"), str)
    }
    sheets: list[dict[str, Any]] = []
    for batch in plan.get("batches", ()):
        if not isinstance(batch, Mapping):
            raise PackageSemanticAlignmentError("semantic batch row is invalid")
        tiles: list[tuple[Image.Image, str, str]] = []
        for case_id in batch.get("case_ids", ()):
            case = cases.get(str(case_id))
            if case is None:
                raise PackageSemanticAlignmentError(
                    f"contact-sheet case is missing from plan: {case_id}"
                )
            targets = case.get("targets")
            if not isinstance(targets, Sequence) or not targets:
                raise PackageSemanticAlignmentError(f"contact-sheet case has no targets: {case_id}")
            first = targets[0]
            if not isinstance(first, Mapping):
                raise PackageSemanticAlignmentError(f"contact-sheet target is invalid: {case_id}")
            panel = packages / str(case["package"]) / str(first["panel_file"])
            if not panel.is_file() or sha256_file(panel) != first.get("panel_sha256"):
                raise PackageSemanticAlignmentError(
                    f"contact-sheet panel is missing or drifted: {case_id}"
                )
            with Image.open(panel) as opened:
                rendered = opened.convert("RGB")
            height = max(1, round(rendered.height * tile_width / rendered.width))
            rendered = rendered.resize(
                (tile_width, height),
                Image.Resampling.LANCZOS,
            )
            labels = [
                str(target.get("label_id")) for target in targets if isinstance(target, Mapping)
            ]
            tiles.append(
                (
                    rendered,
                    f"{case['image_id']} / {case['instance_id']}",
                    ", ".join(labels[:3]) + (f" +{len(labels) - 3}" if len(labels) > 3 else ""),
                )
            )

        header_height = 42
        tile_height = max((image.height for image, _, _ in tiles), default=1)
        rows = max(1, (len(tiles) + columns - 1) // columns)
        sheet = Image.new(
            "RGB",
            (columns * tile_width, rows * (header_height + tile_height)),
            "black",
        )
        draw = ImageDraw.Draw(sheet)
        for index, (tile, identity, labels) in enumerate(tiles):
            column = index % columns
            row = index // columns
            x = column * tile_width
            y = row * (header_height + tile_height)
            draw.text((x + 6, y + 4), identity, fill="white")
            draw.text((x + 6, y + 22), labels, fill="#7CFC00")
            sheet.paste(tile, (x, y + header_height))

        batch_index = int(batch.get("batch_index", len(sheets)))
        path = output / f"batch_{batch_index:03d}.png"
        sheet.save(path, format="PNG", optimize=True)
        sheets.append(
            {
                "batch_index": batch_index,
                "batch_sha256": batch.get("batch_sha256"),
                "file": path.name,
                "sha256": sha256_file(path),
                "case_ids": list(batch.get("case_ids", ())),
                "width": sheet.width,
                "height": sheet.height,
                "purpose": "operator_overview_only; per-target panels remain authoritative",
            }
        )

    manifest: dict[str, Any] = {
        "schema_version": "1.0.0",
        "authority_claimed": False,
        "plan_sha256": plan["plan_sha256"],
        "sheet_count": len(sheets),
        "sheets": sheets,
    }
    manifest["manifest_sha256"] = _canonical_sha256(manifest)
    (output / "contact_sheet_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _without_self_hash(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != field}


def execute_semantic_requalification_batch(
    plan: Mapping[str, Any],
    *,
    batch_index: int,
    critic_reviews: Sequence[Mapping[str, Any]],
    critic_certificates: Sequence[Mapping[str, Any]],
    critic_catalog: Mapping[str, Any],
    packages_root: Path,
    now: datetime,
) -> dict[str, Any]:
    """Resolve one bulk batch without mutating any frozen package.

    Authority failures reject the whole batch. Package-specific drift or malformed
    decisions become compact exception rows so unrelated cases continue. Relabel
    outcomes are proposals for a new immutable version; this function never renames
    a label or writes mask pixels in place.
    """

    expected_plan_sha256 = _canonical_sha256(_without_self_hash(plan, "plan_sha256"))
    if plan.get("plan_sha256") != expected_plan_sha256:
        raise PackageSemanticAlignmentError("semantic bulk plan hash mismatch")
    batches = plan.get("batches")
    if not isinstance(batches, Sequence) or isinstance(batches, (str, bytes)):
        raise PackageSemanticAlignmentError("semantic bulk batches are invalid")
    if batch_index < 0 or batch_index >= len(batches):
        raise PackageSemanticAlignmentError("semantic bulk batch_index is invalid")
    batch = batches[batch_index]
    if not isinstance(batch, Mapping):
        raise PackageSemanticAlignmentError("semantic bulk batch row is invalid")
    expected_batch_sha256 = _canonical_sha256(_without_self_hash(batch, "batch_sha256"))
    if batch.get("batch_sha256") != expected_batch_sha256:
        raise PackageSemanticAlignmentError("semantic bulk batch hash mismatch")

    from ..vlm.critic_authority import CriticAuthorityError, evaluate_pass_quorum

    try:
        quorum = evaluate_pass_quorum(
            critic_certificates,
            critic_catalog,
            now=now,
            deterministic_hard_veto=False,
        )
    except CriticAuthorityError as exc:
        raise PackageSemanticAlignmentError(str(exc)) from exc
    if quorum.get("status") != "eligible":
        raise PackageSemanticAlignmentError("semantic bulk critic quorum is ineligible")

    certificates = {
        str(certificate.get("certificate_sha256")): certificate
        for certificate in critic_certificates
    }
    required_roles = set(batch.get("required_roles") or ())
    if required_roles != {"primary_visual_critic", "independent_juror"}:
        raise PackageSemanticAlignmentError("semantic bulk required roles drifted")
    reviews_by_role: dict[str, Mapping[str, Any]] = {}
    for review in critic_reviews:
        if not isinstance(review, Mapping) or set(review) != BATCH_REVIEW_KEYS:
            raise PackageSemanticAlignmentError("semantic bulk review fields are invalid")
        if review.get("schema_version") != "1.0.0":
            raise PackageSemanticAlignmentError("semantic bulk review schema is invalid")
        if (
            review.get("plan_sha256") != plan["plan_sha256"]
            or review.get("batch_sha256") != batch["batch_sha256"]
        ):
            raise PackageSemanticAlignmentError("semantic bulk review binding drifted")
        if review.get("review_sha256") != _canonical_sha256(
            _without_self_hash(review, "review_sha256")
        ):
            raise PackageSemanticAlignmentError("semantic bulk review hash mismatch")
        role = str(review.get("role_id"))
        certificate = certificates.get(str(review.get("certificate_sha256")))
        if role not in required_roles or role in reviews_by_role or certificate is None:
            raise PackageSemanticAlignmentError(
                "semantic bulk review role or certificate is unknown or duplicated"
            )
        if any(
            review.get(field) != certificate.get(field)
            for field in ("role_id", "model_id", "family_id")
        ):
            raise PackageSemanticAlignmentError("semantic bulk critic identity drifted")
        reviews_by_role[role] = review
    if set(reviews_by_role) != required_roles:
        raise PackageSemanticAlignmentError("semantic bulk reviews lack the required quorum")

    case_ids = [str(value) for value in batch.get("case_ids") or ()]
    cases = {
        str(case.get("case_id")): case
        for case in plan.get("cases") or ()
        if isinstance(case, Mapping)
    }
    review_cases: dict[str, dict[str, Mapping[str, Any]]] = {}
    for role, review in reviews_by_role.items():
        decisions = review.get("case_decisions")
        if not isinstance(decisions, Sequence) or isinstance(decisions, (str, bytes)):
            raise PackageSemanticAlignmentError("semantic bulk case decisions are invalid")
        role_cases: dict[str, Mapping[str, Any]] = {}
        for decision in decisions:
            if not isinstance(decision, Mapping) or set(decision) != BATCH_CASE_DECISION_KEYS:
                raise PackageSemanticAlignmentError(
                    "semantic bulk case decision fields are invalid"
                )
            case_id = str(decision.get("case_id"))
            if case_id in role_cases or case_id not in case_ids:
                raise PackageSemanticAlignmentError(
                    "semantic bulk case decision is unknown or duplicated"
                )
            if decision.get("decision_sha256") != _canonical_sha256(
                _without_self_hash(decision, "decision_sha256")
            ):
                raise PackageSemanticAlignmentError("semantic bulk case decision hash mismatch")
            role_cases[case_id] = decision
        if set(role_cases) != set(case_ids):
            raise PackageSemanticAlignmentError(
                "semantic bulk review does not cover the exact batch"
            )
        review_cases[role] = role_cases

    packages = Path(packages_root)
    outcomes: list[dict[str, Any]] = []
    exceptions: list[dict[str, str]] = []
    for case_id in case_ids:
        case = cases.get(case_id)
        if case is None:
            raise PackageSemanticAlignmentError(f"semantic bulk plan case is missing: {case_id}")
        try:
            package = packages / str(case["package"])
            manifest_path = package / "manifest.json"
            source = package / str(case["source_file"])
            if sha256_file(manifest_path) != case.get("manifest_sha256"):
                raise PackageSemanticAlignmentError("manifest hash drifted")
            if sha256_file(source) != case.get("source_sha256"):
                raise PackageSemanticAlignmentError("source hash drifted")
            target_rows = {
                str(target["label_id"]): target
                for target in case.get("targets") or ()
                if isinstance(target, Mapping)
            }
            if not target_rows:
                raise PackageSemanticAlignmentError("case has no semantic targets")
            decisions_by_role: dict[str, dict[str, Mapping[str, Any]]] = {}
            for role in sorted(required_roles):
                decision = review_cases[role][case_id]
                targets = decision.get("targets")
                if not isinstance(targets, Sequence) or isinstance(targets, (str, bytes)):
                    raise PackageSemanticAlignmentError("critic targets are invalid")
                observed: dict[str, Mapping[str, Any]] = {}
                for target in targets:
                    if not isinstance(target, Mapping) or set(target) != BATCH_TARGET_DECISION_KEYS:
                        raise PackageSemanticAlignmentError(
                            "critic target decision fields are invalid"
                        )
                    label = str(target.get("label_id"))
                    planned = target_rows.get(label)
                    if planned is None or label in observed:
                        raise PackageSemanticAlignmentError(
                            "critic target is unknown or duplicated"
                        )
                    if target.get("mask_sha256") != planned.get("mask_sha256") or target.get(
                        "panel_sha256"
                    ) != planned.get("panel_sha256"):
                        raise PackageSemanticAlignmentError(
                            "critic target mask or panel binding drifted"
                        )
                    verdict = target.get("verdict")
                    proposed = target.get("proposed_label_id")
                    if verdict not in BATCH_TARGET_VERDICTS:
                        raise PackageSemanticAlignmentError("critic target verdict is invalid")
                    if verdict == "relabel":
                        if not isinstance(proposed, str) or not proposed or proposed == label:
                            raise PackageSemanticAlignmentError(
                                "critic relabel proposal is invalid"
                            )
                    elif proposed is not None:
                        raise PackageSemanticAlignmentError(
                            "non-relabel critic target carries a proposed label"
                        )
                    mask_path = package / str(planned["mask_file"])
                    panel_path = package / str(planned["panel_file"])
                    if (
                        sha256_file(mask_path) != planned["mask_sha256"]
                        or sha256_file(panel_path) != planned["panel_sha256"]
                    ):
                        raise PackageSemanticAlignmentError(
                            "target mask or panel drifted after planning"
                        )
                    observed[label] = target
                if set(observed) != set(target_rows):
                    raise PackageSemanticAlignmentError("critic review does not cover every target")
                decisions_by_role[role] = observed

            relabel_map: dict[str, str] = {}
            outcome = "accept_exact_label"
            for label in sorted(target_rows):
                pair = [decisions_by_role[role][label] for role in sorted(required_roles)]
                verdicts = {str(value["verdict"]) for value in pair}
                if "reject" in verdicts:
                    outcome = "reject"
                    relabel_map = {}
                    break
                if "abstain" in verdicts or len(verdicts) != 1:
                    outcome = "abstain"
                    relabel_map = {}
                    break
                verdict = next(iter(verdicts))
                if verdict == "relabel":
                    proposals = {str(value["proposed_label_id"]) for value in pair}
                    if len(proposals) != 1:
                        outcome = "abstain"
                        relabel_map = {}
                        break
                    relabel_map[label] = next(iter(proposals))
                    outcome = "relabel_new_immutable_version"
            if len(set(relabel_map.values())) != len(relabel_map):
                outcome = "abstain"
                relabel_map = {}
            outcomes.append(
                {
                    "case_id": case_id,
                    "package": case["package"],
                    "outcome": outcome,
                    "relabel_map": relabel_map,
                    "source_sha256": case["source_sha256"],
                    "manifest_sha256": case["manifest_sha256"],
                }
            )
        except (KeyError, OSError, PackageSemanticAlignmentError) as exc:
            exceptions.append(
                {
                    "case_id": case_id,
                    "package": str(case.get("package", "unknown")),
                    "reason": str(exc),
                    "action": "abstain_and_report",
                }
            )

    counts = {
        outcome: sum(row["outcome"] == outcome for row in outcomes)
        for outcome in (
            "accept_exact_label",
            "relabel_new_immutable_version",
            "reject",
            "abstain",
        )
    }
    result: dict[str, Any] = {
        "schema_version": "1.0.0",
        "authority_claimed": False,
        "plan_sha256": plan["plan_sha256"],
        "batch_index": batch_index,
        "batch_sha256": batch["batch_sha256"],
        "quorum_sha256": quorum["quorum_sha256"],
        "mutation_performed": False,
        "outcomes": outcomes,
        "counts": counts,
        "exceptions": exceptions,
        "next_batch_index": batch_index + 1 if batch_index + 1 < len(batches) else None,
        "operator_report_policy": "compact_summary_and_exceptions_only",
    }
    result["result_sha256"] = _canonical_sha256(result)
    return result


def publish_semantic_relabel_versions(
    plan: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    packages_root: Path,
    publication_root: Path,
    ontology_path: Path,
    now: datetime,
) -> dict[str, Any]:
    """Publish verified relabel outcomes as new immutable machine candidates.

    Parent packages are read-only. Source and binary target masks remain byte exact;
    the copied indexed map and manifest are changed together so the new label has
    one coherent ontology meaning. Previous certification never crosses the version
    boundary: every published package must pass fresh package certification.
    """

    if plan.get("plan_sha256") != _canonical_sha256(_without_self_hash(plan, "plan_sha256")):
        raise PackageSemanticAlignmentError("semantic bulk plan hash mismatch")
    if result.get("result_sha256") != _canonical_sha256(
        _without_self_hash(result, "result_sha256")
    ):
        raise PackageSemanticAlignmentError("semantic bulk result hash mismatch")
    if result.get("plan_sha256") != plan.get("plan_sha256"):
        raise PackageSemanticAlignmentError("semantic bulk publication plan binding drifted")
    batches = plan.get("batches")
    batch_index = result.get("batch_index")
    if (
        not isinstance(batches, Sequence)
        or isinstance(batches, (str, bytes))
        or not isinstance(batch_index, int)
        or batch_index < 0
        or batch_index >= len(batches)
    ):
        raise PackageSemanticAlignmentError("semantic bulk publication batch is invalid")
    batch = batches[batch_index]
    if not isinstance(batch, Mapping) or result.get("batch_sha256") != batch.get("batch_sha256"):
        raise PackageSemanticAlignmentError("semantic bulk publication batch binding drifted")
    if (
        result.get("authority_claimed") is not False
        or result.get("mutation_performed") is not False
    ):
        raise PackageSemanticAlignmentError("semantic bulk result has an invalid authority claim")

    try:
        ontology = load_ontology(ontology_path)
    except OntologyError as exc:
        raise PackageSemanticAlignmentError(str(exc)) from exc
    ontology_sha256 = sha256_file(Path(ontology_path))
    packages = Path(packages_root).resolve()
    publication = Path(publication_root).resolve()
    cases = {
        str(case.get("case_id")): case
        for case in plan.get("cases") or ()
        if isinstance(case, Mapping)
    }
    published: list[dict[str, Any]] = []
    for outcome in result.get("outcomes") or ():
        if (
            not isinstance(outcome, Mapping)
            or outcome.get("outcome") != "relabel_new_immutable_version"
        ):
            continue
        case_id = str(outcome.get("case_id"))
        case = cases.get(case_id)
        if case is None or case_id not in set(batch.get("case_ids") or ()):
            raise PackageSemanticAlignmentError(
                "semantic relabel outcome references an unknown case"
            )
        relative = Path(str(case.get("package", "")))
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise PackageSemanticAlignmentError("semantic relabel package path is unsafe")
        parent = (packages / relative).resolve()
        if packages not in parent.parents:
            raise PackageSemanticAlignmentError("semantic relabel package escapes its root")
        manifest_path = parent / "manifest.json"
        source = parent / str(case.get("source_file"))
        if sha256_file(manifest_path) != case.get("manifest_sha256"):
            raise PackageSemanticAlignmentError("semantic relabel parent manifest drifted")
        if sha256_file(source) != case.get("source_sha256"):
            raise PackageSemanticAlignmentError("semantic relabel parent source drifted")
        if outcome.get("manifest_sha256") != case.get("manifest_sha256") or outcome.get(
            "source_sha256"
        ) != case.get("source_sha256"):
            raise PackageSemanticAlignmentError("semantic relabel outcome lineage drifted")
        relabel_map = outcome.get("relabel_map")
        if not isinstance(relabel_map, Mapping) or not relabel_map:
            raise PackageSemanticAlignmentError("semantic relabel map is missing")

        parent_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if parent_manifest.get("mask_ontology_version", "body_parts_v1") != ontology.version:
            raise PackageSemanticAlignmentError("semantic relabel ontology version drifted")
        _validate_relabel_map(parent_manifest, relabel_map, ontology)
        revision_payload = {
            "case_id": case_id,
            "parent_manifest_sha256": case["manifest_sha256"],
            "result_sha256": result["result_sha256"],
            "relabel_map": dict(sorted((str(k), str(v)) for k, v in relabel_map.items())),
            "ontology_sha256": ontology_sha256,
        }
        revision_id = f"semantic_relabel_v1_{_canonical_sha256(revision_payload)[:24]}"
        destination = publication / revision_id / relative
        existing_lineage = (
            _load_json(destination / "semantic_relabel_lineage.json")
            if destination.exists()
            else None
        )
        published_at = (
            existing_lineage.get("published_at")
            if isinstance(existing_lineage, Mapping)
            else now.isoformat()
        )
        if not isinstance(published_at, str) or not published_at:
            raise PackageSemanticAlignmentError("semantic relabel publication time is invalid")
        lineage = {
            "schema_version": "1.0.0",
            "authority_claimed": False,
            "publication_status": "immutable_machine_candidate_requires_recertification",
            "revision_id": revision_id,
            "case_id": case_id,
            "parent_package": relative.as_posix(),
            "parent_manifest_sha256": case["manifest_sha256"],
            "parent_lineage_sha256": case.get("lineage_sha256"),
            "source_sha256": case["source_sha256"],
            "preserved_target_mask_sha256s": {
                str(target["label_id"]): str(target["mask_sha256"])
                for target in case.get("targets") or ()
                if isinstance(target, Mapping)
            },
            "plan_sha256": plan["plan_sha256"],
            "batch_sha256": result["batch_sha256"],
            "result_sha256": result["result_sha256"],
            "quorum_sha256": result.get("quorum_sha256"),
            "ontology_version": ontology.version,
            "ontology_sha256": ontology_sha256,
            "relabel_map": revision_payload["relabel_map"],
            "published_at": published_at,
        }
        lineage["lineage_sha256"] = _canonical_sha256(lineage)
        if existing_lineage is not None and existing_lineage != lineage:
            raise PackageSemanticAlignmentError(
                f"semantic relabel publication conflicts with existing revision: {revision_id}"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = destination.parent / f".{destination.name}.tmp-{uuid.uuid4().hex}"
        try:
            shutil.copytree(parent, staging, copy_function=shutil.copy2)
            _rewrite_relabel_candidate(
                staging,
                parent_manifest=parent_manifest,
                relabel_map=relabel_map,
                ontology=ontology,
                lineage=lineage,
                now=datetime.fromisoformat(published_at.replace("Z", "+00:00")),
            )
            if destination.exists():
                if _tree_hashes(destination) != _tree_hashes(staging):
                    raise PackageSemanticAlignmentError(
                        f"semantic relabel immutable revision drifted: {revision_id}"
                    )
            else:
                os.replace(staging, destination)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        published_manifest_sha256 = sha256_file(destination / "manifest.json")
        published.append(
            {
                "case_id": case_id,
                "revision_id": revision_id,
                "package": destination.as_posix(),
                "manifest_sha256": published_manifest_sha256,
                "lineage_sha256": lineage["lineage_sha256"],
                "authority_claimed": False,
                "requires_recertification": True,
            }
        )

    publication_result: dict[str, Any] = {
        "schema_version": "1.0.0",
        "authority_claimed": False,
        "plan_sha256": plan["plan_sha256"],
        "batch_sha256": result["batch_sha256"],
        "result_sha256": result["result_sha256"],
        "published_count": len(published),
        "published": published,
    }
    publication_result["publication_sha256"] = _canonical_sha256(publication_result)
    return publication_result


def _validate_relabel_map(
    manifest: Mapping[str, Any], relabel_map: Mapping[str, Any], ontology: Any
) -> None:
    parts = manifest.get("parts")
    if not isinstance(parts, Mapping):
        raise PackageSemanticAlignmentError("semantic relabel manifest parts are invalid")
    destinations: set[str] = set()
    for old_value, new_value in relabel_map.items():
        old, new = str(old_value), str(new_value)
        if old == new or new in destinations:
            raise PackageSemanticAlignmentError("semantic relabel map collides")
        try:
            old_label = ontology.label(old, require_enabled=True)
            new_label = ontology.label(new, require_enabled=True)
        except OntologyError as exc:
            raise PackageSemanticAlignmentError(str(exc)) from exc
        if old_label.map != new_label.map or old_label.mask_type != new_label.mask_type:
            raise PackageSemanticAlignmentError(
                "semantic relabel labels are not map/type compatible"
            )
        source_entry = parts.get(old)
        destination_entry = parts.get(new)
        if not isinstance(source_entry, Mapping) or not isinstance(
            source_entry.get("mask_file"), str
        ):
            raise PackageSemanticAlignmentError(f"semantic relabel source is not active: {old}")
        if isinstance(destination_entry, Mapping) and destination_entry.get("status") != "n/a":
            raise PackageSemanticAlignmentError(
                f"semantic relabel destination is already active: {new}"
            )
        destinations.add(new)


def _rewrite_relabel_candidate(
    package: Path,
    *,
    parent_manifest: Mapping[str, Any],
    relabel_map: Mapping[str, Any],
    ontology: Any,
    lineage: Mapping[str, Any],
    now: datetime,
) -> None:
    manifest = json.loads(json.dumps(parent_manifest))
    parts = manifest["parts"]
    for old_value, new_value in sorted(relabel_map.items()):
        old, new = str(old_value), str(new_value)
        old_entry = parts[old]
        previous_destination = parts.get(new)
        old_mask_relative = Path(str(old_entry["mask_file"]))
        new_mask_relative = old_mask_relative.with_name(f"{new}{old_mask_relative.suffix}")
        old_mask = package / old_mask_relative
        new_mask = package / new_mask_relative
        if new_mask.exists() and new_mask != old_mask:
            raise PackageSemanticAlignmentError("semantic relabel destination mask file collides")
        new_mask.parent.mkdir(parents=True, exist_ok=True)
        os.replace(old_mask, new_mask)
        old_entry["mask_file"] = new_mask_relative.as_posix()
        old_entry["mask_sha256"] = sha256_file(new_mask)
        old_entry["status"] = "draft_model_generated"
        if isinstance(previous_destination, Mapping):
            parts[old] = dict(previous_destination)
        else:
            del parts[old]
        parts[new] = old_entry

        old_panel = package / "qa_panels" / f"{old}.png"
        new_panel = package / "qa_panels" / f"{new}.png"
        if old_panel.is_file():
            if new_panel.exists():
                raise PackageSemanticAlignmentError("semantic relabel destination panel collides")
            os.replace(old_panel, new_panel)

        old_label = ontology.label(old, require_enabled=True)
        new_label = ontology.label(new, require_enabled=True)
        if old_label.id is not None and new_label.id is not None:
            map_name = f"label_map_{old_label.map}.png"
            map_path = package / map_name
            if map_path.is_file():
                values = read_mask(map_path)
                if bool((values == new_label.id).any()):
                    raise PackageSemanticAlignmentError(
                        "semantic relabel destination already has indexed pixels"
                    )
                values[values == old_label.id] = new_label.id
                write_label_map(
                    map_path,
                    values,
                    bits=16 if old_label.map == "part" else 8,
                )

    manifest["workflow_status"] = "machine_candidate"
    manifest["workflow_updated_at"] = now.isoformat()
    manifest["truth_tier"] = "machine_candidate"
    (package / "semantic_relabel_lineage.json").write_text(
        json.dumps(lineage, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (package / ".maskfactory_frozen.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "frozen_at": now.isoformat(),
                "authority_claimed": False,
                "revision_id": lineage["revision_id"],
                "lineage_sha256": lineage["lineage_sha256"],
                "policy": "immutable machine candidate; fresh certification required",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest["files"] = {
        path.relative_to(package).as_posix(): sha256_file(path)
        for path in sorted(package.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    }
    (package / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackageSemanticAlignmentError(
            f"cannot read immutable semantic lineage: {path}"
        ) from exc


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def validate_package_semantic_alignment(
    report: Mapping[str, Any],
    *,
    package_root: Path,
    manifest: Mapping[str, Any],
    deterministic_results: Sequence[Any],
    critic_certificates: Sequence[Mapping[str, Any]],
    critic_catalog: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """Validate a package-bound semantic pass from an independent critic quorum."""

    package = Path(package_root)
    if set(report) != REPORT_KEYS or report.get("schema_version") != "1.0.0":
        raise PackageSemanticAlignmentError(
            "semantic alignment report fields or schema are invalid"
        )
    if report.get("status") != "pass" or report.get("authority_claimed") is not False:
        raise PackageSemanticAlignmentError(
            "semantic alignment did not pass or improperly claims mask authority"
        )
    if report.get("deterministic_hard_veto") is not False:
        raise PackageSemanticAlignmentError("semantic alignment cannot clear a hard veto")
    if report.get("report_sha256") != semantic_alignment_report_sha256(report):
        raise PackageSemanticAlignmentError("semantic alignment report hash mismatch")

    identity = report.get("package_identity")
    if not isinstance(identity, Mapping) or set(identity) != IDENTITY_KEYS:
        raise PackageSemanticAlignmentError("semantic alignment package identity is invalid")
    expected_identity = {
        "image_id": manifest.get("image_id"),
        "instance_id": _instance_id(package),
        "ontology_version": manifest.get("mask_ontology_version", "body_parts_v1"),
        "source_sha256": sha256_file(_package_source(package)),
        "final_mask_set_sha256": final_mask_set_sha256(package, manifest),
    }
    if dict(identity) != expected_identity:
        raise PackageSemanticAlignmentError("semantic alignment package identity drifted")

    expected_qa = deterministic_qa_sha256(deterministic_results)
    if report.get("deterministic_qa_sha256") != expected_qa:
        raise PackageSemanticAlignmentError("semantic alignment deterministic QA hash drifted")
    _sha256(report.get("panel_set_sha256"), "panel_set_sha256")

    active_parts = {
        str(label): entry
        for label, entry in manifest.get("parts", {}).items()
        if isinstance(entry, Mapping)
        and entry.get("status") != "n/a"
        and isinstance(entry.get("mask_file"), str)
    }
    if not active_parts:
        raise PackageSemanticAlignmentError("semantic alignment has no active package labels")
    targets = report.get("targets")
    if not isinstance(targets, Sequence) or isinstance(targets, (str, bytes)):
        raise PackageSemanticAlignmentError("semantic alignment targets must be an array")
    observed_targets: dict[str, Mapping[str, Any]] = {}
    for row in targets:
        if not isinstance(row, Mapping) or set(row) != TARGET_KEYS:
            raise PackageSemanticAlignmentError("semantic alignment target fields are invalid")
        label = str(row.get("label_id"))
        if label in observed_targets or label not in active_parts:
            raise PackageSemanticAlignmentError(
                "semantic alignment target is unknown or duplicated"
            )
        if row.get("verdict") != "pass":
            raise PackageSemanticAlignmentError(f"semantic alignment target did not pass: {label}")
        mask = package / str(active_parts[label]["mask_file"])
        if row.get("mask_sha256") != sha256_file(mask):
            raise PackageSemanticAlignmentError(f"semantic alignment mask hash drifted: {label}")
        _sha256(row.get("decision_sha256"), f"{label}.decision_sha256")
        observed_targets[label] = row
    if set(observed_targets) != set(active_parts):
        raise PackageSemanticAlignmentError("semantic alignment does not cover every active label")

    from ..vlm.critic_authority import CriticAuthorityError, evaluate_pass_quorum

    try:
        quorum = evaluate_pass_quorum(
            critic_certificates,
            critic_catalog,
            now=now,
            deterministic_hard_veto=False,
        )
    except CriticAuthorityError as exc:
        raise PackageSemanticAlignmentError(str(exc)) from exc
    if quorum.get("status") != "eligible" or report.get("quorum_sha256") != quorum.get(
        "quorum_sha256"
    ):
        raise PackageSemanticAlignmentError(
            "semantic alignment lacks an exact current independent critic quorum"
        )

    certificates = {
        str(certificate["certificate_sha256"]): certificate for certificate in critic_certificates
    }
    decisions = report.get("critic_decisions")
    if not isinstance(decisions, Sequence) or isinstance(decisions, (str, bytes)):
        raise PackageSemanticAlignmentError("semantic alignment critic decisions must be an array")
    observed_decisions: set[str] = set()
    for row in decisions:
        if not isinstance(row, Mapping) or set(row) != DECISION_KEYS:
            raise PackageSemanticAlignmentError(
                "semantic alignment critic decision fields are invalid"
            )
        certificate_sha = str(row.get("certificate_sha256"))
        certificate = certificates.get(certificate_sha)
        if certificate is None or certificate_sha in observed_decisions:
            raise PackageSemanticAlignmentError(
                "semantic alignment critic certificate is unknown or duplicated"
            )
        if any(
            row.get(field) != certificate.get(field)
            for field in ("role_id", "model_id", "family_id")
        ):
            raise PackageSemanticAlignmentError("semantic alignment critic identity drifted")
        if row.get("verdict") != "pass" or set(row.get("cited_labels") or ()) != set(active_parts):
            raise PackageSemanticAlignmentError(
                "semantic alignment critic did not pass every active label"
            )
        _sha256(row.get("decision_sha256"), f"{certificate_sha}.decision_sha256")
        observed_decisions.add(certificate_sha)
    if observed_decisions != set(certificates):
        raise PackageSemanticAlignmentError(
            "semantic alignment does not contain every quorum decision"
        )

    return {
        "status": "pass",
        "report_sha256": report["report_sha256"],
        "quorum_sha256": quorum["quorum_sha256"],
        "covered_labels": sorted(active_parts),
        "final_mask_set_sha256": expected_identity["final_mask_set_sha256"],
    }


__all__ = [
    "PackageSemanticAlignmentError",
    "build_semantic_requalification_plan",
    "deterministic_qa_sha256",
    "execute_semantic_requalification_batch",
    "final_mask_set_sha256",
    "render_semantic_requalification_contact_sheets",
    "semantic_alignment_report_sha256",
    "validate_package_semantic_alignment",
]
