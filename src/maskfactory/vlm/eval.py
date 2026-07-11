"""Known-ground-truth VLM panel set, precision/recall gate, and change invalidation."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping

import numpy as np
from PIL import Image, ImageDraw

from ..io.png_strict import read_mask
from ..qa.panels import render_boundary_panel

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


class VlmEvalError(RuntimeError):
    """Calibration set or production gate is missing, stale, or below threshold."""


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    panel_file: str
    label: str
    expected_defect: bool
    seeded_problem: str | None


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
    required = {"id", "label", "source", "good_mask", "defect_mask", "defect_type"}
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
    for seed in seeds:
        paths = {
            name: (base / seed[name]).resolve() for name in ("source", "good_mask", "defect_mask")
        }
        if any(not path.is_file() for path in paths.values()):
            raise VlmEvalError(f"calibration seed file missing: {seed['id']}")
        with Image.open(paths["source"]) as opened:
            source = opened.convert("RGB")
        good = _binary_seed(paths["good_mask"], source.size)
        defect = _binary_seed(paths["defect_mask"], source.size)
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
        good_case = EvalCase(
            f"good_{index:02d}", f"panels/good_{index:02d}.png", seed["label"], False, None
        )
        defect_case = EvalCase(
            f"defect_{index:02d}",
            f"panels/defect_{index:02d}.png",
            seed["label"],
            True,
            seed["defect_type"],
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


def load_cases(root: Path) -> tuple[EvalCase, ...]:
    document = json.loads((Path(root) / "manifest.json").read_text(encoding="utf-8"))
    cases = tuple(EvalCase(**case) for case in document["cases"])
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


def _binary_seed(path: Path, source_size: tuple[int, int]) -> np.ndarray:
    with Image.open(path) as opened:
        if opened.mode != "L" or opened.size != source_size:
            raise VlmEvalError(f"calibration mask must be mode L at source dimensions: {path}")
    mask = read_mask(path)
    if set(np.unique(mask).tolist()) - {0, 255}:
        raise VlmEvalError(f"calibration mask is not binary: {path}")
    return mask > 0


def gate_fingerprint(*, model: str, prompt_version: str, prompt_path: Path) -> str:
    payload = b"\0".join((model.encode(), prompt_version.encode(), Path(prompt_path).read_bytes()))
    return hashlib.sha256(payload).hexdigest()


def evaluate_gate(
    cases: tuple[EvalCase, ...],
    predictions: Mapping[str, str],
    *,
    model: str,
    prompt_version: str,
    prompt_path: Path,
    output_dir: Path,
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
    report = EvalReport(
        model,
        prompt_version,
        gate_fingerprint(model=model, prompt_version=prompt_version, prompt_path=prompt_path),
        len(cases),
        len(cases) - defect_count,
        defect_count,
        tp,
        fp,
        fn,
        recall,
        precision,
        recall >= 0.90 and precision >= 0.80,
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
    from .client import OllamaClient, prepare_panel_input, review_part

    prompt = Path(prompt_path).read_text(encoding="utf-8")
    prepared_root = Path(output_dir) / "prepared"
    predictions: dict[str, str] = {}
    verdicts: list[dict] = []
    client = OllamaClient()
    for case in cases:
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
) -> dict:
    try:
        gate = json.loads(Path(gate_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VlmEvalError("VLM production gate unavailable") from exc
    current = gate_fingerprint(model=model, prompt_version=prompt_version, prompt_path=prompt_path)
    if gate.get("fingerprint") != current:
        raise VlmEvalError("VLM production gate invalidated by model or prompt change")
    if (
        gate.get("passed") is not True
        or gate.get("recall", 0) < 0.90
        or gate.get("precision", 0) < 0.80
    ):
        raise VlmEvalError("VLM production use refused: calibration threshold not passed")
    return gate


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
