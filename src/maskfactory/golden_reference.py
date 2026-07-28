"""Lossless audit/import for user-authored reference-layer mask collections."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from PIL import Image
from scipy import ndimage

from .io.hashing import sha256_file
from .io.png_strict import write_binary_mask
from .ontology import get_ontology


class GoldenReferenceError(RuntimeError):
    """A reference collection cannot be imported without losing or overstating truth."""


def import_golden_reference(
    source_root: Path,
    output_root: Path,
    *,
    mapping_path: Path,
) -> dict[str, Any]:
    """Normalize BW layers and emit an authority-honest audit manifest."""
    source_root = Path(source_root).resolve()
    output_root = Path(output_root).resolve()
    mapping = yaml.safe_load(Path(mapping_path).read_text(encoding="utf-8"))
    if mapping.get("schema_version") != "1.0.0" or set(mapping) != {
        "schema_version",
        "source_file",
        "reviewer_assertion",
        "layers",
    }:
        raise GoldenReferenceError("golden reference mapping has an invalid top-level contract")
    source_path = source_root / mapping["source_file"]
    if not source_path.is_file():
        raise GoldenReferenceError(f"reference source image is missing: {source_path}")
    if output_root.exists():
        raise GoldenReferenceError(f"reference output already exists: {output_root}")
    source = np.asarray(Image.open(source_path).convert("RGB"))
    height, width = source.shape[:2]
    bw_files = sorted(source_root.glob("*_BW_Masked.png"), key=lambda path: path.name.casefold())
    discovered = {path.name[: -len("_BW_Masked.png")]: path for path in bw_files}
    configured = mapping["layers"]
    if not isinstance(configured, dict) or set(discovered) != set(configured):
        missing = sorted(set(discovered) - set(configured))
        stale = sorted(set(configured) - set(discovered))
        raise GoldenReferenceError(f"mapping/layer mismatch: unmapped={missing}; absent={stale}")

    ontology = get_ontology()
    records: list[dict[str, Any]] = []
    normalized: dict[str, np.ndarray] = {}
    staged = output_root.with_name(f".{output_root.name}.tmp-{uuid.uuid4().hex}")
    try:
        staged.mkdir(parents=True)
        for base, bw_path in discovered.items():
            declaration = configured[base]
            _validate_declaration(declaration, base, ontology)
            mask = _read_strict_bw(bw_path, expected_size=(width, height))
            solid_path = source_root / f"{base}_solid.png"
            if not solid_path.is_file():
                raise GoldenReferenceError(f"solid cross-check is missing: {solid_path}")
            solid = np.asarray(Image.open(solid_path).convert("RGB"))
            if solid.shape != source.shape or not np.array_equal(
                np.any(solid != source, axis=2), mask
            ):
                raise GoldenReferenceError(f"BW/solid changed-pixel mismatch: {base}")
            category = str(declaration["category"])
            relative = Path("masks") / category / f"{_slug(base)}.png"
            target_path = staged / relative
            target_path.parent.mkdir(parents=True, exist_ok=True)
            write_binary_mask(target_path, mask)
            labels, component_count = ndimage.label(mask, structure=np.ones((3, 3), dtype=np.uint8))
            component_sizes = sorted(
                (int(value) for value in np.bincount(labels.ravel())[1:]), reverse=True
            )
            record = {
                "source_layer": base,
                "category": category,
                "map": declaration.get("map"),
                "target": declaration.get("target"),
                "mapping_status": declaration.get("mapping_status"),
                "notes": declaration.get("notes", ""),
                "normalized_mask": relative.as_posix(),
                "pixel_count": int(mask.sum()),
                "area_fraction": float(mask.mean()),
                "component_count": int(component_count),
                "largest_component_fraction": (
                    component_sizes[0] / int(mask.sum()) if component_sizes else 0.0
                ),
                "bbox_xyxy": list(_bbox(mask)),
                "bw_sha256": sha256_file(bw_path),
                "solid_sha256": sha256_file(solid_path),
                "normalized_sha256": sha256_file(target_path),
                "solid_changed_pixel_equivalence": True,
            }
            records.append(record)
            normalized[base] = mask

        overlap_findings = _candidate_overlaps(records, normalized)
        duplicate_groups = _duplicate_groups(records)
        mapped_part_targets = {
            str(record["target"])
            for record in records
            if record["map"] == "part" and record["mapping_status"] == "direct_candidate"
        }
        required_parts = {
            label.name
            for label in ontology.labels_for_map("part", enabled_only=True)
            if int(label.id) != 0
        }
        blockers = [
            "reference layers are not a complete exclusive MaskFactory PART map",
            "review_time_sec and full visibility-state adjudication are absent",
        ]
        if overlap_findings:
            blockers.append(
                "mapped PART candidates overlap and require human boundary adjudication"
            )
        missing_parts = sorted(required_parts - mapped_part_targets)
        if missing_parts:
            blockers.append("required ontology labels are missing or not directly mappable")
        manifest = {
            "schema_version": "1.0.0",
            "collection_id": f"goldref_{sha256_file(source_path)[:12]}",
            "image_id": f"img_{sha256_file(source_path)[:12]}",
            "source": str(source_path),
            "source_sha256": sha256_file(source_path),
            "source_size": [width, height],
            "reviewer_assertion": str(mapping["reviewer_assertion"]),
            "authority": "user_supplied_reference_requires_maskfactory_adjudication",
            "eligible_for_package_gold": False,
            "eligible_for_training": False,
            "eligible_for_cloud_teacher_truth": False,
            "layer_count": len(records),
            "layers": records,
            "mapped_part_targets": sorted(mapped_part_targets),
            "missing_part_targets": missing_parts,
            "part_candidate_overlaps": overlap_findings,
            "duplicate_mask_groups": duplicate_groups,
            "blockers": blockers,
        }
        manifest["manifest_sha256"] = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        (staged / "reference_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        staged.replace(output_root)
        return manifest
    except Exception:
        _remove_staged_tree(staged)
        raise


def verify_golden_reference(output_root: Path) -> tuple[str, ...]:
    """Verify normalized mask bytes, geometry, and manifest identity without mutation."""
    root = Path(output_root).resolve()
    manifest_path = root / "reference_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GoldenReferenceError(f"cannot read reference manifest: {exc}") from exc
    issues: list[str] = []
    source = Path(manifest.get("source", ""))
    if not source.is_file() or sha256_file(source) != manifest.get("source_sha256"):
        issues.append("source_hash_mismatch")
    size = tuple(manifest.get("source_size", ()))
    for record in manifest.get("layers", ()):
        relative = str(record.get("normalized_mask", ""))
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            issues.append(f"path_escape:{relative}")
            continue
        if not path.is_file():
            issues.append(f"missing:{relative}")
            continue
        if sha256_file(path) != record.get("normalized_sha256"):
            issues.append(f"hash_mismatch:{relative}")
            continue
        image = Image.open(path)
        if (
            image.mode != "L"
            or image.size != size
            or not set(np.unique(image).tolist()) <= {0, 255}
        ):
            issues.append(f"format_mismatch:{relative}")
    if len(manifest.get("layers", ())) != manifest.get("layer_count"):
        issues.append("layer_count_mismatch")
    fingerprinted = dict(manifest)
    claimed = fingerprinted.pop("manifest_sha256", None)
    actual = hashlib.sha256(
        json.dumps(fingerprinted, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if actual != claimed:
        issues.append("manifest_hash_mismatch")
    return tuple(sorted(set(issues)))


def run_reference_cloud_benchmark(
    reference_root: Path,
    *,
    labels: tuple[str, ...],
    cloud_config_path: Path,
    output_root: Path,
    providers: dict | None = None,
    provider_names: tuple[str, ...] = ("gemini", "openai", "anthropic"),
) -> dict[str, Any]:
    """Run each enabled teacher independently on selected reference masks in shadow mode."""
    from .qa.panels import render_workhorse_evidence
    from .vlm.cloud_budget import DailyBudgetLedger
    from .vlm.cloud_providers import build_teacher_providers
    from .vlm.cloud_teacher import (
        TeacherRequest,
        load_cloud_teacher_config,
        materialize_teacher_candidate,
        run_teacher_cascade,
    )
    from .vlm.workhorse import CorrectionPlan, WorkhorseAudit

    reference_root = Path(reference_root).resolve()
    output_root = Path(output_root).resolve()
    if output_root.exists():
        raise GoldenReferenceError(f"cloud benchmark output already exists: {output_root}")
    if issues := verify_golden_reference(reference_root):
        raise GoldenReferenceError(f"reference verification failed: {issues}")
    manifest = json.loads((reference_root / "reference_manifest.json").read_text(encoding="utf-8"))
    config = load_cloud_teacher_config(cloud_config_path)
    if config["enabled"] is not True or config["mode"] != "shadow_only":
        raise GoldenReferenceError("cloud benchmark requires enabled shadow-only configuration")
    active_providers = providers if providers is not None else build_teacher_providers(config)
    if not active_providers:
        raise GoldenReferenceError("cloud benchmark has no enabled providers")
    if not provider_names or any(
        name not in {"gemini", "openai", "anthropic"} for name in provider_names
    ):
        raise GoldenReferenceError("cloud benchmark provider selection is invalid")
    by_target = {
        record["target"]: record
        for record in manifest["layers"]
        if record["map"] == "part" and record["mapping_status"] == "direct_candidate"
    }
    if not labels or any(label not in by_target for label in labels):
        raise GoldenReferenceError(
            f"benchmark labels must be direct PART candidates: requested={list(labels)}"
        )
    budget_settings = config["budget"]
    budget = DailyBudgetLedger(
        Path(budget_settings["ledger_path"]),
        timezone_name=budget_settings["timezone"],
        hard_limit_usd=budget_settings["hard_limit_usd"],
        lock_timeout_sec=float(budget_settings["lock_timeout_sec"]),
    )
    source_path = Path(manifest["source"])
    source = Image.open(source_path).convert("RGB")
    direct_masks = {
        target: np.asarray(Image.open(reference_root / record["normalized_mask"])) != 0
        for target, record in by_target.items()
    }
    prompt = Path("src/maskfactory/vlm/prompts/p_cloud_teacher.txt").read_text(encoding="utf-8")
    staged = output_root.with_name(f".{output_root.name}.tmp-{uuid.uuid4().hex}")
    results: list[dict[str, Any]] = []
    try:
        staged.mkdir(parents=True)
        for label in labels:
            mask = direct_masks[label]
            protected = np.zeros_like(mask)
            for other_label, other_mask in direct_masks.items():
                if other_label != label:
                    protected |= other_mask
            evidence = render_workhorse_evidence(
                source,
                mask,
                protected,
                staged / "evidence" / label,
                tile_size=1024,
            )
            overlaps = tuple(
                finding
                for finding in manifest["part_candidate_overlaps"]
                if finding["left_target"] == label or finding["right_target"] == label
            )
            local = WorkhorseAudit(
                label=label,
                model_verdict="uncertain",
                model_confidence=0.0,
                verdict="uncertain",
                confidence=0.0,
                problems=(),
                observations={
                    key: "Reference seed has not yet been adjudicated against MaskFactory ontology."
                    for key in (
                        "full_context",
                        "source_crop",
                        "mask",
                        "overlay",
                        "contour",
                        "neighbor_overlap",
                    )
                },
                evidence="Human-authored reference seed; independent teacher audit required.",
                correction_instruction="",
                correction_plan=CorrectionPlan("human_review", (), (), "reference seed"),
                model="reference_seed",
                prompt_version="image1_v1",
                latency_ms=0,
                deterministic_overrides=(),
            )
            request = TeacherRequest(
                manifest["image_id"],
                "p0",
                label,
                source_path,
                evidence,
                local,
                tuple(
                    {
                        "check_id": "REF-OVERLAP",
                        "result": "warn",
                        "details": finding,
                    }
                    for finding in overlaps
                ),
            )
            for provider_name in provider_names:
                if provider_name not in active_providers:
                    continue
                single = deepcopy(config)
                single["budget"]["maximum_calls_per_image"] = 1
                single["selection"]["primary_provider"] = provider_name
                single["selection"]["always_escalate_labels"] = [label]
                report_path = staged / "reports" / label / f"{provider_name}.json"
                judgments = run_teacher_cascade(
                    request,
                    providers={provider_name: active_providers[provider_name]},
                    config=single,
                    budget=budget,
                    prompt_template=prompt,
                    report_path=report_path,
                )
                if not judgments:
                    results.append(
                        {
                            "label": label,
                            "provider": provider_name,
                            "status": "provider_failed_or_unusable",
                            "report": report_path.relative_to(staged).as_posix(),
                            "judgment": None,
                            "candidate": None,
                        }
                    )
                    continue
                judgment = judgments[0]
                candidate = materialize_teacher_candidate(
                    judgment,
                    request=request,
                    current_mask=mask,
                    protected_neighbor=protected,
                    refiner=None,
                    output_path=staged / "candidates" / label / f"{provider_name}.png",
                )
                results.append(
                    {
                        "label": label,
                        "provider": provider_name,
                        "status": "complete",
                        "report": report_path.relative_to(staged).as_posix(),
                        "judgment": asdict(judgment),
                        "candidate": asdict(candidate),
                    }
                )
        snapshot = budget.snapshot()
        summary = {
            "schema_version": "1.0.0",
            "reference_collection_id": manifest["collection_id"],
            "image_id": manifest["image_id"],
            "labels": list(labels),
            "provider_results": results,
            "budget": {
                "local_date": snapshot.local_date,
                "committed_usd": str(snapshot.committed_usd),
                "reserved_usd": str(snapshot.reserved_usd),
                "available_usd": str(snapshot.available_usd),
                "hard_limit_usd": str(snapshot.hard_limit_usd),
            },
            "authority": "shadow_only_no_gold_or_mask_authority",
        }
        (staged / "benchmark_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        staged.replace(output_root)
        return summary
    except Exception:
        _remove_staged_tree(staged)
        raise


def _validate_declaration(declaration: Any, base: str, ontology) -> None:
    required = {"category", "map", "target", "mapping_status", "notes"}
    if not isinstance(declaration, dict) or set(declaration) != required:
        raise GoldenReferenceError(f"layer declaration has wrong shape: {base}")
    if declaration["mapping_status"] not in {
        "direct_candidate",
        "union_or_coarse",
        "auxiliary_detail",
        "ambiguous_duplicate",
        "unresolved",
    }:
        raise GoldenReferenceError(f"invalid mapping status: {base}")
    map_name, target = declaration["map"], declaration["target"]
    if map_name is None and target is None:
        return
    if map_name not in {"part", "material"} or not isinstance(target, str):
        raise GoldenReferenceError(f"invalid ontology target declaration: {base}")
    label = ontology.label(target)
    if label.map != map_name:
        raise GoldenReferenceError(f"ontology target is in the wrong map: {base}")


def _read_strict_bw(path: Path, *, expected_size: tuple[int, int]) -> np.ndarray:
    image = Image.open(path)
    if image.size != expected_size or image.mode != "RGB":
        raise GoldenReferenceError(f"BW mask geometry/mode is invalid: {path.name}")
    array = np.asarray(image)
    if not (
        np.array_equal(array[:, :, 0], array[:, :, 1])
        and np.array_equal(array[:, :, 0], array[:, :, 2])
        and set(np.unique(array[:, :, 0]).tolist()) <= {0, 255}
    ):
        raise GoldenReferenceError(f"BW mask is not strict binary grayscale: {path.name}")
    mask = array[:, :, 0] == 255
    if not mask.any():
        raise GoldenReferenceError(f"BW mask is empty: {path.name}")
    return mask


def _candidate_overlaps(records: list[dict], masks: dict[str, np.ndarray]) -> list[dict]:
    candidates = [
        record
        for record in records
        if record["map"] == "part" and record["mapping_status"] == "direct_candidate"
    ]
    findings = []
    for index, left in enumerate(candidates):
        for right in candidates[index + 1 :]:
            overlap = int(
                np.count_nonzero(masks[left["source_layer"]] & masks[right["source_layer"]])
            )
            if overlap:
                findings.append(
                    {
                        "left_source": left["source_layer"],
                        "left_target": left["target"],
                        "right_source": right["source_layer"],
                        "right_target": right["target"],
                        "overlap_px": overlap,
                    }
                )
    return findings


def _duplicate_groups(records: list[dict]) -> list[list[str]]:
    groups: dict[str, list[str]] = {}
    for record in records:
        groups.setdefault(record["normalized_sha256"], []).append(record["source_layer"])
    return [sorted(names) for names in groups.values() if len(names) > 1]


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.where(mask)
    return int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    return slug or "unnamed"


def _remove_staged_tree(root: Path) -> None:
    if not root.exists():
        return
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            path.rmdir()
    root.rmdir()


__all__ = [
    "GoldenReferenceError",
    "import_golden_reference",
    "run_reference_cloud_benchmark",
    "verify_golden_reference",
]
