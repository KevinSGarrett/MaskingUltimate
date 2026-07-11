"""S03 dual human-parsing execution, remapping, degradation, and evidence."""

from __future__ import annotations

import json
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from PIL import Image

from ..io.png_strict import write_binary_mask, write_grayscale, write_label_map


class ParsingError(ValueError):
    """A parsing provider returned output that violates the S03 contract."""


@dataclass(frozen=True)
class ModelParsing:
    """Indexed prediction and CxHxW probabilities from one parser."""

    labels: np.ndarray
    probabilities: np.ndarray


class ParsingProvider(Protocol):
    def __call__(self, image: np.ndarray, *, scale: float = 1.0) -> ModelParsing: ...


class WslParserProvider:
    """Pinned Sapiens/SCHP provider executed in the authoritative WSL CUDA env."""

    CLASS_COUNTS = {"sapiens": 28, "schp_atr": 18}

    def __init__(
        self,
        parser: str,
        checkpoint: Path,
        work_dir: Path,
        *,
        wsl_distribution: str = "Ubuntu-22.04",
        python_path: str = "/home/kevin/miniforge3/envs/maskfactory/bin/python",
        timeout_sec: int = 900,
    ) -> None:
        if parser not in self.CLASS_COUNTS:
            raise ParsingError(f"unsupported WSL parser: {parser}")
        if not Path(checkpoint).is_file():
            raise ParsingError(f"parser checkpoint missing: {checkpoint}")
        self.parser = parser
        self.checkpoint = Path(checkpoint)
        self.work_dir = Path(work_dir)
        self.wsl_distribution = wsl_distribution
        self.python_path = python_path
        self.timeout_sec = timeout_sec

    def __call__(self, image: np.ndarray, *, scale: float = 1.0) -> ModelParsing:
        source = np.asarray(image)
        if source.ndim != 3 or source.shape[2] not in {3, 4} or not 0 < scale <= 1:
            raise ParsingError("provider image/scale invalid")
        original_shape = source.shape[:2]
        if source.shape[2] == 4:
            source = source[:, :, :3]
        if scale != 1:
            target = (
                max(1, round(source.shape[1] * scale)),
                max(1, round(source.shape[0] * scale)),
            )
            source = np.asarray(
                Image.fromarray(source.astype(np.uint8), mode="RGB").resize(
                    target, Image.Resampling.BILINEAR
                )
            )
        token = uuid.uuid4().hex
        self.work_dir.mkdir(parents=True, exist_ok=True)
        input_path = self.work_dir / f"{self.parser}_{token}.png"
        output_path = self.work_dir / f"{self.parser}_{token}.npz"
        Image.fromarray(source.astype(np.uint8), mode="RGB").save(input_path, format="PNG")
        root = Path(__file__).resolve().parents[3]
        command = [
            "wsl",
            "-d",
            self.wsl_distribution,
            "--",
            self.python_path,
            _wsl_path(root / "tools" / "run_parser_wsl.py"),
            "--parser",
            self.parser,
            "--checkpoint",
            _wsl_path(self.checkpoint),
            "--image",
            _wsl_path(input_path),
            "--output",
            _wsl_path(output_path),
        ]
        try:
            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ParsingError(f"{self.parser} WSL launch failed: {exc}") from exc
        if process.returncode:
            detail = process.stderr.strip()[-2000:] or process.stdout.strip()[-2000:]
            if "out of memory" in detail.lower():
                raise RuntimeError(f"CUDA out of memory: {detail}")
            raise ParsingError(f"{self.parser} WSL inference failed: {detail}")
        try:
            metadata = json.loads(process.stdout.strip().splitlines()[-1])
            with np.load(output_path, allow_pickle=False) as archive:
                labels = archive["labels"]
                probabilities = archive["probabilities"]
        except (OSError, ValueError, KeyError, IndexError, json.JSONDecodeError) as exc:
            raise ParsingError(f"{self.parser} output invalid: {exc}") from exc
        expected_classes = self.CLASS_COUNTS[self.parser]
        if metadata.get("parser") != self.parser or probabilities.shape[0] != expected_classes:
            raise ParsingError(f"{self.parser} metadata/class-count mismatch")
        if labels.shape != source.shape[:2] or probabilities.shape[1:] != source.shape[:2]:
            raise ParsingError(f"{self.parser} provider geometry mismatch")
        if source.shape[:2] != original_shape:
            probabilities = _restore_probabilities(probabilities, original_shape)
            labels = probabilities.argmax(axis=0).astype(np.uint8)
        return ModelParsing(labels, probabilities)


@dataclass(frozen=True)
class S03Result:
    sapiens_path: Path | None
    schp_path: Path
    sapiens_confidence_paths: tuple[Path, ...]
    schp_confidence_paths: tuple[Path, ...]
    disagreement_pct: float | None
    parsing_degraded: bool
    sapiens_scale: float | None


