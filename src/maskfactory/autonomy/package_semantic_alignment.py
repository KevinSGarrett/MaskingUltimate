"""Fail-closed semantic alignment for autonomous-certified training packages.

Structural mask QA and multi-provider pixel consensus cannot prove that a mask
represents the label written beside it.  This module binds each package to a
package-specific, current, independent self-hosted critic quorum before the
package may be frozen or consumed as autonomous-certified training truth.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from ..io.hashing import sha256_file, sha256_file_map

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
    "final_mask_set_sha256",
    "render_semantic_requalification_contact_sheets",
    "semantic_alignment_report_sha256",
    "validate_package_semantic_alignment",
]
