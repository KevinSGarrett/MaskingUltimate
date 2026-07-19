"""Bounded visual repair wave: DurableRepairExecutor + remove_small_components.

Honest proof-tier lane: accept only guarded complete-map improvements; prefer
ABSTAIN_BOUNDED over false VISUAL_QA_PASS. Does not claim gold.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import yaml
from PIL import Image
from scipy import ndimage

from maskfactory.autonomy.operational_repair import (
    DurableRepairExecutor,
    LiveRepairProposal,
)
from maskfactory.autonomy.repair import (
    BoundedRepairLimits,
    evaluate_repair_candidate,
    repair_limits_from_policy,
)
from maskfactory.autonomy.review_draft import CandidateQaOutcome
from maskfactory.derive import derive_package
from maskfactory.fusion.mapbuild import export_binaries
from maskfactory.io.hashing import sha256_file
from maskfactory.io.png_strict import read_mask, write_binary_mask, write_label_map
from maskfactory.ontology import get_ontology
from maskfactory.packager import verify_packages
from maskfactory.qa.checks import run_qc001_010
from maskfactory.qa.panels import render_boundary_panel, render_part_overlays

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent
PACKAGES = ROOT / "data" / "packages"

# Worst documented visual-defect instances from hard_visual_qa_corpus_climb.
TARGETS = [
    {
        "image_id": "img_51945db358cb",
        "instance": "p0",
        "label": "left_forearm",
        "defect_class": "noise_leak",
        "hypotheses": ["remove_small_components_max_ontology"],
    },
    {
        "image_id": "img_cdab0311dc96",
        "instance": "p0",
        "label": "left_hand_base",
        "defect_class": "noise_artifacts",
        "hypotheses": ["remove_small_components_max_ontology"],
    },
    {
        "image_id": "img_7b7a3c7d5dd3",
        "instance": "p0",
        "label": "chest_upper_torso",
        "defect_class": "noise_spray",
        "hypotheses": ["remove_small_components_max_ontology"],
    },
    {
        "image_id": "img_2ca794d19be9",
        "instance": "p0",
        "label": "left_forearm",
        "defect_class": "noise_leak",
        "hypotheses": ["remove_small_components_max_ontology"],
    },
    {
        "image_id": "img_b2b46c45d8e0",
        "instance": "p0",
        "label": "left_forearm",
        "defect_class": "exclusivity_bleed",
        "hypotheses": ["remove_small_components_max_ontology"],
    },
    {
        "image_id": "img_e5163e08baac",
        "instance": "p0",
        "label": "left_forearm",
        "defect_class": "underfill",
        "hypotheses": ["remove_small_components_max_ontology", "drop_tiny_lt_64px"],
    },
    {
        "image_id": "img_a3d2663ad90d",
        "instance": "p0",
        "label": "hair",
        "defect_class": "multi_person_half_fill",
        "hypotheses": ["remove_small_components_max_ontology"],
    },
]


def _package_root(image_id: str, instance: str) -> Path:
    return PACKAGES / image_id / "instances" / instance


def _expand_bbox(mask: np.ndarray, pad_frac: float = 0.12) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        h, w = mask.shape
        return (0, 0, w, h)
    top, bottom = int(ys.min()), int(ys.max()) + 1
    left, right = int(xs.min()), int(xs.max()) + 1
    h, w = mask.shape
    pad_y = max(1, int(round((bottom - top) * pad_frac)))
    pad_x = max(1, int(round((right - left) * pad_frac)))
    return (
        max(0, left - pad_x),
        max(0, top - pad_y),
        min(w, right + pad_x),
        min(h, bottom + pad_y),
    )


def _candidate_mask(current: np.ndarray, hypothesis: str, label: str) -> np.ndarray:
    labels, count = ndimage.label(current)
    if count == 0:
        return current.copy()
    sizes = {i: int((labels == i).sum()) for i in range(1, count + 1)}
    ranked = sorted(sizes, key=sizes.get, reverse=True)
    if hypothesis == "remove_small_components_max_ontology":
        allowed = max(1, int(get_ontology().label(label).max_components))
        keep = set(ranked[:allowed])
    elif hypothesis == "drop_tiny_lt_64px":
        keep = {i for i, area in sizes.items() if area >= 64} or {ranked[0]}
    else:
        raise ValueError(hypothesis)
    return np.isin(labels, list(keep))


def _map_metrics(part_map: np.ndarray, label: str) -> dict[str, float | int]:
    label_id = int(get_ontology().label(label).id)
    mask = part_map == label_id
    max_c = max(1, int(get_ontology().label(label).max_components))
    n = int(ndimage.label(mask)[1])
    area = int(mask.sum())
    excess = max(0, n - max_c)
    # Higher is better: reward fewer excess components; penalize empty.
    score = 0.0 if area == 0 else max(0.0, 1.0 - (excess / max(1.0, float(n))) * 0.85)
    # Small bonus for lower absolute excess.
    score = min(1.0, score + max(0.0, 0.05 * (1.0 - min(1.0, excess / 20.0))))
    return {"area": area, "components": n, "excess": excess, "score": float(score)}


def _validator_factory(baseline_part: np.ndarray, label: str, baseline_score: float):
    def _validate(path: Path, _scope: str) -> CandidateQaOutcome:
        part = read_mask(path).astype(np.uint16)
        if part.shape != baseline_part.shape:
            return CandidateQaOutcome(
                ("SHAPE",), None, "fail", score=0.0, baseline_score=baseline_score
            )
        metrics = _map_metrics(part, label)
        # Reject if target label vanished or shrank more than 25% (underfill risk).
        base_area = int((baseline_part == int(get_ontology().label(label).id)).sum())
        if metrics["area"] == 0 or (base_area and metrics["area"] < 0.75 * base_area):
            return CandidateQaOutcome(
                ("AREA_REGRESSION",),
                None,
                "fail",
                score=float(metrics["score"]),
                baseline_score=baseline_score,
                non_regressing=False,
            )
        improved = float(metrics["score"]) > baseline_score + 0.001
        overall = (
            "pass"
            if improved and metrics["excess"] < _map_metrics(baseline_part, label)["excess"]
            else "fail"
        )
        return CandidateQaOutcome(
            (),
            None,
            overall,
            score=float(metrics["score"]),
            baseline_score=baseline_score,
            non_regressing=float(metrics["score"]) + 1e-9 >= baseline_score,
        )

    return _validate


def _refresh_files(package_root: Path) -> None:
    path = package_root / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    files = tuple(
        file
        for file in package_root.rglob("*")
        if file.is_file()
        and file.name != "manifest.json"
        and not file.relative_to(package_root).parts[0].startswith("masks@v")
    )
    from maskfactory.io.hashing import sha256_file_map

    manifest["files"] = sha256_file_map(package_root, files)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _regen_panels(package_root: Path) -> None:
    part_map = read_mask(package_root / "label_map_part.png").astype(np.uint16)
    source_path = package_root / "source.png"
    with Image.open(source_path) as opened:
        source = opened.convert("RGB")
    viz = yaml.safe_load((ROOT / "configs" / "viz.yaml").read_text(encoding="utf-8"))
    render_part_overlays(
        source, part_map, package_root / "overlays", label_colors=viz["label_colors"]
    )
    authority = get_ontology()
    masks = {
        label.name: part_map == int(label.id)
        for label in authority.labels_for_map("part", enabled_only=True)
        if label.id and np.any(part_map == int(label.id))
    }
    panel_dir = package_root / "qa_panels"
    panel_dir.mkdir(exist_ok=True)
    for name, mask in masks.items():
        neighbor = np.zeros(mask.shape, dtype=bool)
        for other, other_mask in masks.items():
            if other != name:
                neighbor |= other_mask
        render_boundary_panel(source, mask, neighbor, panel_dir / f"{name}.png")


def _promote_accepted(
    package_root: Path,
    accepted_map: Path,
    label: str,
    backup_dir: Path,
) -> dict:
    backup_dir.mkdir(parents=True, exist_ok=True)
    for name in ("label_map_part.png", "label_map_material.png", "manifest.json"):
        src = package_root / name
        if src.is_file():
            shutil.copy2(src, backup_dir / name)
    part = read_mask(accepted_map).astype(np.uint16)
    material = read_mask(package_root / "label_map_material.png").astype(np.uint8)
    label_id = int(get_ontology().label(label).id)
    # Clear material where part label was removed.
    old = read_mask(package_root / "label_map_part.png").astype(np.uint16)
    removed = (old == label_id) & (part != label_id)
    material[removed] = 0
    write_label_map(package_root / "label_map_part.png", part, bits=16)
    write_label_map(package_root / "label_map_material.png", material, bits=8)
    export_binaries(package_root)
    derive_package(package_root)
    _regen_panels(package_root)
    _refresh_files(package_root)
    results = run_qc001_010(package_root)
    return {
        "qc_passed": all(r.passed for r in results),
        "qc": [asdict(r) for r in results if not r.passed],
        "part_sha256": sha256_file(package_root / "label_map_part.png"),
    }


def run_one(target: dict, limits: BoundedRepairLimits) -> dict:
    package = _package_root(target["image_id"], target["instance"])
    label = target["label"]
    record: dict = {
        "target": f"{target['image_id']}/{target['instance']}/{label}",
        "defect_class": target["defect_class"],
        "attempts": [],
        "outcome": "ABSTAIN_BOUNDED",
        "promoted": False,
    }
    if not (package / "label_map_part.png").is_file():
        record["reason"] = "package_missing"
        return record
    if not (package / "masks" / f"{label}.png").is_file():
        record["reason"] = "mask_missing"
        return record

    work = WORK / "sessions" / f"{target['image_id']}_{target['instance']}_{label}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    parent_map = work / "accepted_parent.png"
    shutil.copy2(package / "label_map_part.png", parent_map)
    parent_part = read_mask(parent_map).astype(np.uint16)
    current = read_mask(package / "masks" / f"{label}.png") > 0
    if not current.any():
        # Fall back to label map.
        current = parent_part == int(get_ontology().label(label).id)
    baseline = _map_metrics(parent_part, label)
    record["baseline"] = baseline
    roi = _expand_bbox(current)
    person_bbox = _expand_bbox(parent_part > 0, pad_frac=0.02)
    protected = np.zeros(current.shape, dtype=bool)
    for pname in ("other_person", "accessory_or_prop", "occluding_object", "support_surface"):
        try:
            pid = int(get_ontology().label(pname).id)
        except Exception:
            continue
        protected |= parent_part == pid

    parent_id = f"{target['image_id']}-{target['instance']}-{label}-v1"
    executor = DurableRepairExecutor(
        state_path=work / "repair-state.json",
        accepted_map_path=parent_map,
        accepted_parent_id=parent_id,
        limits=limits,
        map_validator=_validator_factory(parent_part, label, float(baseline["score"])),
        output_dir=work / "repair-output",
    )

    terminal_outcome = None
    for hypothesis in target["hypotheses"]:
        candidate = _candidate_mask(current, hypothesis, label)
        drop_px = int(current.sum()) - int(candidate.sum())
        cand_path = work / f"candidate_{hypothesis}.png"
        write_binary_mask(cand_path, candidate.astype(np.uint8) * 255)
        guard = evaluate_repair_candidate(
            candidate,
            current_mask=current,
            protected_mask=protected,
            label=label,
            roi_xyxy=roi,
            person_bbox_xyxy=person_bbox,
            ordinary_max_changed_fraction=0.75,
            reconstruction_max_changed_fraction=2.0,
            maximum_protected_overlap_fraction=0.01,
            maximum_outside_roi_fraction=0.005,
            expected_area_slack=0.5,
        )
        # Score ppm mirrors component cleanup magnitude for decide_bounded_repair history.
        score_ppm = min(
            999_000,
            int(float(baseline["score"]) * 1_000_000)
            + max(
                0,
                int(baseline["excess"])
                - max(
                    0,
                    int(ndimage.label(candidate)[1])
                    - max(1, int(get_ontology().label(label).max_components)),
                ),
            )
            * 50_000
            + min(drop_px, 5000),
        )
        proposal = LiveRepairProposal(
            accepted_parent_id=parent_id,
            hypothesis_id=hypothesis,
            label=label,
            candidate_mask_path=cand_path,
            candidate_mask_sha256=sha256_file(cand_path),
            score_ppm=score_ppm,
            elapsed_seconds=1.0,
            resource_units=1.0,
            guard=guard,
            repair_roi_xyxy=roi,
        )
        result = executor.execute(proposal)
        attempt = {
            "hypothesis": hypothesis,
            "drop_px": drop_px,
            "components_before": int(ndimage.label(current)[1]),
            "components_after": int(ndimage.label(candidate)[1]),
            "guard_eligible": guard.eligible,
            "guard_vetoes": list(guard.vetoes),
            "executor_outcome": result.outcome,
            "executor_reason": result.reason,
            "accepted_map_sha256": result.accepted_map_sha256,
        }
        record["attempts"].append(attempt)
        terminal_outcome = result.outcome
        if result.outcome == "accepted_reversible_repair":
            # Promote only when noise/excess improved and remaining defect class is noise-like.
            if (
                target["defect_class"]
                in {
                    "noise_leak",
                    "noise_artifacts",
                    "noise_spray",
                }
                and drop_px >= 64
                and baseline["excess"] > 0
            ):
                promote = _promote_accepted(
                    package,
                    result.accepted_map_path,
                    label,
                    WORK / "backups" / f"{target['image_id']}_{target['instance']}_{label}",
                )
                record["promoted"] = True
                record["promote"] = promote
                if promote["qc_passed"]:
                    record["outcome"] = "ACCEPTED_REVERSIBLE_REPAIR_BOUNDED"
                    record["reason"] = (
                        "noise-component cleanup accepted via DurableRepairExecutor; "
                        "hard QC re-pass; visual gold NOT claimed"
                    )
                else:
                    # Rollback promotion from backup.
                    for name in ("label_map_part.png", "label_map_material.png", "manifest.json"):
                        b = (
                            WORK
                            / "backups"
                            / f"{target['image_id']}_{target['instance']}_{label}"
                            / name
                        )
                        if b.is_file():
                            shutil.copy2(b, package / name)
                    export_binaries(package)
                    derive_package(package)
                    _regen_panels(package)
                    _refresh_files(package)
                    record["outcome"] = "ABSTAIN_BOUNDED"
                    record["reason"] = "promote_failed_hard_qc_rolled_back"
                    record["promoted"] = False
            else:
                record["outcome"] = "ABSTAIN_BOUNDED"
                record["reason"] = (
                    f"executor accepted map child but defect_class={target['defect_class']} "
                    f"or drop_px={drop_px} not sufficient for live promote; parent preserved"
                )
            break
        if result.outcome == "rolled_back_autonomous_abstention":
            record["outcome"] = "ABSTAIN_BOUNDED"
            record["reason"] = result.reason
            break

    if terminal_outcome is None:
        record["reason"] = "no_hypothesis_executed"
    elif record["outcome"] == "ABSTAIN_BOUNDED" and "reason" not in record:
        record["reason"] = terminal_outcome or "no_accepted_repair"
    # Structural abstain for non-noise classes even after attempts.
    if target["defect_class"] in {"underfill", "exclusivity_bleed", "multi_person_half_fill"}:
        if record["outcome"] != "ACCEPTED_REVERSIBLE_REPAIR_BOUNDED":
            record["outcome"] = "ABSTAIN_BOUNDED"
            record["reason"] = (
                record.get("reason")
                or f"{target['defect_class']} not remediable by bounded CC cleanup without false visual pass"
            )
    return record


def main() -> None:
    policy = yaml.safe_load(
        (ROOT / "configs" / "autonomous_masks.yaml").read_text(encoding="utf-8")
    )
    limits = repair_limits_from_policy(policy["repair"])
    # Keep wave short: 3 attempts max already in policy.
    started = datetime.now(UTC).isoformat()
    results = [run_one(target, limits) for target in TARGETS]
    hard = verify_packages(PACKAGES, sample=20)
    hard_summary = {
        "discovered": len(hard),
        "passed": sum(1 for item in hard if item.passed),
        "failed": [
            str(item.package.relative_to(PACKAGES)).replace("\\", "/")
            for item in hard
            if not item.passed
        ],
    }
    accepted = [r for r in results if r["outcome"] == "ACCEPTED_REVERSIBLE_REPAIR_BOUNDED"]
    abstained = [r for r in results if r["outcome"] == "ABSTAIN_BOUNDED"]
    evidence = {
        "ts": datetime.now(UTC).isoformat(),
        "started_at": started,
        "lane": "bounded_visual_repair_toward_improvement",
        "contracts": [
            "maskfactory.autonomy.operational_repair.DurableRepairExecutor",
            "maskfactory.autonomy.repair.decide_bounded_repair",
            "remove_small_components hypothesis (workhorse tool family)",
        ],
        "claims_not_established": [
            "VISUAL_QA_PASS_BOUNDED",
            "gold",
            "human_approved_gold",
            "PRODUCTION_EVIDENCE_PASS",
        ],
        "results": results,
        "summary": {
            "accepted_promoted": len(accepted),
            "abstain_bounded": len(abstained),
            "hard_qa_after": hard_summary,
            "highest_hard_tier": (
                "HARD_QA_PASS_BOUNDED"
                if hard_summary["passed"] == hard_summary["discovered"]
                and hard_summary["discovered"]
                else "HARD_QA_FAIL_BOUNDED"
            ),
            "highest_visual_tier": (
                "VISUAL_QA_REVIEWED_WITH_DEFECTS" if accepted else "VISUAL_QA_REVIEWED_WITH_DEFECTS"
            ),
            "visual_note": (
                "Noise-component repairs may improve panels but residual garment/"
                "underfill/bleed/half-fill defects remain; never claim VISUAL_QA_PASS_BOUNDED."
            ),
        },
        "blockers": [
            "VISUAL_QA_PASS_BOUNDED blocked: residual garment bias / underfill / exclusivity bleed / multi-person half-fill",
            "human_approved_gold still requires Kevin CVAT correction",
        ],
    }
    out = WORK / "bounded_visual_repair_20260719.json"
    out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"evidence": str(out), "summary": evidence["summary"]}, indent=2))


if __name__ == "__main__":
    main()