def run_s03_production(
    image_path: Path,
    *,
    sapiens_checkpoint: Path,
    schp_checkpoint: Path,
    sapiens_map: dict[int, dict[str, Any]],
    schp_map: dict[int, dict[str, Any]],
    output_dir: Path,
) -> S03Result:
    """Execute registered Sapiens primary and mandatory SCHP-ATR companion."""
    with Image.open(image_path) as opened:
        image = np.asarray(opened.convert("RGB"))
    provider_work = Path(output_dir) / "provider_work"
    return run_parsing(
        image,
        sapiens=WslParserProvider("sapiens", sapiens_checkpoint, provider_work / "sapiens"),
        schp=WslParserProvider("schp_atr", schp_checkpoint, provider_work / "schp_atr"),
        sapiens_map=sapiens_map,
        schp_map=schp_map,
        output_dir=output_dir,
    )


def run_parsing(
    image: np.ndarray,
    *,
    sapiens: ParsingProvider,
    schp: ParsingProvider,
    sapiens_map: dict[int, dict[str, Any]],
    schp_map: dict[int, dict[str, Any]],
    output_dir: Path,
) -> S03Result:
    """Always run SCHP; run Sapiens with half-resolution OOM retry and fallback."""
    image = np.asarray(image)
    if image.ndim != 3 or image.shape[2] not in (3, 4):
        raise ParsingError("image must be HxWx3 or HxWx4")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    schp_output = _validated(schp(image, scale=1.0), image.shape[:2], len(schp_map), "SCHP")
    schp_path, schp_confidence = _write_output(output_dir, "schp_atr", schp_output)

    sapiens_output: ModelParsing | None = None
    sapiens_scale: float | None = 1.0
    degraded = False
    try:
        sapiens_output = sapiens(image, scale=1.0)
    except (MemoryError, RuntimeError) as first_error:
        if not _is_oom(first_error):
            raise
        sapiens_scale = 0.5
        try:
            sapiens_output = sapiens(image, scale=0.5)
        except (MemoryError, RuntimeError) as second_error:
            if not _is_oom(second_error):
                raise
            degraded = True
            sapiens_scale = None

    sapiens_path = None
    sapiens_confidence: tuple[Path, ...] = ()
    disagreement = None
    if sapiens_output is not None:
        sapiens_output = _validated(sapiens_output, image.shape[:2], len(sapiens_map), "Sapiens")
        sapiens_path, sapiens_confidence = _write_output(output_dir, "sapiens_28", sapiens_output)
        disagreement = _disagreement_pct(
            sapiens_output.labels, schp_output.labels, sapiens_map, schp_map
        )

    metrics = {
        "parsing_degraded": degraded,
        "sapiens_scale": sapiens_scale,
        "sapiens_schp_disagreement_pct": disagreement,
        "schp_always_run": True,
    }
    (output_dir / "parsing_metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return S03Result(
        sapiens_path,
        schp_path,
        sapiens_confidence,
        schp_confidence,
        disagreement,
        degraded,
        sapiens_scale,
    )


def remap_priors(labels: np.ndarray, mapping: dict[int, dict[str, Any]]) -> np.ndarray:
    """Return an object array of stable prior signatures for remap tests/fusion."""
    labels = np.asarray(labels)
    output = np.empty(labels.shape, dtype=object)
    unknown = set(np.unique(labels).tolist()) - set(mapping)
    if unknown:
        raise ParsingError(f"unmapped parser classes: {sorted(unknown)}")
    for index, entry in mapping.items():
        parts = tuple(sorted(entry.get("part_priors", ())))
        materials = tuple(sorted(entry.get("material_priors", ())))
        signature = (parts, materials)
        for flat_index in np.flatnonzero(labels == index):
            output.flat[flat_index] = signature
    return output


