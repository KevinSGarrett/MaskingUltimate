"""CVAT/Nuclio pth-sam2 client for WSL-independent package part repair.

Invokes the live production interactor at localhost:8080 (CVAT v2.24) -> Nuclio
``pth-sam2``. Does not require the Ubuntu-22.04 WSL distro or host CUDA torch.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import requests
from PIL import Image


class NuclioSam2Error(RuntimeError):
    """CVAT/Nuclio SAM2 invoke failed or returned an invalid mask."""


SAM2_NUCLIO_PART_REFINE_HYPOTHESIS = "sam2_nuclio_part_refine"
SAM2_NUCLIO_PROMOTABLE_DEFECT_CLASSES = frozenset({"fragmentation", "underfill"})
MINIMUM_SAM2_CC_EXCESS_DROP = 1
HIGHEST_VISUAL_TIER_WITH_RESIDUALS = "VISUAL_QA_REVIEWED_WITH_DEFECTS"
BLOCKED_VISUAL_PASS_CLAIM = "VISUAL_QA_PASS_BOUNDED"


@dataclass(frozen=True)
class NuclioSam2PromotionDecision:
    """Whether a nuclio part refine may mutate a live package part mask."""

    may_promote: bool
    outcome: str
    reason: str
    visual_tier: str
    claims_forbidden: tuple[str, ...]


def decide_sam2_nuclio_promotion(
    *,
    defect_class: str,
    executor_accepted: bool,
    baseline_excess: int,
    hard_qc_passed: bool | None = None,
) -> NuclioSam2PromotionDecision:
    """Gate live package promotion for WSL-independent nuclio SAM2 part refine.

    Never claims VISUAL_QA_PASS_BOUNDED. Morphology-only abstention for structural
    classes remains in visual_defect_policy; this gate is specific to the
    ``sam2_nuclio_part_refine`` hypothesis.
    """
    forbidden = (
        BLOCKED_VISUAL_PASS_CLAIM,
        "gold",
        "human_approved_gold",
        "PRODUCTION_EVIDENCE_PASS",
    )
    visual = HIGHEST_VISUAL_TIER_WITH_RESIDUALS
    if not executor_accepted:
        return NuclioSam2PromotionDecision(
            False,
            "ABSTAIN_BOUNDED",
            "executor_did_not_accept_reversible_repair",
            visual,
            forbidden,
        )
    if defect_class not in SAM2_NUCLIO_PROMOTABLE_DEFECT_CLASSES:
        return NuclioSam2PromotionDecision(
            False,
            "ABSTAIN_BOUNDED",
            (
                f"sam2_nuclio_part_refine does not promote defect_class={defect_class}; "
                f"allowed={sorted(SAM2_NUCLIO_PROMOTABLE_DEFECT_CLASSES)}"
            ),
            visual,
            forbidden,
        )
    if baseline_excess < MINIMUM_SAM2_CC_EXCESS_DROP:
        return NuclioSam2PromotionDecision(
            False,
            "ABSTAIN_BOUNDED",
            (
                f"sam2_nuclio baseline_excess={baseline_excess} "
                f"< minimum {MINIMUM_SAM2_CC_EXCESS_DROP}; parent preserved"
            ),
            visual,
            forbidden,
        )
    if hard_qc_passed is False:
        return NuclioSam2PromotionDecision(
            False,
            "ABSTAIN_BOUNDED",
            "sam2_nuclio promote failed hard QC; rolled back",
            visual,
            forbidden,
        )
    return NuclioSam2PromotionDecision(
        True,
        "ACCEPTED_REVERSIBLE_REPAIR_BOUNDED",
        (
            "nuclio/CVAT pth-sam2 part refine accepted; component excess reduced; "
            f"hard QC re-pass; {BLOCKED_VISUAL_PASS_CLAIM} still forbidden "
            "(instance may retain other structural residuals)"
        ),
        visual,
        forbidden,
    )


@dataclass(frozen=True)
class NuclioSam2InvokeResult:
    """One interactive SAM2 mask from the production Nuclio interactor."""

    mask: np.ndarray
    task_id: int
    latency_seconds: float
    function_version: int | None
    foreground_pixels: int


def load_cvat_token(env_path: Path) -> str:
    """Read CVAT_TOKEN from the gitignored root .env (never log the value)."""
    values: dict[str, str] = {}
    for line in Path(env_path).read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    token = values.get("CVAT_TOKEN")
    if not token:
        raise NuclioSam2Error("CVAT_TOKEN is missing from the ignored root .env")
    return token


class NuclioSam2Client:
    """Thin authenticated client for ``POST /api/lambda/functions/pth-sam2``."""

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:8080",
        token: str,
        timeout_seconds: float = 180,
    ) -> None:
        if not token.strip():
            raise NuclioSam2Error("CVAT token must be non-empty")
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers["Authorization"] = "Token " + token

    def ensure_interactor(self) -> dict:
        functions = self._request_json("GET", "/api/lambda/functions")
        function = next((item for item in functions if item.get("id") == "pth-sam2"), None)
        if function is None or function.get("kind") != "interactor":
            raise NuclioSam2Error("CVAT does not list pth-sam2 as an interactor")
        return function

    def get_or_create_image_task(self, *, task_name: str, image_path: Path) -> int:
        """Create or reuse a 1-frame CVAT task seeded with the package source PNG."""
        image_path = Path(image_path)
        if not image_path.is_file():
            raise NuclioSam2Error(f"source image missing: {image_path}")
        tasks = self._request_json("GET", "/api/tasks", params={"search": task_name})
        exact = [task for task in tasks.get("results", []) if task.get("name") == task_name]
        for task in exact:
            if int(task.get("size") or 0) == 1:
                return int(task["id"])
            self.session.delete(
                self.base_url + f"/api/tasks/{task['id']}", timeout=30
            ).raise_for_status()

        task = self._request_json(
            "POST",
            "/api/tasks",
            json={
                "name": task_name,
                "labels": [{"name": "object", "color": "#33aa55", "type": "mask"}],
            },
        )
        task_id = int(task["id"])
        response = self.session.post(
            self.base_url + f"/api/tasks/{task_id}/data",
            data={"image_quality": "100", "sorting_method": "lexicographical"},
            files={"client_files[0]": (image_path.name, image_path.read_bytes(), "image/png")},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        request_id = response.json()["rq_id"]
        deadline = time.monotonic() + max(60.0, self.timeout_seconds)
        while time.monotonic() < deadline:
            request = self._request_json("GET", f"/api/requests/{request_id}")
            status = request.get("status")
            if status == "finished":
                return task_id
            if status == "failed":
                raise NuclioSam2Error(
                    f"CVAT task data processing failed: {request.get('message')}"
                )
            time.sleep(1)
        raise NuclioSam2Error("CVAT did not finish package-image task upload in time")

    def invoke(
        self,
        *,
        task_id: int,
        pos_points: Sequence[Sequence[int | float]],
        neg_points: Sequence[Sequence[int | float]] = (),
        frame: int = 0,
        expected_shape: tuple[int, int] | None = None,
    ) -> NuclioSam2InvokeResult:
        if not pos_points:
            raise NuclioSam2Error("at least one positive point is required")
        function = self.ensure_interactor()
        started = time.perf_counter()
        result = self._request_json(
            "POST",
            "/api/lambda/functions/pth-sam2",
            json={
                "task": int(task_id),
                "frame": int(frame),
                "pos_points": [[float(x), float(y)] for x, y in pos_points],
                "neg_points": [[float(x), float(y)] for x, y in neg_points],
            },
        )
        latency = time.perf_counter() - started
        if "mask" not in result:
            raise NuclioSam2Error(f"pth-sam2 response missing mask: keys={sorted(result)}")
        mask = np.asarray(result["mask"], dtype=np.uint8)
        if mask.ndim != 2:
            raise NuclioSam2Error(f"pth-sam2 mask must be 2-D; got {mask.shape}")
        if expected_shape is not None and mask.shape != expected_shape:
            raise NuclioSam2Error(
                f"pth-sam2 mask shape {mask.shape} != expected {expected_shape}"
            )
        unique = set(int(value) for value in np.unique(mask))
        if not unique.issubset({0, 255}):
            # Some deployments return 0/1; coerce only that safe case.
            if unique.issubset({0, 1}):
                mask = (mask > 0).astype(np.uint8) * 255
            else:
                raise NuclioSam2Error(f"pth-sam2 mask has non-binary values: {sorted(unique)[:8]}")
        return NuclioSam2InvokeResult(
            mask=mask,
            task_id=int(task_id),
            latency_seconds=round(latency, 3),
            function_version=function.get("version"),
            foreground_pixels=int(np.count_nonzero(mask)),
        )

    def refine_part_mask(
        self,
        *,
        task_id: int,
        current_mask: np.ndarray,
        pos_points: Sequence[Sequence[int | float]],
        neg_points: Sequence[Sequence[int | float]],
        roi_xyxy: tuple[int, int, int, int],
    ) -> NuclioSam2InvokeResult:
        """Invoke SAM2 and keep only the ROI-anchored component(s) hitting positives."""
        height, width = np.asarray(current_mask).shape[:2]
        result = self.invoke(
            task_id=task_id,
            pos_points=pos_points,
            neg_points=neg_points,
            expected_shape=(height, width),
        )
        left, top, right, bottom = roi_xyxy
        roi = np.zeros((height, width), dtype=bool)
        roi[top:bottom, left:right] = True
        raw = (result.mask > 0) & roi
        if not raw.any():
            raise NuclioSam2Error("pth-sam2 returned empty mask inside repair ROI")
        # Keep connected components that contain at least one positive click.
        from scipy import ndimage

        components, _ = ndimage.label(raw)
        keep_ids = {
            int(components[int(y), int(x)])
            for x, y in pos_points
            if 0 <= int(x) < width and 0 <= int(y) < height and int(components[int(y), int(x)]) > 0
        }
        if not keep_ids:
            raise NuclioSam2Error("pth-sam2 mask does not cover any positive click")
        anchored = np.isin(components, tuple(keep_ids))
        refined = (anchored.astype(np.uint8) * 255)
        return NuclioSam2InvokeResult(
            mask=refined,
            task_id=result.task_id,
            latency_seconds=result.latency_seconds,
            function_version=result.function_version,
            foreground_pixels=int(np.count_nonzero(refined)),
        )

    def _request_json(self, method: str, path: str, **kwargs) -> dict | list:
        response = self.session.request(
            method, self.base_url + path, timeout=self.timeout_seconds, **kwargs
        )
        response.raise_for_status()
        return response.json()


def derive_clicks_from_mask(
    mask: np.ndarray,
    *,
    protected: np.ndarray | None = None,
    max_positives: int = 3,
    max_negatives: int = 4,
    pad_px: int = 24,
) -> tuple[list[tuple[int, int]], list[tuple[int, int]], tuple[int, int, int, int]]:
    """Build pos/neg clicks + ROI from the largest connected component of a part mask."""
    from scipy import ndimage

    target = np.asarray(mask).astype(bool)
    if not target.any():
        raise NuclioSam2Error("cannot derive clicks from an empty part mask")
    height, width = target.shape
    labels, count = ndimage.label(target)
    sizes = {index: int(np.count_nonzero(labels == index)) for index in range(1, count + 1)}
    largest = max(sizes, key=sizes.get)
    primary = labels == largest
    ys, xs = np.where(primary)
    cy, cx = int(ys.mean()), int(xs.mean())
    positives: list[tuple[int, int]] = [(cx, cy)]
    # Prefer interior samples (distance transform peaks).
    distance = ndimage.distance_transform_edt(primary)
    flat = distance.reshape(-1)
    order = np.argsort(flat)[::-1]
    for index in order:
        if len(positives) >= max_positives:
            break
        y, x = divmod(int(index), width)
        point = (x, y)
        if point in positives or not primary[y, x]:
            continue
        positives.append(point)

    ys_all, xs_all = np.where(target)
    left = max(0, int(xs_all.min()) - pad_px)
    top = max(0, int(ys_all.min()) - pad_px)
    right = min(width, int(xs_all.max()) + 1 + pad_px)
    bottom = min(height, int(ys_all.max()) + 1 + pad_px)
    roi = (left, top, right, bottom)

    negatives: list[tuple[int, int]] = []
    if protected is not None:
        prot = np.asarray(protected).astype(bool)
        # Negatives on protected neighbors inside the ROI (hard boundaries).
        py, px = np.where(prot & ~target)
        step = max(1, len(px) // max_negatives) if len(px) else 1
        for x, y in zip(px[::step], py[::step]):
            if left <= x < right and top <= y < bottom:
                negatives.append((int(x), int(y)))
            if len(negatives) >= max_negatives:
                break
    # Corner-of-ROI background fallbacks.
    for point in ((left, top), (right - 1, top), (left, bottom - 1), (right - 1, bottom - 1)):
        x, y = point
        if 0 <= x < width and 0 <= y < height and not target[y, x]:
            if point not in negatives:
                negatives.append(point)
        if len(negatives) >= max_negatives:
            break
    return positives, negatives, roi


def load_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"), dtype=np.uint8)


__all__ = [
    "BLOCKED_VISUAL_PASS_CLAIM",
    "HIGHEST_VISUAL_TIER_WITH_RESIDUALS",
    "MINIMUM_SAM2_CC_EXCESS_DROP",
    "NuclioSam2Client",
    "NuclioSam2Error",
    "NuclioSam2InvokeResult",
    "NuclioSam2PromotionDecision",
    "SAM2_NUCLIO_PART_REFINE_HYPOTHESIS",
    "SAM2_NUCLIO_PROMOTABLE_DEFECT_CLASSES",
    "decide_sam2_nuclio_promotion",
    "derive_clicks_from_mask",
    "load_cvat_token",
    "load_rgb",
]
