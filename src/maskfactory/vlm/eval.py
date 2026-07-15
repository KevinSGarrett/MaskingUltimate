"""Known-ground-truth VLM panel set, precision/recall gate, and change invalidation."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

from ..io.png_strict import read_mask, write_binary_mask
from ..ontology import get_ontology
from ..packager import verify_packages
from ..qa.panels import render_boundary_panel, render_workhorse_evidence
from .client import DETERMINISTIC_GENERATION_OPTIONS, WORKHORSE_GENERATION_OPTIONS

DEFECT_TAXONOMY = (
    "wrong_side",
    "boundary_too_loose",
    "boundary_too_tight",
    "includes_clothing_as_skin",
    "includes_neighbor_part",
    "missing_visible_area",
    "mask_on_hidden_area",
    "finger_merge",
    "hair_edge_bad",
    "occlusion_error",
)
CALIBRATION_ORIGINS = {"generated", "owned_photo", "licensed", "consented_subject"}


class VlmEvalError(RuntimeError):
    """Calibration set or production gate is missing, stale, or below threshold."""


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    panel_file: str
    label: str
    expected_defect: bool
    seeded_problem: str | None
    evidence_dir: str | None = None
    crop_xyxy: tuple[int, int, int, int] | None = None
    source_size: tuple[int, int] | None = None


@dataclass(frozen=True)
class EvalReport:
    model: str
    prompt_version: str
    fingerprint: str
    total: int
    good_count: int
    defect_count: int
    true_positives: int
    false_positives: int
    false_negatives: int
    recall: float
    precision: float
    passed: bool
    generation_options: dict[str, int | float]


def generate_calibration_set(root: Path, *, test_fixture: bool = False) -> tuple[EvalCase, ...]:
    """Generate abstract evaluator fixtures; explicitly forbidden for production gating."""
    if not test_fixture:
        raise VlmEvalError(
            "abstract synthetic panels are test-only; production requires an explicit seed manifest"
        )
    root = Path(root)
    panels = root / "panels"
    panels.mkdir(parents=True, exist_ok=True)
    cases = []
    for index in range(20):
        case = EvalCase(
            f"good_{index:02d}", f"panels/good_{index:02d}.png", "left_forearm", False, None
        )
        _render_case(root / case.panel_file, None, index)
        cases.append(case)
    defects = tuple(DEFECT_TAXONOMY[index % len(DEFECT_TAXONOMY)] for index in range(20))
    for index, problem in enumerate(defects):
        case = EvalCase(
            f"defect_{index:02d}",
            f"panels/defect_{index:02d}_{problem}.png",
            "left_forearm",
            True,
            problem,
        )
        _render_case(root / case.panel_file, problem, index)
        cases.append(case)
    manifest = {
        "schema_version": "1.0.0",
        "good_count": 20,
        "defect_count": 20,
        "taxonomy": list(DEFECT_TAXONOMY),
        "cases": [asdict(case) for case in cases],
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return tuple(cases)


def build_calibration_from_seed_manifest(
    seed_manifest_path: Path, root: Path
) -> tuple[EvalCase, ...]:
    """Build production panels from explicit real source/good/defect mask records."""
    seed_manifest_path = Path(seed_manifest_path)
    try:
        seed_document = json.loads(seed_manifest_path.read_text(encoding="utf-8"))
        seeds = seed_document["seeds"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise VlmEvalError(f"calibration seed manifest invalid: {exc}") from exc
    if not isinstance(seeds, list) or len(seeds) != 20:
        raise VlmEvalError("production calibration requires exactly 20 explicit seed records")
    required = {
        "id",
        "label",
        "source",
        "good_mask",
        "defect_mask",
        "defect_type",
        "governance",
    }
    if any(not isinstance(seed, dict) or set(seed) != required for seed in seeds):
        raise VlmEvalError(f"every calibration seed requires exactly {sorted(required)}")
    if len({seed["id"] for seed in seeds}) != 20:
        raise VlmEvalError("calibration seed IDs must be unique")
    defects = [seed["defect_type"] for seed in seeds]
    if set(defects) != set(DEFECT_TAXONOMY) or any(
        defects.count(name) != 2 for name in DEFECT_TAXONOMY
    ):
        raise VlmEvalError("seed defects must cover every taxonomy value exactly twice")
    base = seed_manifest_path.parent
    validated = []
    signatures = set()
    source_hashes = set()
    authority = get_ontology()
    for seed in seeds:
        governance = seed["governance"]
        if not isinstance(governance, dict) or set(governance) != {
            "source_origin",
            "age_safety",
            "rights_evidence",
            "source_sha256",
        }:
            raise VlmEvalError(f"calibration governance invalid: {seed['id']}")
        if governance["source_origin"] not in CALIBRATION_ORIGINS:
            raise VlmEvalError(f"calibration source origin is not governed: {seed['id']}")
        if governance["age_safety"] != "clear_adult":
            raise VlmEvalError(f"calibration source is not age-cleared adult: {seed['id']}")
        if (
            not isinstance(governance["rights_evidence"], str)
            or not governance["rights_evidence"].strip()
        ):
            raise VlmEvalError(f"calibration rights evidence missing: {seed['id']}")
        try:
            label = authority.label(seed["label"])
        except Exception as exc:
            raise VlmEvalError(f"calibration label is not in the ontology: {seed['id']}") from exc
        if label.map not in {"part", "material"} or label.id is None:
            raise VlmEvalError(f"calibration label is not an indexed atomic class: {seed['id']}")
        paths = {
            name: (base / seed[name]).resolve() for name in ("source", "good_mask", "defect_mask")
        }
        if any(not path.is_file() for path in paths.values()):
            raise VlmEvalError(f"calibration seed file missing: {seed['id']}")
        with Image.open(paths["source"]) as opened:
            source = opened.convert("RGB")
        source_digest = hashlib.sha256(paths["source"].read_bytes()).hexdigest()
        if governance["source_sha256"] != source_digest:
            raise VlmEvalError(f"calibration source hash mismatch: {seed['id']}")
        if source_digest in source_hashes:
            raise VlmEvalError(f"calibration requires 20 distinct source images: {seed['id']}")
        source_hashes.add(source_digest)
        good = _binary_seed(paths["good_mask"], source.size)
        defect = _binary_seed(paths["defect_mask"], source.size)
        if not good.any():
            raise VlmEvalError(f"good mask is empty: {seed['id']}")
        if np.array_equal(good, defect):
            raise VlmEvalError(f"defect mask equals good mask: {seed['id']}")
        signature = (
            hashlib.sha256(paths["source"].read_bytes()).hexdigest(),
            hashlib.sha256(good.tobytes()).hexdigest(),
            hashlib.sha256(defect.tobytes()).hexdigest(),
            seed["label"],
        )
        if signature in signatures:
            raise VlmEvalError(f"duplicate calibration source/mask pair: {seed['id']}")
        signatures.add(signature)
        validated.append((seed, source, good, defect, paths))
    if len({seed["label"] for seed, *_ in validated}) < 5:
        raise VlmEvalError("production calibration must span at least five distinct labels")
    root = Path(root)
    (root / "panels").mkdir(parents=True, exist_ok=True)
    cases = []
    source_records = []
    for index, (seed, source, good, defect, paths) in enumerate(validated):
        good_evidence_dir = f"evidence/good_{index:02d}"
        defect_evidence_dir = f"evidence/defect_{index:02d}"
        good_evidence = render_workhorse_evidence(
            source, good, np.zeros_like(good), root / good_evidence_dir
        )
        defect_evidence = render_workhorse_evidence(
            source, defect, np.zeros_like(good), root / defect_evidence_dir
        )
        good_case = EvalCase(
            f"good_{index:02d}",
            f"panels/good_{index:02d}.png",
            seed["label"],
            False,
            None,
            good_evidence_dir,
            good_evidence.crop_xyxy,
            good_evidence.source_size,
        )
        defect_case = EvalCase(
            f"defect_{index:02d}",
            f"panels/defect_{index:02d}.png",
            seed["label"],
            True,
            seed["defect_type"],
            defect_evidence_dir,
            defect_evidence.crop_xyxy,
            defect_evidence.source_size,
        )
        protected = np.zeros_like(good)
        render_boundary_panel(source, good, protected, root / good_case.panel_file)
        render_boundary_panel(source, defect, protected, root / defect_case.panel_file)
        cases.extend((good_case, defect_case))
        source_records.append(
            {
                "seed_id": seed["id"],
                "source_sha256": hashlib.sha256(paths["source"].read_bytes()).hexdigest(),
                "good_mask_sha256": hashlib.sha256(good.tobytes()).hexdigest(),
                "defect_mask_sha256": hashlib.sha256(defect.tobytes()).hexdigest(),
                "defect_type": seed["defect_type"],
                "source_origin": seed["governance"]["source_origin"],
                "age_safety": seed["governance"]["age_safety"],
                "rights_evidence": seed["governance"]["rights_evidence"],
            }
        )
    manifest = {
        "schema_version": "2.0.0",
        "corpus_authority": "explicit_source_good_defect_pairs",
        "answer_text_embedded_in_panels": False,
        "good_count": 20,
        "defect_count": 20,
        "taxonomy": list(DEFECT_TAXONOMY),
        "cases": [asdict(case) for case in cases],
        "sources": source_records,
    }
    _atomic_json(root / "manifest.json", manifest)
    return tuple(cases)


def build_calibration_from_gold_selection(
    selection_path: Path,
    root: Path,
    *,
    packages_root: Path,
    images_root: Path,
    package_verifier=verify_packages,
) -> tuple[EvalCase, ...]:
    """Derive known-truth calibration pairs only from frozen, verified approved gold."""
    selection_path = Path(selection_path)
    root = Path(root)
    if root.exists():
        raise VlmEvalError(f"calibration output already exists: {root}")
    try:
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
        cases = selection["cases"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise VlmEvalError(f"gold calibration selection invalid: {exc}") from exc
    required = {"id", "package", "label", "defect_type", "auxiliary_label"}
    if selection.get("schema_version") != "1.0.0" or not isinstance(cases, list):
        raise VlmEvalError("gold calibration selection requires schema_version 1.0.0 and cases")
    if len(cases) != 20 or any(
        not isinstance(case, dict) or set(case) != required for case in cases
    ):
        raise VlmEvalError(f"gold calibration requires 20 cases with exactly {sorted(required)}")
    if len({case["id"] for case in cases}) != 20:
        raise VlmEvalError("gold calibration case IDs must be unique")
    defects = [case["defect_type"] for case in cases]
    if set(defects) != set(DEFECT_TAXONOMY) or any(
        defects.count(name) != 2 for name in DEFECT_TAXONOMY
    ):
        raise VlmEvalError("gold calibration defects must cover every taxonomy value exactly twice")

    packages_root = Path(packages_root).resolve()
    images_root = Path(images_root).resolve()
    authority = get_ontology()
    validated = []
    image_ids = set()
    labels = set()
    for case in cases:
        package = _contained_path(packages_root, str(case["package"]), "gold package")
        manifest_path = package / "manifest.json"
        frozen_path = package / ".maskfactory_frozen.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise VlmEvalError(f"gold package manifest invalid: {package}: {exc}") from exc
        image_id = str(manifest.get("image_id", ""))
        if image_id in image_ids:
            raise VlmEvalError(f"gold calibration requires 20 distinct image IDs: {image_id}")
        image_ids.add(image_id)
        if not frozen_path.is_file():
            raise VlmEvalError(f"gold package is not frozen: {package}")
        review = manifest.get("review", {})
        if (
            not review.get("reviewer")
            or not review.get("approved_at")
            or not isinstance(review.get("review_time_sec"), (int, float))
            or manifest.get("qa", {}).get("qa_overall") != "pass"
        ):
            raise VlmEvalError(f"gold package lacks approval or passing QA: {package}")
        visible = {
            name: entry
            for name, entry in manifest.get("parts", {}).items()
            if entry.get("visibility") in {"visible", "partially_visible", "occluded"}
        }
        if not visible or any(
            entry.get("status") != "human_approved_gold" for entry in visible.values()
        ):
            raise VlmEvalError(f"gold package has visible non-gold labels: {package}")
        verifications = tuple(package_verifier(package))
        if len(verifications) != 1 or not verifications[0].passed:
            raise VlmEvalError(f"gold package fails format/hash verification: {package}")
        try:
            label = authority.label(str(case["label"]), require_enabled=True)
        except Exception as exc:
            raise VlmEvalError(f"gold calibration label invalid: {case['id']}") from exc
        if (
            label.id is None
            or label.map not in {"part", "material"}
            or label.mask_type == "protected_qa"
        ):
            raise VlmEvalError(
                f"gold calibration label is not indexed mask authority: {case['id']}"
            )
        good_path = _package_mask_path(package, label)
        if not good_path.is_file():
            raise VlmEvalError(f"gold mask missing for calibration case: {case['id']}")
        source_path = package / str(manifest["source"]["source_file"])
        if not source_path.is_file():
            raise VlmEvalError(f"gold source missing for calibration case: {case['id']}")
        intake_path = images_root / image_id / "manifest.json"
        try:
            intake = json.loads(intake_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise VlmEvalError(f"intake authority missing for {image_id}: {exc}") from exc
        if intake.get("age_safety", {}).get("verdict") != "clear_adult":
            raise VlmEvalError(f"gold calibration source is not age-cleared adult: {image_id}")
        origin_note = str(manifest.get("source", {}).get("origin_note", "")).strip()
        if not origin_note:
            raise VlmEvalError(f"gold calibration rights evidence missing: {image_id}")
        auxiliary = case["auxiliary_label"]
        auxiliary_path = None
        if case["defect_type"] == "wrong_side":
            auxiliary = label.swap_partner
        if auxiliary is not None:
            try:
                auxiliary_definition = authority.label(str(auxiliary), require_enabled=True)
            except Exception as exc:
                raise VlmEvalError(
                    f"gold calibration auxiliary label invalid: {case['id']}"
                ) from exc
            auxiliary_path = _package_mask_path(package, auxiliary_definition)
            if not auxiliary_path.is_file():
                raise VlmEvalError(f"gold auxiliary mask missing: {case['id']}")
        labels.add(label.name)
        validated.append((case, package, manifest, source_path, good_path, auxiliary_path))
    if len(labels) < 5:
        raise VlmEvalError("gold calibration must span at least five distinct labels")

    stage = root.with_name(f".{root.name}.tmp-{uuid.uuid4().hex}")
    seed_root = stage / "seeds"
    try:
        seed_root.mkdir(parents=True)
        seeds = []
        for index, (case, _package, manifest, source_path, good_path, auxiliary_path) in enumerate(
            validated
        ):
            source_target = seed_root / f"source_{index:02d}{source_path.suffix.lower()}"
            good_target = seed_root / f"good_{index:02d}.png"
            defect_target = seed_root / f"defect_{index:02d}.png"
            shutil.copy2(source_path, source_target)
            good = read_mask(good_path) > 0
            auxiliary = read_mask(auxiliary_path) > 0 if auxiliary_path is not None else None
            defect = _seed_gold_defect(good, str(case["defect_type"]), auxiliary)
            source_size = (good.shape[1], good.shape[0])
            write_binary_mask(good_target, good, source_size=source_size)
            write_binary_mask(defect_target, defect, source_size=source_size)
            seeds.append(
                {
                    "id": str(case["id"]),
                    "label": str(case["label"]),
                    "source": source_target.name,
                    "good_mask": good_target.name,
                    "defect_mask": defect_target.name,
                    "defect_type": str(case["defect_type"]),
                    "governance": {
                        "source_origin": manifest["source"]["source_origin"],
                        "age_safety": "clear_adult",
                        "rights_evidence": manifest["source"]["origin_note"],
                        "source_sha256": hashlib.sha256(source_target.read_bytes()).hexdigest(),
                    },
                }
            )
        seed_manifest = seed_root / "manifest.json"
        _atomic_json(seed_manifest, {"schema_version": "1.0.0", "seeds": seeds})
        built = build_calibration_from_seed_manifest(seed_manifest, stage)
        os.replace(stage, root)
        return built
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def load_cases(root: Path) -> tuple[EvalCase, ...]:
    document = json.loads((Path(root) / "manifest.json").read_text(encoding="utf-8"))
    cases = tuple(
        EvalCase(
            **case
            | {
                "crop_xyxy": tuple(case["crop_xyxy"]) if case.get("crop_xyxy") else None,
                "source_size": tuple(case["source_size"]) if case.get("source_size") else None,
            }
        )
        for case in document["cases"]
    )
    if (
        len(cases) != 40
        or sum(not case.expected_defect for case in cases) != 20
        or sum(case.expected_defect for case in cases) != 20
    ):
        raise VlmEvalError("calibration set must contain exactly 20 good and 20 defect panels")
    if {case.seeded_problem for case in cases if case.expected_defect} != set(DEFECT_TAXONOMY):
        raise VlmEvalError("calibration defects do not span the full taxonomy")
    if any(not (Path(root) / case.panel_file).is_file() for case in cases):
        raise VlmEvalError("calibration panel file missing")
    return cases


def _contained_path(root: Path, relative: str, description: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise VlmEvalError(f"{description} escapes configured root: {relative}") from exc
    return candidate


def _package_mask_path(package: Path, label) -> Path:
    if label.mask_type == "protected_qa":
        directory = "protected"
    elif label.map == "material":
        directory = "masks_material"
    else:
        directory = "masks"
    return Path(package) / directory / f"{label.name}.png"


def _seed_gold_defect(
    good: np.ndarray,
    problem: str,
    auxiliary: np.ndarray | None,
) -> np.ndarray:
    """Apply one deterministic, visibly material defect without changing gold authority."""
    region = np.asarray(good).astype(bool)
    if region.ndim != 2 or not region.any():
        raise VlmEvalError("selected gold mask is empty")
    radius = max(2, min(region.shape) // 96)
    if problem == "boundary_too_loose":
        defect = ndimage.binary_dilation(region, iterations=radius)
    elif problem == "boundary_too_tight":
        defect = ndimage.binary_erosion(region, iterations=radius)
        if not defect.any():
            defect = region.copy()
            ys, xs = np.nonzero(region)
            defect[ys[len(ys) // 2 :], xs[len(xs) // 2 :]] = False
    elif problem == "missing_visible_area":
        defect = region.copy()
        ys, xs = np.nonzero(region)
        split = int(np.quantile(xs, 0.65))
        defect[:, split:] = False
    elif problem == "mask_on_hidden_area":
        shift = max(radius * 4, region.shape[1] // 4)
        translated = np.zeros_like(region)
        if shift < region.shape[1]:
            translated[:, shift:] = region[:, :-shift]
        defect = region | (translated & ~region)
        if np.array_equal(defect, region):
            defect = region | (ndimage.binary_dilation(region, iterations=radius * 4) & ~region)
    elif problem == "hair_edge_bad":
        inner = ndimage.binary_erosion(region, iterations=radius)
        outer = ndimage.binary_dilation(region, iterations=radius)
        yy, xx = np.indices(region.shape)
        checker = ((xx // radius) + (yy // radius)) % 2 == 0
        defect = (region & (inner | checker)) | ((outer & ~region) & checker)
    elif problem in {
        "wrong_side",
        "includes_clothing_as_skin",
        "includes_neighbor_part",
        "finger_merge",
        "occlusion_error",
    }:
        if auxiliary is None or np.asarray(auxiliary).shape != region.shape:
            raise VlmEvalError(f"{problem} requires a same-size auxiliary gold mask")
        other = np.asarray(auxiliary).astype(bool)
        if not other.any():
            raise VlmEvalError(f"{problem} auxiliary gold mask is empty")
        defect = other if problem == "wrong_side" else region | other
    else:
        raise VlmEvalError(f"unsupported calibration defect: {problem}")
    if not defect.any() or np.array_equal(defect, region):
        raise VlmEvalError(f"seeded {problem} defect did not materially change the gold mask")
    return np.asarray(defect).astype(bool)


def _binary_seed(path: Path, source_size: tuple[int, int]) -> np.ndarray:
    with Image.open(path) as opened:
        if opened.mode != "L" or opened.size != source_size:
            raise VlmEvalError(f"calibration mask must be mode L at source dimensions: {path}")
    mask = read_mask(path)
    if set(np.unique(mask).tolist()) - {0, 255}:
        raise VlmEvalError(f"calibration mask is not binary: {path}")
    return mask > 0


def gate_fingerprint(
    *,
    model: str,
    prompt_version: str,
    prompt_path: Path,
    generation_options: Mapping[str, int | float] | None = None,
) -> str:
    options = _resolved_generation_options(prompt_path, generation_options)
    prompt_path = Path(prompt_path)
    prompt_payloads = [prompt_path.read_bytes()]
    if prompt_path.name == "p_workhorse.txt":
        compare_path = prompt_path.with_name("p_compare.txt")
        if not compare_path.is_file():
            raise VlmEvalError("workhorse gate requires the P-COMPARE prompt")
        prompt_payloads.append(compare_path.read_bytes())
        prompt_payloads.extend(
            path.read_bytes()
            for path in (
                Path(__file__).with_name("workhorse.py"),
                Path(__file__).with_name("client.py"),
                Path(__file__).parents[1] / "qa" / "panels.py",
                Path(__file__).with_name("production.py"),
                Path(__file__).with_name("prompts") / "p_image.txt",
            )
        )
        prompt_payloads.append(b"ollama_think=false")
    payload = b"\0".join(
        (
            model.encode(),
            prompt_version.encode(),
            *prompt_payloads,
            json.dumps(options, sort_keys=True, separators=(",", ":")).encode(),
        )
    )
    return hashlib.sha256(payload).hexdigest()


def evaluate_gate(
    cases: tuple[EvalCase, ...],
    predictions: Mapping[str, str],
    *,
    model: str,
    prompt_version: str,
    prompt_path: Path,
    output_dir: Path,
    generation_options: Mapping[str, int | float] | None = None,
) -> EvalReport:
    if set(predictions) != {case.case_id for case in cases}:
        raise VlmEvalError("predictions must cover every calibration case exactly once")
    if not set(predictions.values()) <= {"pass", "fail", "uncertain"}:
        raise VlmEvalError("prediction verdict outside closed vocabulary")
    tp = sum(case.expected_defect and predictions[case.case_id] == "fail" for case in cases)
    fp = sum(not case.expected_defect and predictions[case.case_id] == "fail" for case in cases)
    fn = sum(case.expected_defect and predictions[case.case_id] != "fail" for case in cases)
    defect_count = sum(case.expected_defect for case in cases)
    recall = tp / defect_count
    precision = tp / (tp + fp) if tp + fp else 0.0
    options = _resolved_generation_options(prompt_path, generation_options)
    report = EvalReport(
        model=model,
        prompt_version=prompt_version,
        fingerprint=gate_fingerprint(
            model=model,
            prompt_version=prompt_version,
            prompt_path=prompt_path,
            generation_options=options,
        ),
        total=len(cases),
        good_count=len(cases) - defect_count,
        defect_count=defect_count,
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        recall=recall,
        precision=precision,
        passed=recall >= 0.90 and precision >= 0.80,
        generation_options=options,
    )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_json(
        output_dir / f"eval_{model.replace(':', '_')}_{prompt_version}.json", asdict(report)
    )
    _atomic_json(output_dir / "production_gate.json", asdict(report))
    return report


def predict_live(
    cases: tuple[EvalCase, ...],
    *,
    calibration_root: Path,
    model: str,
    prompt_path: Path,
    output_dir: Path,
    gpu_lock_path: Path,
) -> dict[str, str]:
    """Run the fixed set through the local-only production part-review path."""
    from ..qa.panels import WorkhorseEvidence
    from .client import OllamaClient, prepare_panel_input, review_part
    from .workhorse import review_part_workhorse

    prompt = Path(prompt_path).read_text(encoding="utf-8")
    prepared_root = Path(output_dir) / "prepared"
    predictions: dict[str, str] = {}
    verdicts: list[dict] = []
    client = OllamaClient()
    workhorse_mode = Path(prompt_path).name == "p_workhorse.txt"
    for case in cases:
        if workhorse_mode:
            if case.evidence_dir is None or case.crop_xyxy is None or case.source_size is None:
                raise VlmEvalError("workhorse calibration case lacks independent evidence metadata")
            evidence_root = Path(calibration_root) / case.evidence_dir
            names = (
                "full_context.png",
                "source_crop.png",
                "mask.png",
                "overlay.png",
                "contour.png",
                "neighbor_overlap.png",
            )
            evidence = WorkhorseEvidence(
                tuple(evidence_root / name for name in names),
                tuple(case.crop_xyxy),
                tuple(case.source_size),
            )
            if any(not path.is_file() for path in evidence.images):
                raise VlmEvalError("workhorse calibration evidence image missing")
            verdict = review_part_workhorse(
                client,
                label=case.label,
                evidence=evidence,
                model=model,
                prompt_template=prompt,
                prompt_version="calibration",
                gpu_lock_path=gpu_lock_path,
                generation_options=WORKHORSE_GENERATION_OPTIONS,
            )
        else:
            prepared = prepare_panel_input(
                Path(calibration_root) / case.panel_file,
                prepared_root / f"{case.case_id}.png",
            )
            verdict = review_part(
                client,
                label=case.label,
                panel_path=prepared,
                panel_file=case.panel_file,
                model=model,
                prompt_template=prompt,
                prompt_version="calibration",
                gpu_lock_path=gpu_lock_path,
                generation_options=DETERMINISTIC_GENERATION_OPTIONS,
            )
        predictions[case.case_id] = verdict.verdict
        verdicts.append(asdict(verdict) | {"problems": list(verdict.problems)})
    _atomic_json(
        Path(output_dir) / f"live_verdicts_{model.replace(':', '_')}.json", {"verdicts": verdicts}
    )
    _atomic_json(Path(output_dir) / f"predictions_{model.replace(':', '_')}.json", predictions)
    return predictions


def require_current_gate(
    gate_path: Path,
    *,
    model: str,
    prompt_version: str,
    prompt_path: Path,
    generation_options: Mapping[str, int | float] | None = None,
) -> dict:
    try:
        gate = json.loads(Path(gate_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VlmEvalError("VLM production gate unavailable") from exc
    options = _resolved_generation_options(prompt_path, generation_options)
    current = gate_fingerprint(
        model=model,
        prompt_version=prompt_version,
        prompt_path=prompt_path,
        generation_options=options,
    )
    if gate.get("fingerprint") != current:
        raise VlmEvalError(
            "VLM production gate invalidated by model, prompt, or generation-options change"
        )
    if gate.get("generation_options") != options:
        raise VlmEvalError("VLM production gate generation options are not current")
    if (
        gate.get("passed") is not True
        or gate.get("recall", 0) < 0.90
        or gate.get("precision", 0) < 0.80
    ):
        raise VlmEvalError("VLM production use refused: calibration threshold not passed")
    return gate


def _resolved_generation_options(
    prompt_path: Path,
    generation_options: Mapping[str, int | float] | None,
) -> dict[str, int | float]:
    if generation_options is not None:
        return dict(generation_options)
    defaults = (
        WORKHORSE_GENERATION_OPTIONS
        if Path(prompt_path).name == "p_workhorse.txt"
        else DETERMINISTIC_GENERATION_OPTIONS
    )
    return dict(defaults)


def _render_case(path: Path, problem: str | None, variant: int) -> None:
    tile_size = 512
    panel = Image.new("RGB", (tile_size * 5, tile_size), (24, 24, 24))
    colors = ((90, 120, 160), (0, 0, 0), (90, 120, 160), (90, 120, 160), (20, 20, 20))
    for tile, color in enumerate(colors):
        ImageDraw.Draw(panel).rectangle(
            (tile * tile_size, 0, (tile + 1) * tile_size - 1, tile_size - 1), fill=color
        )
    source_box = (190, 80, 320, 440)
    mask_box = list(source_box)
    if problem == "boundary_too_loose":
        mask_box = [160, 60, 350, 460]
    elif problem in {"boundary_too_tight", "missing_visible_area"}:
        mask_box = [215, 120, 300, 390]
    elif problem in {"wrong_side", "includes_neighbor_part", "mask_on_hidden_area"}:
        mask_box = [330, 80, 460, 440]
    elif problem == "finger_merge":
        mask_box = [175, 80, 355, 440]
    elif problem == "hair_edge_bad":
        mask_box = [185, 40, 330, 250]
    elif problem == "occlusion_error":
        mask_box = [190, 80, 320, 490]
    elif problem == "includes_clothing_as_skin":
        mask_box = [175, 80, 335, 440]
    for tile in (0, 2, 3):
        offset = tile * tile_size
        ImageDraw.Draw(panel).rounded_rectangle(
            (offset + source_box[0], source_box[1], offset + source_box[2], source_box[3]),
            radius=35,
            fill=(205, 155, 125),
        )
    draw = ImageDraw.Draw(panel)
    draw.rectangle(
        tuple(value + (tile_size if index % 2 == 0 else 0) for index, value in enumerate(mask_box)),
        fill=(255, 255, 255),
    )
    overlay = tuple(
        value + (2 * tile_size if index % 2 == 0 else 0) for index, value in enumerate(mask_box)
    )
    draw.rectangle(overlay, fill=(255, 64, 64), outline=(255, 255, 255), width=4)
    contour = tuple(
        value + (3 * tile_size if index % 2 == 0 else 0) for index, value in enumerate(mask_box)
    )
    draw.rectangle(contour, outline=(0, 255, 255), width=5)
    if problem in {"includes_neighbor_part", "includes_clothing_as_skin", "occlusion_error"}:
        draw.rectangle((4 * tile_size + 250, 180, 4 * tile_size + 420, 360), fill=(255, 0, 255))
    draw.text((12, 12), f"case {variant:02d} | {problem or 'good'}", fill=(255, 255, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    panel.save(path, format="PNG")  # png-strict: allow (RGB calibration panel, never mask)


def _atomic_json(path: Path, document: dict) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