def suppress_co_subject_parsing(
    output_dir: Path,
    *,
    other_person_protected_full: np.ndarray,
    target_silhouette_full: np.ndarray,
    context_bbox_xyxy: tuple[int, int, int, int],
) -> dict[str, int | bool]:
    """Zero co-subject parser evidence before S05 and record true overlap as ambiguous."""
    output_dir = Path(output_dir)
    protected_full = np.asarray(other_person_protected_full).astype(bool)
    target_full = np.asarray(target_silhouette_full).astype(bool)
    if protected_full.ndim != 2 or target_full.shape != protected_full.shape:
        raise ParsingError("co-subject protection and target silhouette must share full canvas")
    left, top, right, bottom = context_bbox_xyxy
    protected = protected_full[top:bottom, left:right]
    target = target_full[top:bottom, left:right]
    if protected.shape != target.shape:
        raise ParsingError("invalid context projection for co-subject suppression")
    for stem in ("sapiens_28", "schp_atr"):
        labels_path = output_dir / f"{stem}.png"
        if not labels_path.is_file():
            continue
        labels = np.asarray(Image.open(labels_path))
        if labels.shape != protected.shape:
            raise ParsingError(f"{stem} dimensions differ from co-subject protection")
        labels = labels.astype(np.uint8, copy=True)
        labels[protected] = 0
        write_label_map(labels_path, labels, bits=8)
        confidence_paths = sorted((output_dir / f"{stem}_confidence").glob("class_*.png"))
        for index, path in enumerate(confidence_paths):
            confidence = np.asarray(Image.open(path).convert("L")).copy()
            confidence[protected] = 255 if index == 0 else 0
            write_grayscale(path, confidence, source_size=(labels.shape[1], labels.shape[0]))
    ambiguity = protected & target
    write_binary_mask(
        output_dir / "other_person_suppressed.png",
        protected,
        source_size=(protected.shape[1], protected.shape[0]),
    )
    write_binary_mask(
        output_dir / "ambiguous_do_not_use.png",
        ambiguity,
        source_size=(ambiguity.shape[1], ambiguity.shape[0]),
    )
    metrics_path = output_dir / "parsing_metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics.update(
        {
            "co_subject_suppressed_px": int(protected.sum()),
            "co_subject_ambiguous_px": int(ambiguity.sum()),
            "ambiguous_do_not_use": bool(ambiguity.any()),
            "parsing_degraded": bool(metrics.get("parsing_degraded")) or bool(ambiguity.any()),
        }
    )
    metrics_path.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "suppressed_px": int(protected.sum()),
        "ambiguous_px": int(ambiguity.sum()),
        "careful_review": bool(ambiguity.any()),
    }


def _validated(
    output: ModelParsing, shape: tuple[int, int], class_count: int, name: str
) -> ModelParsing:
    labels = np.asarray(output.labels)
    probabilities = np.asarray(output.probabilities, dtype=np.float32)
    if labels.shape != shape or probabilities.shape != (class_count, *shape):
        raise ParsingError(f"{name} output shape mismatch")
    if labels.min() < 0 or labels.max() >= class_count:
        raise ParsingError(f"{name} label outside class vocabulary")
    if not np.isfinite(probabilities).all() or probabilities.min() < 0 or probabilities.max() > 1:
        raise ParsingError(f"{name} probabilities must be finite in 0..1")
    return ModelParsing(labels.astype(np.uint8), probabilities)


def _write_output(
    output_dir: Path, stem: str, output: ModelParsing
) -> tuple[Path, tuple[Path, ...]]:
    labels_path = write_label_map(output_dir / f"{stem}.png", output.labels, bits=8)
    confidence_dir = output_dir / f"{stem}_confidence"
    confidence_paths = tuple(
        write_grayscale(
            confidence_dir / f"class_{index:02d}.png",
            np.rint(probability * 255).astype(np.uint8),
            source_size=(output.labels.shape[1], output.labels.shape[0]),
        )
        for index, probability in enumerate(output.probabilities)
    )
    return labels_path, confidence_paths


def _disagreement_pct(
    sapiens_labels: np.ndarray,
    schp_labels: np.ndarray,
    sapiens_map: dict[int, dict[str, Any]],
    schp_map: dict[int, dict[str, Any]],
) -> float:
    sapiens_priors = remap_priors(sapiens_labels, sapiens_map)
    schp_priors = remap_priors(schp_labels, schp_map)
    disagreements = 0
    for sapiens_prior, schp_prior in zip(sapiens_priors.flat, schp_priors.flat, strict=True):
        sapiens_set = set(sapiens_prior[0]) | set(sapiens_prior[1])
        schp_set = set(schp_prior[0]) | set(schp_prior[1])
        disagreements += not bool(sapiens_set & schp_set)
    return 100.0 * disagreements / sapiens_labels.size


def _is_oom(error: BaseException) -> bool:
    return isinstance(error, MemoryError) or "out of memory" in str(error).lower()


def _restore_probabilities(probabilities: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    height, width = shape
    restored = np.stack(
        [
            np.asarray(
                Image.fromarray(channel.astype(np.float32), mode="F").resize(
                    (width, height), Image.Resampling.BILINEAR
                ),
                dtype=np.float32,
            )
            for channel in probabilities
        ]
    )
    normalizer = restored.sum(axis=0, keepdims=True)
    return np.divide(restored, normalizer, out=np.zeros_like(restored), where=normalizer > 0)


def _wsl_path(path: Path) -> str:
    resolved = Path(path).resolve()
    drive = resolved.drive.rstrip(":").lower()
    if not drive:
        raise ParsingError(f"expected Windows drive path: {resolved}")
    return f"/mnt/{drive}{resolved.as_posix().split(':', 1)[1]}"
