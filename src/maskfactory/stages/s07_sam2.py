"""S07 SAM2 embedding lifecycle, candidate refinement, and strict post-processing."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from PIL import Image
from scipy import ndimage

from ..io.png_strict import write_binary_mask
from .s05_geometry import PromptPlan


class Sam2Error(ValueError):
    """SAM2 provider output violates the S07 contract."""


@dataclass(frozen=True)
class SamCandidate:
    logits: np.ndarray
    predicted_iou: float


class Sam2Provider(Protocol):
    def embed(self, image: np.ndarray, *, model: str, precision: str) -> Any: ...

    def predict(
        self, embedding: Any, plan: PromptPlan, *, multimask_output: bool
    ) -> list[SamCandidate]: ...


@dataclass
class WslSam2Embedding:
    process: Any
    image_shape: tuple[int, int]
    model: str
    work_dir: Path
    image_path: Path
    launcher: str
    prediction_count: int = 0


MODEL_SHA256 = {
    "sam2.1_hiera_large": "2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318",
    "sam2.1_hiera_base_plus": "a2345aede8715ab1d5d31b4a509fb160c5a4af1970f199d9054ccfb746c004c5",
}
MODEL_CONFIGS = {
    "sam2.1_hiera_large": "configs/sam2.1/sam2.1_hiera_l.yaml",
    "sam2.1_hiera_base_plus": "configs/sam2.1/sam2.1_hiera_b+.yaml",
}


class WslSam2Provider:
    """Persistent one-image WSL SAM2 server: one embedding, many part prompts."""

    def __init__(
        self,
        checkpoints: dict[str, Path],
        configs: dict[str, str],
        work_dir: Path,
        *,
        wsl_distribution: str = "Ubuntu-22.04",
        python_path: str = "/home/kevin/miniforge3/envs/maskfactory/bin/python",
        startup_timeout_sec: float = 300,
        prediction_timeout_sec: float = 120,
        local_cuda_python: Path | None = None,
        source_path: Path | None = None,
        dependency_site: Path | None = None,
    ) -> None:
        self.checkpoints = {key: Path(value) for key, value in checkpoints.items()}
        self.configs = dict(configs)
        drift = {
            key: (self.configs.get(key), expected)
            for key, expected in MODEL_CONFIGS.items()
            if self.configs.get(key) != expected
        }
        if drift:
            raise Sam2Error(f"SAM2 config mapping violates governed contract: {drift}")
        self.work_dir = Path(work_dir)
        self.wsl_distribution = wsl_distribution
        self.python_path = python_path
        if startup_timeout_sec <= 0 or prediction_timeout_sec <= 0:
            raise Sam2Error("SAM2 timeouts must be positive")
        self.startup_timeout_sec = startup_timeout_sec
        self.prediction_timeout_sec = prediction_timeout_sec
        self.local_cuda_python = Path(local_cuda_python) if local_cuda_python is not None else None
        self.source_path = Path(source_path) if source_path is not None else None
        self.dependency_site = Path(dependency_site) if dependency_site is not None else None

    def embed(self, image: np.ndarray, *, model: str, precision: str) -> WslSam2Embedding:
        if (
            precision != "fp16"
            or model not in MODEL_SHA256
            or model not in self.checkpoints
            or model not in self.configs
        ):
            raise Sam2Error("SAM2 model/config/precision unavailable")
        source = np.asarray(image)
        if (
            source.ndim != 3
            or source.shape[2] not in {3, 4}
            or source.dtype != np.uint8
            or source.shape[0] < 1
            or source.shape[1] < 1
        ):
            raise Sam2Error("SAM2 embedding image must be HxWx3/4")
        checkpoint = self.checkpoints[model]
        if not checkpoint.is_file():
            raise Sam2Error(f"SAM2 checkpoint missing: {checkpoint}")
        self.work_dir.mkdir(parents=True, exist_ok=True)
        image_path = self.work_dir / f"embedding_{uuid.uuid4().hex}.png"
        Image.fromarray(source[:, :, :3].astype(np.uint8), mode="RGB").save(image_path)
        root = Path(__file__).resolve().parents[3]
        arguments = [
            "--checkpoint",
            str(checkpoint.resolve()),
            "--config",
            self.configs[model],
            "--image",
            str(image_path.resolve()),
            "--model-key",
            model,
        ]
        if self.local_cuda_python is not None:
            if not self.local_cuda_python.is_file():
                image_path.unlink(missing_ok=True)
                raise Sam2Error("configured local CUDA Python is missing")
            if self.source_path is None or not (self.source_path / "sam2/__init__.py").is_file():
                image_path.unlink(missing_ok=True)
                raise Sam2Error("configured SAM2 source is missing")
            if self.dependency_site is None or not (self.dependency_site / "hydra").is_dir():
                image_path.unlink(missing_ok=True)
                raise Sam2Error("configured SAM2 dependency site is missing")
            command = [
                str(self.local_cuda_python),
                str(root / "tools" / "run_sam2_server_wsl.py"),
                *arguments,
            ]
            launcher = "local_cuda"
            environment = os.environ.copy()
            existing = environment.get("PYTHONPATH")
            environment["PYTHONPATH"] = os.pathsep.join(
                [
                    str(self.source_path.resolve()),
                    str(self.dependency_site.resolve()),
                    *([existing] if existing else []),
                ]
            )
        else:
            wsl_arguments = [
                _wsl_path(Path(value)) if index in {1, 5} else value
                for index, value in enumerate(arguments)
            ]
            command = [
                "wsl",
                "-d",
                self.wsl_distribution,
                "--",
                self.python_path,
                _wsl_path(root / "tools" / "run_sam2_server_wsl.py"),
                *wsl_arguments,
            ]
            launcher = "wsl_cuda"
            environment = None
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                **({"env": environment} if environment is not None else {}),
            )
        except OSError as exc:
            image_path.unlink(missing_ok=True)
            raise Sam2Error(f"SAM2 {launcher} launch failed: {exc}") from exc
        ready_line = (
            _readline_with_timeout(process.stdout, self.startup_timeout_sec)
            if process.stdout is not None
            else ""
        )
        if not ready_line:
            _stop_process(process)
            detail = process.stderr.read()[-2000:] if process.stderr is not None else ""
            image_path.unlink(missing_ok=True)
            if "out of memory" in detail.lower():
                raise RuntimeError(f"CUDA out of memory: {detail}")
            raise Sam2Error(f"SAM2 server failed before embedding: {detail}")
        try:
            ready = json.loads(ready_line)
        except json.JSONDecodeError as exc:
            _stop_process(process)
            image_path.unlink(missing_ok=True)
            detail = ready_line.replace("\x00", "").strip()[-1000:]
            raise Sam2Error(f"SAM2 ready response invalid: {detail or exc}") from exc
        expected = {
            "protocol_version": 1,
            "status": "ready",
            "shape": list(source.shape[:2]),
            "model": model,
            "checkpoint_sha256": MODEL_SHA256[model],
            "config": self.configs[model],
            "precision": "fp16",
            "device_type": "cuda",
            "embedding_count": 1,
            "source_revision": "2b90b9f5ceec907a1c18123530e92e794ad901a4",
        }
        mismatches = {
            key: (ready.get(key), value)
            for key, value in expected.items()
            if ready.get(key) != value
        }
        if mismatches or not isinstance(ready.get("device"), str) or not ready["device"].strip():
            _stop_process(process)
            image_path.unlink(missing_ok=True)
            raise Sam2Error(f"SAM2 ready response violates governed contract: {mismatches}")
        if "+cu128" not in str(ready.get("torch", "")):
            _stop_process(process)
            image_path.unlink(missing_ok=True)
            raise Sam2Error("SAM2 ready response requires the governed cu128 PyTorch runtime")
        runtime_document = {
            "launcher": launcher,
            "python": str(self.local_cuda_python or self.python_path),
            **ready,
        }
        (self.work_dir / "runtime.json").write_text(
            json.dumps(runtime_document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return WslSam2Embedding(
            process, source.shape[:2], model, self.work_dir, image_path, launcher
        )

    def predict(
        self, embedding: WslSam2Embedding, plan: PromptPlan, *, multimask_output: bool
    ) -> list[SamCandidate]:
        process = embedding.process
        if process.poll() is not None or process.stdin is None or process.stdout is None:
            raise Sam2Error("SAM2 embedding server is not running")
        if not multimask_output:
            raise Sam2Error("S07 requires multimask_output=True")
        _validate_prompt_plan(plan, embedding.image_shape)
        request_id = uuid.uuid4().hex
        output_path = embedding.work_dir / f"prediction_{request_id}.npz"
        request = {
            "request_id": request_id,
            "box_xyxy": list(plan.box_xyxy),
            "positive_points": [list(point) for point in plan.positive_points],
            "negative_points": [list(point) for point in plan.negative_points],
            "multimask_output": multimask_output,
            "output": (
                str(output_path.resolve())
                if embedding.launcher == "local_cuda"
                else _wsl_path(output_path)
            ),
        }
        try:
            process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
            process.stdin.flush()
            response_line = _readline_with_timeout(process.stdout, self.prediction_timeout_sec)
        except OSError as exc:
            output_path.unlink(missing_ok=True)
            raise Sam2Error(f"SAM2 prediction request failed: {exc}") from exc
        if not response_line:
            _stop_process(process)
            detail = process.stderr.read()[-2000:] if process.stderr is not None else ""
            output_path.unlink(missing_ok=True)
            raise Sam2Error(f"SAM2 prediction server stopped: {detail}")
        try:
            try:
                response = json.loads(response_line)
                with np.load(output_path, allow_pickle=False) as archive:
                    logits = archive["logits"]
                    scores = archive["scores"]
            except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
                raise Sam2Error(f"SAM2 prediction output invalid: {exc}") from exc
        finally:
            output_path.unlink(missing_ok=True)
        expected_index = embedding.prediction_count + 1
        if (
            response.get("protocol_version") != 1
            or response.get("status") != "ok"
            or response.get("request_id") != request_id
            or response.get("embedding_count") != 1
            or response.get("prediction_index") != expected_index
            or response.get("multimask_output") is not True
            or logits.ndim != 3
            or logits.shape[0] != 3
            or logits.shape[1:] != embedding.image_shape
            or scores.shape != (logits.shape[0],)
        ):
            raise Sam2Error("SAM2 prediction response shape/id mismatch")
        if (
            logits.dtype != np.float32
            or scores.dtype != np.float32
            or not np.isfinite(logits).all()
            or not np.isfinite(scores).all()
            or np.any(scores < 0)
            or np.any(scores > 1)
        ):
            raise Sam2Error("SAM2 prediction archive dtype/value contract violated")
        embedding.prediction_count = expected_index
        return [
            SamCandidate(logit.astype(np.float32), float(score))
            for logit, score in zip(logits, scores, strict=True)
        ]

    @staticmethod
    def close(embedding: WslSam2Embedding) -> None:
        _stop_process(embedding.process)
        embedding.image_path.unlink(missing_ok=True)


@dataclass(frozen=True)
class RefinedPart:
    label: str
    mask: np.ndarray
    predicted_iou: float
    selection_score: float
    corrective_iteration: bool
    sam2_low_conf: bool
    review_flags: tuple[str, ...]
    model: str


def build_embedding(
    provider: Sam2Provider,
    image: np.ndarray,
    *,
    primary_model: str = "sam2.1_hiera_large",
    fallback_model: str = "sam2.1_hiera_base_plus",
) -> tuple[Any, str]:
    """Build exactly one reusable embedding, falling back on primary-model OOM."""
    if primary_model == fallback_model:
        raise Sam2Error("SAM2 primary and OOM fallback models must differ")
    try:
        return provider.embed(image, model=primary_model, precision="fp16"), primary_model
    except (MemoryError, RuntimeError) as error:
        if not _is_oom(error):
            raise
        return provider.embed(image, model=fallback_model, precision="fp16"), fallback_model


def refine_part(
    provider: Sam2Provider,
    embedding: Any,
    plan: PromptPlan,
    prior: np.ndarray,
    *,
    model: str,
    skeleton_points_xy: tuple[tuple[int, int], ...] = (),
    disagreement_threshold: float = 0.08,
    low_confidence_threshold: float = 0.5,
) -> RefinedPart:
    """Select 0.6 prior-IoU + 0.4 predicted-IoU, then correct at most once."""
    prior_mask = np.asarray(prior) > 0
    if prior_mask.ndim != 2 or not prior_mask.any():
        raise Sam2Error("prior must be a non-empty 2-D mask")
    candidate, score = _select(provider.predict(embedding, plan, multimask_output=True), prior_mask)
    selected_mask = np.asarray(candidate.logits) >= 0
    disagreement = np.count_nonzero(selected_mask ^ prior_mask) / np.count_nonzero(prior_mask)
    corrected = False
    if disagreement > disagreement_threshold:
        corrective_plan = _corrective_plan(plan, prior_mask, selected_mask, skeleton_points_xy)
        second, second_score = _select(
            provider.predict(embedding, corrective_plan, multimask_output=True), prior_mask
        )
        if second_score >= score:
            candidate, score = second, second_score
            selected_mask = np.asarray(candidate.logits) >= 0
        corrected = True
    low_confidence = candidate.predicted_iou < low_confidence_threshold
    if low_confidence:
        final = prior_mask.copy()
    else:
        final = postprocess_mask(selected_mask)
    return RefinedPart(
        plan.label,
        final,
        candidate.predicted_iou,
        score,
        corrected,
        low_confidence,
        ("sam2_low_conf", "careful_review") if low_confidence else (),
        model,
    )


def postprocess_mask(mask: np.ndarray) -> np.ndarray:
    """Drop tiny components and fill only holes smaller than 0.5% part area; never smooth."""
    binary = np.asarray(mask).astype(bool)
    if binary.ndim != 2:
        raise Sam2Error("SAM2 mask must be 2-D")
    part_area = int(binary.sum())
    if not part_area:
        return binary
    minimum = max(64, math_ceil(0.02 * part_area))
    labels, count = ndimage.label(binary)
    kept = np.zeros_like(binary)
    for index in range(1, count + 1):
        component = labels == index
        if int(component.sum()) >= minimum:
            kept |= component
    filled = ndimage.binary_fill_holes(kept)
    holes = filled & ~kept
    hole_labels, hole_count = ndimage.label(holes)
    maximum_hole = 0.005 * max(1, int(kept.sum()))
    for index in range(1, hole_count + 1):
        hole = hole_labels == index
        if int(hole.sum()) < maximum_hole:
            kept |= hole
    return kept


def cut_joint_ownership(
    segment_masks: dict[str, np.ndarray],
    joint_bands: dict[str, np.ndarray],
    adjacency: dict[str, tuple[str, str]],
) -> dict[str, np.ndarray]:
    """Carve each joint band from its two adjacent segment results; bands own pixels."""
    output = {label: np.asarray(mask).astype(bool).copy() for label, mask in segment_masks.items()}
    for joint, band_value in joint_bands.items():
        if joint not in adjacency:
            raise Sam2Error(f"joint adjacency missing for {joint}")
        proximal, distal = adjacency[joint]
        if proximal not in output or distal not in output:
            raise Sam2Error(f"segment result missing for {joint}")
        band = np.asarray(band_value).astype(bool) & (output[proximal] | output[distal])
        output[proximal] &= ~band
        output[distal] &= ~band
        output[joint] = band
    return output


def run_s07_production(
    image_path: Path,
    prompts_path: Path,
    priors_dir: Path,
    output_dir: Path,
    *,
    provider: Sam2Provider,
    primary_model: str = "sam2.1_hiera_large",
    fallback_model: str = "sam2.1_hiera_base_plus",
    excluded_crop_lane_parts: frozenset[str] = frozenset(
        {"hair", "chest_upper_torso", "left_breast", "right_breast"}
    ),
) -> tuple[dict[str, RefinedPart], str]:
    """Refine every eligible S05 plan with one shared embedding and persist strict masks."""
    image = np.asarray(Image.open(image_path).convert("RGB"))
    try:
        document = json.loads(Path(prompts_path).read_text(encoding="utf-8"))
        plans = tuple(
            PromptPlan(
                label=item["label"],
                box_xyxy=tuple(item["box_xyxy"]),
                positive_points=tuple(tuple(point) for point in item["positive_points"]),
                negative_points=tuple(tuple(point) for point in item["negative_points"]),
                prior_quality=item["prior_quality"],
                multimask_output=bool(item["multimask_output"]),
            )
            for item in document["plans"]
            if item["label"] not in excluded_crop_lane_parts
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise Sam2Error(f"S05 prompts invalid: {exc}") from exc
    labels = [plan.label for plan in plans]
    if len(set(labels)) != len(labels):
        raise Sam2Error("S07 prompt labels must be unique")
    if any(plan.multimask_output is not True for plan in plans):
        raise Sam2Error("S07 requires multimask_output=True for every prompt plan")
    embedding = None
    results: dict[str, RefinedPart] = {}
    try:
        embedding, model = build_embedding(
            provider, image, primary_model=primary_model, fallback_model=fallback_model
        )
        for plan in plans:
            prior_path = Path(priors_dir) / f"prior_{plan.label}.png"
            prior = np.asarray(Image.open(prior_path).convert("L"))
            if prior.shape != image.shape[:2]:
                raise Sam2Error(f"S07 prior dimensions differ for {plan.label}")
            results[plan.label] = refine_part(
                provider,
                embedding,
                plan,
                prior,
                model=model,
                skeleton_points_xy=plan.positive_points,
            )
    finally:
        if embedding is not None and hasattr(provider, "close"):
            provider.close(embedding)  # type: ignore[attr-defined]
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for label, result in results.items():
        write_binary_mask(
            output_dir / f"sam2_{label}.png",
            result.mask,
            source_size=(image.shape[1], image.shape[0]),
        )
    metrics = {
        "schema_version": "1.0.0",
        "embedding_count": 1,
        "prediction_count": sum(
            1 + int(result.corrective_iteration) for result in results.values()
        ),
        "model": model,
        "parts": {
            label: {
                key: value for key, value in asdict(result).items() if key not in {"label", "mask"}
            }
            for label, result in sorted(results.items())
        },
    }
    (output_dir / "sam2_metrics.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return results, model


def _select(candidates: list[SamCandidate], prior: np.ndarray) -> tuple[SamCandidate, float]:
    if not candidates:
        raise Sam2Error("SAM2 returned no multimask candidates")
    ranked = []
    for index, candidate in enumerate(candidates):
        logits = np.asarray(candidate.logits)
        if logits.shape != prior.shape or not np.isfinite(logits).all():
            raise Sam2Error("SAM2 logits shape/values invalid")
        if not 0 <= candidate.predicted_iou <= 1:
            raise Sam2Error("SAM2 predicted_iou must be in 0..1")
        mask = logits >= 0
        union = np.count_nonzero(mask | prior)
        overlap = np.count_nonzero(mask & prior) / union if union else 1.0
        ranked.append((0.6 * overlap + 0.4 * candidate.predicted_iou, -index, candidate))
    score, _, selected = max(ranked, key=lambda item: (item[0], item[1]))
    return selected, float(score)


def _corrective_plan(
    plan: PromptPlan,
    prior: np.ndarray,
    selected: np.ndarray,
    skeleton_points: tuple[tuple[int, int], ...],
) -> PromptPlan:
    prior_only = prior & ~selected
    mask_only = selected & ~prior
    positives = list(plan.positive_points)
    valid_skeleton = [point for point in skeleton_points if _at(prior_only, point)]
    if valid_skeleton:
        positives.append(valid_skeleton[0])
    elif prior_only.any():
        y, x = np.argwhere(prior_only)[0]
        positives.append((int(x), int(y)))
    negatives = list(plan.negative_points)
    outside_box = mask_only.copy()
    left, top, right, bottom = plan.box_xyxy
    outside_box[top:bottom, left:right] = False
    if outside_box.any():
        y, x = np.argwhere(outside_box)[0]
        negatives.append((int(x), int(y)))
    return replace(
        plan,
        positive_points=tuple(dict.fromkeys(positives)),
        negative_points=tuple(dict.fromkeys(negatives)),
    )


def _at(mask: np.ndarray, point: tuple[int, int]) -> bool:
    x, y = point
    return 0 <= y < mask.shape[0] and 0 <= x < mask.shape[1] and bool(mask[y, x])


def _is_oom(error: BaseException) -> bool:
    return isinstance(error, MemoryError) or "out of memory" in str(error).lower()


def math_ceil(value: float) -> int:
    return int(np.ceil(value))


def _wsl_path(path: Path) -> str:
    resolved = Path(path).resolve()
    drive = resolved.drive.rstrip(":").lower()
    if not drive:
        raise Sam2Error(f"expected Windows drive path: {resolved}")
    return f"/mnt/{drive}{resolved.as_posix().split(':', 1)[1]}"


def _readline_with_timeout(stream: Any, timeout_sec: float) -> str:
    result: queue.Queue[str] = queue.Queue(maxsize=1)

    def read() -> None:
        try:
            result.put(stream.readline(), block=False)
        except (OSError, ValueError):
            result.put("", block=False)

    threading.Thread(target=read, daemon=True).start()
    try:
        return result.get(timeout=timeout_sec)
    except queue.Empty:
        return ""


def _stop_process(process: Any) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=30)


def _validate_prompt_plan(plan: PromptPlan, shape: tuple[int, int]) -> None:
    height, width = shape
    left, top, right, bottom = plan.box_xyxy
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise Sam2Error(f"SAM2 prompt box for {plan.label} must be inside image geometry")
    for name, points in (
        ("positive", plan.positive_points),
        ("negative", plan.negative_points),
    ):
        if any(not (0 <= x < width and 0 <= y < height) for x, y in points):
            raise Sam2Error(f"SAM2 {name} prompt point for {plan.label} is outside image")
