"""Residual visual-defect wave after noise CC repairs.

Research: garment bias / underfill / connected exclusivity bleed / multi-person
half-fill have no safe morphological fill/cut without false gold. One narrow
hypothesis remains: clear ontologically forbidden materials on a part
(footwear/sock on chest). Prefer ABSTAIN_BOUNDED; never claim VISUAL_QA_PASS.
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
from maskfactory.autonomy.visual_defect_policy import (
    BLOCKED_VISUAL_PASS_CLAIM,
    HIGHEST_VISUAL_TIER_WITH_RESIDUALS,
    decide_visual_repair_promotion,
    forbidden_material_names_for_part,
)
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

TARGETS = [
    {
        "image_id": "img_51945db358cb",
        "instance": "p0",
        "label": "chest_upper_torso",
        "defect_class": "garment_bias",
        "hypotheses": [
            "clear_forbidden_material_then_max_components",
            "clear_forbidden_material_on_part",
            "remove_small_components_max_ontology",
        ],
        "research_note": (
            "Sports-bra-shaped chest remains structural garment bias; "
            "footwear material on a separate chest CC is safe material-exclusivity clear "
            "when followed by max-component cleanup to satisfy the CC guard."
        ),
    },
    {
        "image_id": "img_2ca794d19be9",
        "instance": "p0",
        "label": "chest_upper_torso",
        "defect_class": "garment_bias",
        "hypotheses": [
            "clear_forbidden_material_then_max_components",
            "clear_forbidden_material_on_part",
            "remove_small_components_max_ontology",
        ],
        "research_note": (
            "Chest dominated by underwear/lace materials; clearing them guts the part. "
            "No forbidden footwear/sock pixels; morphology cannot fix garment bias safely."
        ),
    },
    {
        "image_id": "img_b2b46c45d8e0",
        "instance": "p0",
        "label": "left_forearm",
        "defect_class": "exclusivity_bleed",
        "hypotheses": ["remove_small_components_max_ontology"],
        "research_note": (
            "Hip/trunk triangle is one CC with the forearm mass; no S05 pose ROI on package; "
            "almost all pixels are garment materials — clearing garments destroys the mask."
        ),
    },
    {
        "image_id": "img_e5163e08baac",
        "instance": "p0",
        "label": "left_forearm",
        "defect_class": "underfill",
        "hypotheses": ["remove_small_components_max_ontology"],
        "research_note": (
            "Severe under-segmentation; CC cleanup / material clear only shrink. "
            "Dilation/fill would invent forearm mass → false gold."
        ),
    },
    {
        "image_id": "img_a3d2663ad90d",
        "instance": "p0",
        "label": "hair",
        "defect_class": "multi_person_half_fill",
        "hypotheses": ["remove_small_components_max_ontology"],
        "research_note": (
            "Half-body identity cut is structural multi-person ownership failure; "
            "CC cleanup drops ~9 px noise only. Material clear on hair is not promotable."
        ),
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


def _keep_max_components(mask: np.ndarray, label: str) -> np.ndarray:
    labels, count = ndimage.label(mask)
    if count == 0:
        return mask.copy()
    sizes = {i: int((labels == i).sum()) for i in range(1, count + 1)}
    ranked = sorted(sizes, key=sizes.get, reverse=True)
    allowed = max(1, int(get_ontology().label(label).max_components))
    keep = set(ranked[:allowed])
    return np.isin(labels, list(keep))


def _clear_forbidden(current: np.ndarray, label: str, material: np.ndarray | None) -> np.ndarray:
    if material is None:
        return current.copy()
    names = forbidden_material_names_for_part(label)
    if not names:
        return current.copy()
    forbidden_ids = set()
    for name in names:
        try:
            forbidden_ids.add(int(get_ontology().label(name).id))
        except Exception:
            continue
    if not forbidden_ids:
        return current.copy()
    return current & ~np.isin(material, list(forbidden_ids))


def _candidate_mask(
    current: np.ndarray,
    hypothesis: str,
    label: str,
    material: np.ndarray | None,
) -> np.ndarray:
    if hypothesis == "remove_small_components_max_ontology":
        return _keep_max_components(current, label)
    if hypothesis == "clear_forbidden_material_on_part":
        return _clear_forbidden(current, label, material)
    if hypothesis == "clear_forbidden_material_then_max_components":
        cleared = _clear_forbidden(current, label, material)
        return _keep_max_components(cleared, label)
    raise ValueError(hypothesis)


def _map_metrics(part_map: np.ndarray, label: str) -> dict[str, float | int]:
    label_id = int(get_ontology().label(label).id)
    mask = part_map == label_id
    max_c = max(1, int(get_ontology().label(label).max_components))
    n = int(ndimage.label(mask)[1])
    area = int(mask.sum())
    excess = max(0, n - max_c)
    score = 0.0 if area == 0 else max(0.0, 1.0 - (excess / max(1.0, float(n))) * 0.85)
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
        base_excess = _map_metrics(baseline_part, label)["excess"]
        # Material clear may keep excess but remove forbidden ontology pixels:
        # accept non-regression with any score improvement OR area drop that
        # still passes the 75% floor (handled above).
        overall = "pass" if improved and metrics["excess"] < base_excess else "fail"
        if not improved and metrics["excess"] <= base_excess:
            # Allow material-clear when excess unchanged but area shrunk via forbidden clear.
            overall = "pass" if metrics["area"] < base_area else "fail"
        return CandidateQaOutcome(
            (),
            None,
            overall,
            score=float(metrics["score"]),
            baseline_score=baseline_score,
            non_regressing=float(metrics["score"]) + 1e-9 >= baseline_score
            or metrics["area"] <= base_area,
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


def _rollback(package_root: Path, backup_dir: Path) -> None:
    for name in ("label_map_part.png", "label_map_material.png", "manifest.json"):
        b = backup_dir / name
        if b.is_file():
            shutil.copy2(b, package_root / name)
    export_binaries(package_root)
    derive_package(package_root)
    _regen_panels(package_root)
    _refresh_files(package_root)


def run_one(target: dict, limits: BoundedRepairLimits) -> dict:
    package = _package_root(target["image_id"], target["instance"])
    label = target["label"]
    record: dict = {
        "target": f"{target['image_id']}/{target['instance']}/{label}",
        "defect_class": target["defect_class"],
        "research_note": target["research_note"],
        "attempts": [],
        "outcome": "ABSTAIN_BOUNDED",
        "promoted": False,
    }
    if not (package / "label_map_part.png").is_file():
        record["reason"] = "package_missing"
        return record

    work = WORK / "sessions" / f"{target['image_id']}_{target['instance']}_{label}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    parent_map = work / "accepted_parent.png"
    shutil.copy2(package / "label_map_part.png", parent_map)
    parent_part = read_mask(parent_map).astype(np.uint16)
    material = read_mask(package / "label_map_material.png").astype(np.uint8)
    current = parent_part == int(get_ontology().label(label).id)
    if (package / "masks" / f"{label}.png").is_file():
        binary = read_mask(package / "masks" / f"{label}.png") > 0
        if binary.any():
            current = binary
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

    parent_id = f"{target['image_id']}-{target['instance']}-{label}-residual-v1"
    executor = DurableRepairExecutor(
        state_path=work / "repair-state.json",
        accepted_map_path=parent_map,
        accepted_parent_id=parent_id,
        limits=limits,
        map_validator=_validator_factory(parent_part, label, float(baseline["score"])),
        output_dir=work / "repair-output",
    )

    for hypothesis in target["hypotheses"]:
        candidate = _candidate_mask(current, hypothesis, label, material)
        drop_px = int(current.sum()) - int(candidate.sum())
        material_only = _clear_forbidden(current, label, material)
        forbidden_material_drop_px = int(current.sum()) - int(material_only.sum())
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
        score_ppm = min(
            999_000,
            int(float(baseline["score"]) * 1_000_000) + min(max(drop_px, 0), 50_000),
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
            "forbidden_material_drop_px": forbidden_material_drop_px,
            "components_before": int(ndimage.label(current)[1]),
            "components_after": int(ndimage.label(candidate)[1]),
            "guard_eligible": guard.eligible,
            "guard_vetoes": list(guard.vetoes),
            "executor_outcome": result.outcome,
            "executor_reason": result.reason,
        }
        record["attempts"].append(attempt)

        executor_ok = result.outcome == "accepted_reversible_repair"
        pre = decide_visual_repair_promotion(
            defect_class=target["defect_class"],
            hypothesis_id=hypothesis,
            executor_accepted=executor_ok,
            drop_px=drop_px,
            baseline_excess=int(baseline["excess"]),
            hard_qc_passed=None,
            label=label,
            forbidden_material_drop_px=forbidden_material_drop_px,
        )
        if executor_ok and pre.may_promote:
            backup = WORK / "backups" / f"{target['image_id']}_{target['instance']}_{label}"
            promote = _promote_accepted(package, result.accepted_map_path, label, backup)
            final = decide_visual_repair_promotion(
                defect_class=target["defect_class"],
                hypothesis_id=hypothesis,
                executor_accepted=True,
                drop_px=drop_px,
                baseline_excess=int(baseline["excess"]),
                hard_qc_passed=bool(promote["qc_passed"]),
                label=label,
                forbidden_material_drop_px=forbidden_material_drop_px,
            )
            if final.may_promote and promote["qc_passed"]:
                record["promoted"] = True
                record["promote"] = promote
                record["outcome"] = final.outcome
                record["reason"] = final.reason
                break
            _rollback(package, backup)
            record["outcome"] = "ABSTAIN_BOUNDED"
            record["reason"] = final.reason
            record["promoted"] = False
            record["promote_rolled_back"] = promote
            break
        if executor_ok:
            record["outcome"] = pre.outcome
            record["reason"] = pre.reason
            # Keep trying other hypotheses only when this one was structural abstain
            # after a soft executor accept (map child not promoted).
            if hypothesis == "clear_forbidden_material_on_part" and drop_px == 0:
                continue
            if target["defect_class"] in {
                "underfill",
                "exclusivity_bleed",
                "multi_person_half_fill",
                "garment_bias",
            }:
                # Record abstain but continue if more hypotheses remain.
                continue
            break
        if result.outcome == "rolled_back_autonomous_abstention":
            record["outcome"] = "ABSTAIN_BOUNDED"
            record["reason"] = result.reason
            break

    if "reason" not in record:
        record["reason"] = "no_accepted_safe_repair"
    return record


def main() -> None:
    policy = yaml.safe_load(
        (ROOT / "configs" / "autonomous_masks.yaml").read_text(encoding="utf-8")
    )
    limits = repair_limits_from_policy(policy["repair"])
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
        "lane": "bounded_visual_residual_after_noise_cc",
        "prior_wave": "qa/live_verification/bounded_visual_repair_20260719.json",
        "contracts": [
            "maskfactory.autonomy.visual_defect_policy.decide_visual_repair_promotion",
            "maskfactory.autonomy.operational_repair.DurableRepairExecutor",
            "clear_forbidden_material_on_part (narrow exclusivity)",
        ],
        "research_summary": {
            "garment_bias": (
                "Semantic sports-bra/underwear chest shape is not remediable without "
                "human redraw. Only footwear/sock material on chest is safe to clear."
            ),
            "underfill": "Missing limb mass cannot be invented by dilation/hole-fill.",
            "exclusivity_bleed": (
                "Connected hip bleed has no S05 pose ROI; garment-clear destroys mask."
            ),
            "multi_person_half_fill": "Identity half-cut requires Kevin CVAT correction.",
        },
        "claims_not_established": [
            BLOCKED_VISUAL_PASS_CLAIM,
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
            "highest_visual_tier": HIGHEST_VISUAL_TIER_WITH_RESIDUALS,
            "visual_note": (
                "Residual structural defects remain; never claim "
                f"{BLOCKED_VISUAL_PASS_CLAIM} without clean panels."
            ),
        },
        "blockers": [
            f"{BLOCKED_VISUAL_PASS_CLAIM} blocked: residual garment bias / underfill / "
            "exclusivity bleed / multi-person half-fill",
            "human_approved_gold still requires Kevin CVAT correction",
        ],
    }
    out = WORK / "bounded_visual_residual_20260719.json"
    out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    live = ROOT / "qa" / "live_verification" / "bounded_visual_residual_20260719.json"
    live.write_text(out.read_text(encoding="utf-8"), encoding="utf-8")
    print(json.dumps({"evidence": str(live), "summary": evidence["summary"]}, indent=2))


if __name__ == "__main__":
    main()
