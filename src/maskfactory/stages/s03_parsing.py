"""S03 dual human-parsing execution, remapping, degradation, and evidence."""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from PIL import Image

from ..io.png_strict import write_binary_mask, write_grayscale, write_label_map
from ..io.writers import write_json_atomic
from ..models.registry import (
    DEFAULT_MODELS_ROOT,
    DEFAULT_REGISTRY,
    ModelRegistryError,
    resolve_registered_role,
)
from ..ontology import get_ontology


class ParsingError(ValueError):
    """A parsing provider returned output that violates the S03 contract."""


@dataclass(frozen=True)
class ModelParsing:
    """Indexed prediction and CxHxW probabilities from one parser."""

    labels: np.ndarray
    probabilities: np.ndarray


class ParsingProvider(Protocol):
    def __call__(self, image: np.ndarray, *, scale: float = 1.0) -> ModelParsing: ...


class ChampionBodypartSlot(Protocol):
    class_names: tuple[str, ...]

    def __call__(self, image: np.ndarray, labels: tuple[str, ...]) -> dict[str, np.ndarray]: ...

    def close(self) -> None: ...


ChampionLoader = Callable[..., ChampionBodypartSlot]


class WslParserProvider:
    """Pinned Sapiens/SCHP provider executed in the authoritative WSL CUDA env."""

    CLASS_COUNTS = {"sapiens": 28, "schp_atr": 18}
    SAPIENS_REVISION = "ea5545c735d1fc994d0d1aafede27df892761322"
    SCHP_REVISION = "eb84c432cc697f494d99662a05f2335eb2f26095"

    def __init__(
        self,
        parser: str,
        checkpoint: Path,
        work_dir: Path,
        *,
        wsl_distribution: str = "Ubuntu-22.04",
        python_path: str = "/home/kevin/miniforge3/envs/maskfactory/bin/python",
        timeout_sec: int = 900,
        sapiens_long_side: int = 1024,
        tile_size: int = 1536,
        tile_overlap: int = 128,
        local_cuda_python: Path | None = None,
        schp_cache: Path | None = None,
    ) -> None:
        if parser not in self.CLASS_COUNTS:
            raise ParsingError(f"unsupported WSL parser: {parser}")
        if not Path(checkpoint).is_file():
            raise ParsingError(f"parser checkpoint missing: {checkpoint}")
        if sapiens_long_side != 1024:
            raise ParsingError("pinned Sapiens TorchScript requires governed long_side=1024")
        if tile_size <= 0 or tile_overlap < 0 or tile_overlap >= tile_size:
            raise ParsingError("parser tile contract requires 0 <= overlap < tile size")
        self.parser = parser
        self.checkpoint = Path(checkpoint)
        self.work_dir = Path(work_dir)
        self.wsl_distribution = wsl_distribution
        self.python_path = python_path
        self.timeout_sec = timeout_sec
        self.sapiens_long_side = sapiens_long_side
        self.tile_size = tile_size
        self.tile_overlap = tile_overlap
        self.local_cuda_python = Path(local_cuda_python) if local_cuda_python is not None else None
        self.schp_cache = Path(schp_cache) if schp_cache is not None else None
        if self.local_cuda_python is not None and not self.local_cuda_python.is_file():
            raise ParsingError(
                f"configured local CUDA Python does not exist: {self.local_cuda_python}"
            )

    def __call__(self, image: np.ndarray, *, scale: float = 1.0) -> ModelParsing:
        source = np.asarray(image)
        if (
            source.ndim != 3
            or source.shape[2] not in {3, 4}
            or source.dtype != np.uint8
            or not 0 < scale <= 1
        ):
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
        arguments = [
            "--parser",
            self.parser,
            "--checkpoint",
            str(self.checkpoint.resolve()),
            "--image",
            str(input_path.resolve()),
            "--output",
            str(output_path.resolve()),
            "--sapiens-long-side",
            str(self.sapiens_long_side),
            "--tile-size",
            str(self.tile_size),
            "--tile-overlap",
            str(self.tile_overlap),
        ]
        if self.local_cuda_python is not None:
            command = [
                str(self.local_cuda_python),
                str(root / "tools" / "run_parser_wsl.py"),
                *arguments,
            ]
            launcher = "local_cuda"
            environment = os.environ.copy()
            if self.schp_cache is not None:
                environment["MASKFACTORY_SCHP_CACHE"] = str(self.schp_cache.resolve())
        else:
            wsl_arguments = [
                _wsl_path(Path(value)) if index in {3, 5, 7} else value
                for index, value in enumerate(arguments)
            ]
            command = [
                "wsl",
                "-d",
                self.wsl_distribution,
                "--",
                self.python_path,
                _wsl_path(root / "tools" / "run_parser_wsl.py"),
                *wsl_arguments,
            ]
            launcher = "wsl_cuda"
            environment = None
        try:
            try:
                process = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_sec,
                    check=False,
                    **({"env": environment} if environment is not None else {}),
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ParsingError(f"{self.parser} {launcher} launch failed: {exc}") from exc
            if process.returncode:
                detail = process.stderr.strip()[-2000:] or process.stdout.strip()[-2000:]
                if "out of memory" in detail.lower():
                    raise RuntimeError(f"CUDA out of memory: {detail}")
                raise ParsingError(f"{self.parser} {launcher} inference failed: {detail}")
            try:
                metadata = json.loads(process.stdout.strip().splitlines()[-1])
                with np.load(output_path, allow_pickle=False) as archive:
                    labels = archive["labels"]
                    probabilities = archive["probabilities"]
            except (OSError, ValueError, KeyError, IndexError, json.JSONDecodeError) as exc:
                raise ParsingError(f"{self.parser} output invalid: {exc}") from exc
        finally:
            input_path.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)
        expected_classes = self.CLASS_COUNTS[self.parser]
        expected_metadata: dict[str, object] = {
            "protocol_version": 1,
            "parser": self.parser,
            "class_count": expected_classes,
            "labels_shape": list(labels.shape),
            "probabilities_shape": list(probabilities.shape),
        }
        if self.parser == "sapiens":
            expected_metadata.update(
                {
                    "model_revision": self.SAPIENS_REVISION,
                    "precision": "bf16",
                    "model_input": [1024, 768],
                    "tile_size": self.tile_size,
                    "tile_overlap": self.tile_overlap,
                }
            )
        else:
            expected_metadata.update(
                {
                    "model_revision": self.SCHP_REVISION,
                    "precision": "fp32",
                    "model_input": [512, 512],
                    "dataset": "atr",
                }
            )
        mismatches = {
            key: (metadata.get(key), expected)
            for key, expected in expected_metadata.items()
            if metadata.get(key) != expected
        }
        if mismatches:
            raise ParsingError(f"{self.parser} metadata violates governed contract: {mismatches}")
        if not isinstance(metadata.get("tile_count"), int) or metadata["tile_count"] < 1:
            raise ParsingError(f"{self.parser} metadata requires positive integer tile_count")
        if not isinstance(metadata.get("device"), str) or not metadata["device"].strip():
            raise ParsingError(f"{self.parser} metadata requires CUDA device identity")
        if "+cu128" not in str(metadata.get("torch", "")):
            raise ParsingError(
                f"{self.parser} metadata requires the governed cu128 PyTorch runtime"
            )
        if labels.dtype != np.uint8 or probabilities.dtype != np.float32:
            raise ParsingError(f"{self.parser} archive dtype mismatch")
        if labels.shape != source.shape[:2] or probabilities.shape[1:] != source.shape[:2]:
            raise ParsingError(f"{self.parser} provider geometry mismatch")
        _validate_distribution(labels, probabilities, expected_classes, self.parser)
        if source.shape[:2] != original_shape:
            probabilities = _restore_probabilities(probabilities, original_shape)
            labels = probabilities.argmax(axis=0).astype(np.uint8)
        runtime_document = {
            "launcher": launcher,
            "python": str(self.local_cuda_python or self.python_path),
            "scale": scale,
            **metadata,
        }
        (self.work_dir / "runtime.json").write_text(
            json.dumps(runtime_document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
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


@dataclass(frozen=True)
class CustomBodypartResult:
    map_path: Path
    provenance_path: Path
    model_key: str


def run_s03_production(
    image_path: Path,
    *,
    sapiens_checkpoint: Path,
    schp_checkpoint: Path,
    sapiens_map: dict[int, dict[str, Any]],
    schp_map: dict[int, dict[str, Any]],
    output_dir: Path,
    sapiens_long_side: int = 1024,
    tile_size: int = 1536,
    tile_overlap: int = 128,
    local_cuda_python: Path | None = None,
    schp_cache: Path | None = None,
) -> S03Result:
    """Execute registered Sapiens primary and mandatory SCHP-ATR companion."""
    with Image.open(image_path) as opened:
        image = np.asarray(opened.convert("RGB"))
    provider_work = Path(output_dir) / "provider_work"
    return run_parsing(
        image,
        sapiens=WslParserProvider(
            "sapiens",
            sapiens_checkpoint,
            provider_work / "sapiens",
            sapiens_long_side=sapiens_long_side,
            tile_size=tile_size,
            tile_overlap=tile_overlap,
            local_cuda_python=local_cuda_python,
            schp_cache=schp_cache,
        ),
        schp=WslParserProvider(
            "schp_atr",
            schp_checkpoint,
            provider_work / "schp_atr",
            sapiens_long_side=sapiens_long_side,
            tile_size=tile_size,
            tile_overlap=tile_overlap,
            local_cuda_python=local_cuda_python,
            schp_cache=schp_cache,
        ),
        sapiens_map=sapiens_map,
        schp_map=schp_map,
        output_dir=output_dir,
    )


def run_champion_bodypart_prediction(
    image_path: Path,
    output_dir: Path,
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    models_root: Path = DEFAULT_MODELS_ROOT,
    loader: ChampionLoader | None = None,
) -> CustomBodypartResult | None:
    """Emit the promoted 56-class S03 prior, or no artifact when no champion exists."""
    registry_path = Path(registry_path)
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ParsingError(f"champion registry is unreadable: {exc}") from exc
    matches = [
        entry
        for entry in registry.get("models", [])
        if entry.get("role") == "champion_bodypart" and entry.get("managed") is not True
    ]
    if not matches:
        return None
    if len(matches) != 1:
        raise ParsingError("expected exactly one champion_bodypart registry entry")
    entry = matches[0]
    try:
        checkpoint = resolve_registered_role(
            "champion_bodypart", registry_path=registry_path, models_root=Path(models_root)
        )
    except ModelRegistryError as exc:
        raise ParsingError(f"champion bodypart resolution failed: {exc}") from exc
    if loader is None:
        from ..serve.providers import load_production_mmseg_slot

        loader = load_production_mmseg_slot
    slot = loader(
        "champion_bodypart",
        checkpoint,
        registry_path=registry_path,
        models_root=Path(models_root),
    )
    try:
        expected = _bodypart_class_names()
        if tuple(slot.class_names) != expected:
            raise ParsingError("champion_bodypart class_names differ from the 56-class ontology")
        requested = tuple(name for name in expected if name != "background")
        with Image.open(image_path) as opened:
            image = np.asarray(opened.convert("RGB"))
        masks = slot(image, requested)
        map_path = _write_custom_bodypart_map(masks, image.shape[:2], output_dir)
        provenance = {
            "schema_version": "1.0.0",
            "role": "champion_bodypart",
            "model_key": str(entry.get("key", "")),
            "checkpoint_sha256": str(entry.get("sha256", "")),
            "inference_config_sha256": str(entry.get("inference_config_sha256", "")),
            "class_names": list(expected),
        }
        if (
            not provenance["model_key"]
            or len(provenance["checkpoint_sha256"]) != 64
            or len(provenance["inference_config_sha256"]) != 64
        ):
            raise ParsingError("champion_bodypart registry provenance is incomplete")
        provenance_path = write_json_atomic(
            Path(output_dir) / "custom_bodypart_provenance.json", provenance
        )
        return CustomBodypartResult(map_path, provenance_path, provenance["model_key"])
    finally:
        slot.close()


def custom_bodypart_refresh_required(
    output_dir: Path,
    *,
    registry_path: Path = DEFAULT_REGISTRY,
) -> bool:
    """Return whether cached S03 output differs from the current champion role pointer."""
    try:
        registry = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ParsingError(f"champion registry is unreadable: {exc}") from exc
    matches = [
        entry
        for entry in registry.get("models", [])
        if entry.get("role") == "champion_bodypart" and entry.get("managed") is not True
    ]
    if len(matches) > 1:
        raise ParsingError("expected at most one champion_bodypart registry entry")
    root = Path(output_dir)
    map_path = root / "custom_bodypart.png"
    provenance_path = root / "custom_bodypart_provenance.json"
    if not matches:
        return map_path.exists() or provenance_path.exists()
    if not map_path.is_file() or not provenance_path.is_file():
        return True
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    entry = matches[0]
    return any(
        provenance.get(key) != entry.get(entry_key)
        for key, entry_key in (
            ("model_key", "key"),
            ("checkpoint_sha256", "sha256"),
            ("inference_config_sha256", "inference_config_sha256"),
            ("class_names", "class_names"),
        )
    )


def _bodypart_class_names() -> tuple[str, ...]:
    labels = sorted(get_ontology().labels_for_map("part"), key=lambda label: int(label.id))
    names = tuple(label.name for label in labels)
    if len(names) != 56 or names[0] != "background":
        raise ParsingError("active bodypart ontology is not the governed 56-class v1 contract")
    return names


def _write_custom_bodypart_map(
    masks: Mapping[str, np.ndarray], shape: tuple[int, int], output_dir: Path
) -> Path:
    expected = _bodypart_class_names()
    requested = set(expected) - {"background"}
    if set(masks) != requested:
        raise ParsingError("champion_bodypart output does not cover the exact ontology vocabulary")
    authority = get_ontology()
    indexed = np.zeros(shape, dtype=np.uint16)
    claimed = np.zeros(shape, dtype=bool)
    for name in expected[1:]:
        mask = np.asarray(masks[name])
        if mask.dtype != np.bool_ or mask.shape != shape:
            raise ParsingError(f"champion_bodypart mask {name} has invalid dtype or geometry")
        if np.any(claimed & mask):
            raise ParsingError("champion_bodypart masks overlap")
        indexed[mask] = int(authority.label(name).id)
        claimed |= mask
    path = Path(output_dir) / "custom_bodypart.png"
    write_label_map(path, indexed, bits=16)
    return path


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
    sapiens_foreground_px = None
    if sapiens_output is not None:
        sapiens_output = _validated(sapiens_output, image.shape[:2], len(sapiens_map), "Sapiens")
        sapiens_foreground_px = int(np.count_nonzero(sapiens_output.labels))
        if sapiens_foreground_px == 0:
            degraded = True
        sapiens_path, sapiens_confidence = _write_output(output_dir, "sapiens_28", sapiens_output)
        disagreement = _disagreement_pct(
            sapiens_output.labels, schp_output.labels, sapiens_map, schp_map
        )

    metrics = {
        "parsing_degraded": degraded,
        "sapiens_scale": sapiens_scale,
        "sapiens_foreground_px": sapiens_foreground_px,
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
    for stem, bits in (("sapiens_28", 8), ("schp_atr", 8), ("custom_bodypart", 16)):
        labels_path = output_dir / f"{stem}.png"
        if not labels_path.is_file():
            continue
        labels = np.asarray(Image.open(labels_path))
        if labels.shape != protected.shape:
            raise ParsingError(f"{stem} dimensions differ from co-subject protection")
        labels = labels.astype(np.uint16 if bits == 16 else np.uint8, copy=True)
        labels[protected] = 0
        write_label_map(labels_path, labels, bits=bits)
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
    _validate_distribution(labels, probabilities, class_count, name)
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
    sapiens_labels = np.asarray(sapiens_labels)
    schp_labels = np.asarray(schp_labels)
    sapiens_unknown = set(np.unique(sapiens_labels).tolist()) - set(sapiens_map)
    schp_unknown = set(np.unique(schp_labels).tolist()) - set(schp_map)
    if sapiens_unknown or schp_unknown:
        raise ParsingError(
            f"unmapped parser classes: sapiens={sorted(sapiens_unknown)}, schp={sorted(schp_unknown)}"
        )
    compatible = np.zeros((max(sapiens_map) + 1, max(schp_map) + 1), dtype=bool)
    for sapiens_id, sapiens_entry in sapiens_map.items():
        sapiens_set = set(sapiens_entry.get("part_priors", ())) | set(
            sapiens_entry.get("material_priors", ())
        )
        for schp_id, schp_entry in schp_map.items():
            schp_set = set(schp_entry.get("part_priors", ())) | set(
                schp_entry.get("material_priors", ())
            )
            compatible[sapiens_id, schp_id] = bool(sapiens_set & schp_set)
    return 100.0 * float((~compatible[sapiens_labels, schp_labels]).mean())


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
    if not np.all(normalizer > 0):
        raise ParsingError("restored parser probabilities contain zero-mass pixels")
    return restored / normalizer


def _validate_distribution(
    labels: np.ndarray, probabilities: np.ndarray, class_count: int, name: str
) -> None:
    if labels.dtype.kind not in "iu":
        raise ParsingError(f"{name} labels must be integer")
    if not np.isfinite(probabilities).all() or probabilities.min() < 0 or probabilities.max() > 1:
        raise ParsingError(f"{name} probabilities must be finite in 0..1")
    if probabilities.shape[0] != class_count:
        raise ParsingError(f"{name} probability class count mismatch")
    if not np.allclose(probabilities.sum(axis=0), 1.0, rtol=0, atol=1e-4):
        raise ParsingError(f"{name} probabilities must sum to one per pixel")
    expected_labels = probabilities.argmax(axis=0)
    if not np.array_equal(labels, expected_labels):
        raise ParsingError(f"{name} labels must equal probability argmax")


def _wsl_path(path: Path) -> str:
    resolved = Path(path).resolve()
    drive = resolved.drive.rstrip(":").lower()
    if not drive:
        raise ParsingError(f"expected Windows drive path: {resolved}")
    return f"/mnt/{drive}{resolved.as_posix().split(':', 1)[1]}"
