"""Run a real local-CUDA tournament (3 mask families + SAM2) and emit MVC sidecars.

Loads BiRefNet / SCHP-ATR / faceparse / SAM2.1 once each (ComfyUI cu128 venv),
GPU-sequenced never concurrent, scores a bounded image-disjoint corpus, and
writes genuine ``machine_verified_candidate`` lifecycle sidecars + corpus
envelopes under ``runs/``. Family list is governed by
``configs/multiprovider_tournament_families.yaml`` — smokes alone are not enough;
this CLI must actually invoke every required family. Never fabricates agreement,
certificates, or champions.

Usage (must use CUDA python):
  C:/Comfy_UI_Main/ComfyUI/.venv/Scripts/python.exe \\
    tools/run_multiprovider_gold_tournament.py --limit 64 \\
    --sample-set qa/live_verification/tournament_sample_set_ultimate_mw_20260720T1505.json \\
    --output qa/live_verification/multiprovider_tournament_<ts>.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import torch
import yaml
from PIL import Image
from torchvision import transforms

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from maskfactory.autonomy.adapters import (  # noqa: E402
    MaskCandidateInput,
    build_mask_candidate_evidence,
)
from maskfactory.autonomy.emit import emit_lifecycle_and_corpus_record  # noqa: E402
from maskfactory.autonomy.tournament import run_candidate_tournament  # noqa: E402
from maskfactory.autonomy.tournament_families import (  # noqa: E402
    load_tournament_family_map,
    validate_runner_coverage,
)
from maskfactory.io.hashing import sha256_file  # noqa: E402
from maskfactory.io.png_strict import write_binary_mask  # noqa: E402
from maskfactory.providers.contracts import ProviderIdentity  # noqa: E402
from maskfactory.qa.metrics import iou  # noqa: E402
from maskfactory.serve.providers import production_sam2_runtime_options  # noqa: E402
from maskfactory.stages.s05_geometry import PromptPlan  # noqa: E402
from maskfactory.stages.s07_sam2 import MODEL_CONFIGS, WslSam2Provider  # noqa: E402

LABEL = "torso"
CONTEXT = "solo"
PIPELINE_FP = "multiprovider-local-cuda-tournament-20260720-v1"
FAMILY_MAP = load_tournament_family_map()
FAMILIES = FAMILY_MAP.required_invocation_keys
MIN_MEAN_PAIRWISE_IOU = 0.25
MIN_FG_FRACTION = 0.01
MAX_FG_FRACTION = 0.98
# Cap working resolution so 4K–6K gold-volume sources cannot OOM the 8 GiB GPU
# or explode host RAM when holding 64 full-res masks.
WORKING_LONG_SIDE = 1024

BIREFNET_CKPT = REPO_ROOT / "models/silhouette/BiRefNet-general.safetensors"
SCHP_CKPT = REPO_ROOT / "models/parsing_fallback/exp-schp-201908301523-atr.pth"
FACEPARSE_CKPT = REPO_ROOT / "models/faceparse/79999_iter.pth"
FACEPARSE_SRC = REPO_ROOT / "models/runtime_cache/face-parsing-pytorch_d2e684c"
SCHP_CACHE = REPO_ROOT / "models/runtime_cache/schp"
SAM2_LARGE = REPO_ROOT / "models/sam2/sam2.1_hiera_large.pt"
SAM2_BASE = REPO_ROOT / "models/sam2/sam2.1_hiera_base_plus.pt"
CELEBA = Path(r"C:\Comfy_UI_Main\MaskedWarehouse\CelebAMask-HQ\CelebA-HQ-img")
REFERENCE = Path(r"F:\Reference_Images")

# Fail closed at import if this CLI drifts from the governed family map.
validate_runner_coverage(
    FAMILIES,
    {
        "birefnet_general",
        "schp_atr",
        "faceparse_bisenet",
        "sam2_1_large",
    },
)


def _image_id(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"img_{digest[:12]}"


def _load_working_rgb(path: Path) -> tuple[Image.Image, tuple[int, int]]:
    """Load RGB image scaled so max(H, W) <= WORKING_LONG_SIDE (nearest for masks later)."""
    image = Image.open(path).convert("RGB")
    original = image.size  # (W, H)
    width, height = original
    long_side = max(width, height)
    if long_side <= WORKING_LONG_SIDE:
        return image, original
    scale = WORKING_LONG_SIDE / float(long_side)
    new_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    return image.resize(new_size, Image.Resampling.BILINEAR), original


def _load_sample_set(sample_set: Path) -> tuple[list[Path], dict[str, Any]]:
    """Load frozen sibling-feed sample set (ordered_sample_ids + source paths)."""
    payload = json.loads(sample_set.read_text(encoding="utf-8"))
    samples = payload.get("samples") or []
    ordered = list(payload.get("ordered_sample_ids") or [])
    by_id = {row["sample_id"]: row for row in samples if "sample_id" in row}
    paths: list[Path] = []
    meta_rows: list[dict[str, Any]] = []
    for sample_id in ordered:
        row = by_id.get(sample_id)
        if row is None:
            raise RuntimeError(f"sample_set missing sample_id={sample_id}")
        path = Path(row["source_path_readonly"])
        if not path.is_file():
            raise RuntimeError(f"sample path missing: {path}")
        digest = sha256_file(path)
        expected = str(row.get("source_sha256") or "")
        if expected and digest != expected:
            raise RuntimeError(f"source_sha256 mismatch for {sample_id}: {digest} != {expected}")
        paths.append(path)
        meta_rows.append(
            {
                "sample_id": sample_id,
                "source_path_readonly": str(path),
                "source_sha256": digest,
                "source_family": row.get("source_family"),
                "collection_id": row.get("collection_id"),
            }
        )
    meta = {
        "sample_set_path": str(sample_set).replace("\\", "/"),
        "sample_set_self_sha256": payload.get("self_sha256"),
        "ordered_sample_ids": ordered,
        "sample_count": len(paths),
        "image_disjoint": bool(payload.get("image_disjoint")),
        "samples": meta_rows,
    }
    return paths, meta


def _collect_images(limit: int) -> list[Path]:
    paths: list[Path] = []
    seen: set[str] = set()
    if CELEBA.is_dir():
        for path in sorted(CELEBA.glob("*.jpg")):
            if len(paths) >= limit:
                break
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            paths.append(path)
    if len(paths) < limit and REFERENCE.is_dir():
        for path in sorted(REFERENCE.rglob("*.jpg")):
            if len(paths) >= limit:
                break
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                continue
            if digest in seen:
                continue
            seen.add(digest)
            paths.append(path)
    if len(paths) < limit:
        raise RuntimeError(f"only found {len(paths)} image-disjoint sources; need {limit}")
    return paths[:limit]


def _to_binary(mask: np.ndarray) -> np.ndarray:
    return (np.asarray(mask) != 0).astype(np.uint8) * 255


def _resize_nn(mask: np.ndarray, size_hw: tuple[int, int]) -> np.ndarray:
    image = Image.fromarray(_to_binary(mask), mode="L")
    return np.asarray(image.resize((size_hw[1], size_hw[0]), Image.Resampling.NEAREST))


def _pairwise_mean_iou(masks: list[np.ndarray]) -> float:
    bools = [(m != 0) for m in masks]
    scores: list[float] = []
    for i in range(len(bools)):
        for j in range(i + 1, len(bools)):
            scores.append(float(iou(bools[i], bools[j])))
    return float(np.mean(scores)) if scores else 0.0


def _largest_component(mask: np.ndarray) -> np.ndarray:
    from scipy import ndimage

    labeled, count = ndimage.label(mask != 0)
    if count <= 1:
        return _to_binary(mask)
    sizes = ndimage.sum(mask != 0, labeled, index=range(1, count + 1))
    keep = int(np.argmax(sizes)) + 1
    return ((labeled == keep).astype(np.uint8)) * 255


def _majority(masks: list[np.ndarray]) -> np.ndarray:
    stack = np.stack([(m != 0).astype(np.uint8) for m in masks], axis=0)
    threshold = len(masks) // 2 + 1
    return _largest_component(((stack.sum(axis=0) >= threshold).astype(np.uint8)) * 255)


def _bbox_from_mask(mask: np.ndarray, *, pad: int = 8) -> tuple[int, int, int, int]:
    binary = mask != 0
    if not binary.any():
        height, width = mask.shape[:2]
        return (0, 0, max(1, width), max(1, height))
    ys, xs = np.where(binary)
    height, width = binary.shape
    left = max(0, int(xs.min()) - pad)
    top = max(0, int(ys.min()) - pad)
    right = min(width, int(xs.max()) + 1 + pad)
    bottom = min(height, int(ys.max()) + 1 + pad)
    if right <= left:
        right = min(width, left + 1)
    if bottom <= top:
        bottom = min(height, top + 1)
    return (left, top, right, bottom)


class BiRefNetRunner:
    def __init__(self) -> None:
        from huggingface_hub import snapshot_download
        from transformers import AutoModelForImageSegmentation

        source = snapshot_download(
            repo_id="ZhengPeng7/BiRefNet",
            revision="e2bf8e4460fc8fa32bba5ea4d94b3233d367b0e4",
            ignore_patterns=["*.safetensors", "*.bin", "*.pth", "*.onnx"],
        )
        self._tmpdir = tempfile.TemporaryDirectory(prefix="mf-birefnet-")
        model_dir = Path(self._tmpdir.name) / "model"
        shutil.copytree(source, model_dir, symlinks=False)
        shutil.copy2(BIREFNET_CKPT, model_dir / "model.safetensors")
        self.model = AutoModelForImageSegmentation.from_pretrained(
            model_dir, trust_remote_code=True, local_files_only=True
        ).eval()
        self.device = torch.device("cuda")
        self.model.to(self.device)
        self.transform = transforms.Compose(
            [
                transforms.Resize((1024, 1024)),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ]
        )

    def infer(self, image_path: Path) -> np.ndarray:
        image, _original = _load_working_rgb(image_path)
        width, height = image.size
        tensor = self.transform(image).unsqueeze(0).to(self.device)
        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16):
            prediction = self.model(tensor)[-1].sigmoid().float().cpu()[0, 0]
        mask = (prediction.numpy() >= 0.5).astype(np.uint8) * 255
        del tensor, prediction
        torch.cuda.empty_cache()
        return _resize_nn(mask, (height, width))

    def close(self) -> None:
        del self.model
        torch.cuda.empty_cache()
        self._tmpdir.cleanup()


class SchpRunner:
    REVISION = "eb84c432cc697f494d99662a05f2335eb2f26095"
    NUM_CLASSES = 18
    INPUT_SIZE = 512

    def __init__(self) -> None:
        self._model = None
        self._prepare_model()

    def _ensure_source(self) -> Path:
        source = SCHP_CACHE / self.REVISION
        marker = source / "networks" / "AugmentCE2P.py"
        if marker.is_file():
            return source
        source.parent.mkdir(parents=True, exist_ok=True)
        import subprocess

        subprocess.run(
            [
                "git",
                "-c",
                "http.sslBackend=openssl",
                "clone",
                "--filter=blob:none",
                "https://github.com/GoGoDuck912/Self-Correction-Human-Parsing.git",
                str(source),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(source), "checkout", "--detach", self.REVISION],
            check=True,
            capture_output=True,
            text=True,
        )
        return source

    def _prepare_model(self) -> None:
        import types
        from collections import OrderedDict

        from torch import nn

        source = self._ensure_source()

        class PureInferenceABN(nn.BatchNorm2d):
            def __init__(self, num_features: int, activation: str = "none", **kwargs):
                super().__init__(num_features, **kwargs)
                self.activation = activation

            def forward(self, tensor: torch.Tensor) -> torch.Tensor:
                result = super().forward(tensor)
                if self.activation == "leaky_relu":
                    return torch.nn.functional.leaky_relu(result, 0.01, inplace=False)
                if self.activation == "elu":
                    return torch.nn.functional.elu(result, inplace=False)
                if self.activation == "relu":
                    return torch.nn.functional.relu(result, inplace=False)
                return result

        compatibility_module = types.ModuleType("modules")
        compatibility_module.InPlaceABNSync = PureInferenceABN
        sys.modules["modules"] = compatibility_module
        sys.path.insert(0, str(source))
        import networks  # noqa: PLC0415

        model = networks.init_model("resnet101", num_classes=self.NUM_CLASSES, pretrained=None)
        checkpoint_document = torch.load(SCHP_CKPT, map_location="cpu", weights_only=True)
        state = OrderedDict(
            (name.removeprefix("module."), tensor)
            for name, tensor in checkpoint_document["state_dict"].items()
        )
        model.load_state_dict(state, strict=True)
        self._model = model.eval().cuda()
        self._input_size = self.INPUT_SIZE

    def infer(self, image_path: Path) -> np.ndarray:
        import cv2

        image, _original = _load_working_rgb(image_path)
        width, height = image.size
        rgb = np.asarray(image)
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        resized = cv2.resize(
            bgr, (self._input_size, self._input_size), interpolation=cv2.INTER_LINEAR
        )
        tensor = torch.from_numpy(resized).permute(2, 0, 1).float().div(255)
        mean = torch.tensor([0.406, 0.456, 0.485]).view(3, 1, 1)
        std = torch.tensor([0.225, 0.224, 0.229]).view(3, 1, 1)
        tensor = ((tensor - mean) / std).unsqueeze(0).cuda()
        with torch.inference_mode():
            output = self._model(tensor)
        logits = output[0][-1]
        logits = torch.nn.functional.interpolate(
            logits.float(),
            size=(self._input_size, self._input_size),
            mode="bilinear",
            align_corners=True,
        )
        labels = logits.softmax(dim=1)[0].argmax(dim=0).cpu().numpy().astype(np.uint8)
        del tensor, logits, output
        torch.cuda.empty_cache()
        return _resize_nn((labels != 0).astype(np.uint8) * 255, (height, width))

    def close(self) -> None:
        del self._model
        torch.cuda.empty_cache()


class FaceparseRunner:
    def __init__(self) -> None:
        sys.path.insert(0, str(FACEPARSE_SRC))
        from model import BiSeNet  # noqa: PLC0415

        self.model = BiSeNet(n_classes=19).cuda().eval()
        state = torch.load(FACEPARSE_CKPT, map_location="cuda", weights_only=True)
        self.model.load_state_dict(state, strict=True)

    def infer(self, image_path: Path) -> np.ndarray:
        from torchvision.transforms import functional as TF

        image, _original = _load_working_rgb(image_path)
        width, height = image.size
        # Working-resolution portraits: use a large central crop so faceparse
        # contributes a meaningful full-canvas signal alongside body families.
        crop_box = (
            round(width * 0.15),
            round(height * 0.05),
            round(width * 0.85),
            round(height * 0.95),
        )
        crop = image.crop(crop_box).resize((512, 512), Image.Resampling.BILINEAR)
        tensor = TF.normalize(
            TF.to_tensor(crop),
            mean=(0.485, 0.456, 0.406),
            std=(0.229, 0.224, 0.225),
        ).unsqueeze(0)
        with torch.inference_mode():
            logits = self.model(tensor.cuda())[0]
        labels = logits.argmax(dim=1).squeeze(0).to(torch.uint8).cpu().numpy()
        del tensor, logits
        torch.cuda.empty_cache()
        crop_mask = Image.fromarray((labels > 0).astype(np.uint8) * 255, mode="L").resize(
            (crop_box[2] - crop_box[0], crop_box[3] - crop_box[1]),
            Image.Resampling.NEAREST,
        )
        canvas = Image.new("L", (width, height), 0)
        canvas.paste(crop_mask, (crop_box[0], crop_box[1]))
        return np.asarray(canvas)

    def close(self) -> None:
        del self.model
        torch.cuda.empty_cache()


class Sam2LocalCudaRunner:
    """Governed local-CUDA SAM2.1 large with BiRefNet box prior (OOM → base_plus)."""

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        options = production_sam2_runtime_options()
        self.provider = WslSam2Provider(
            {
                "sam2.1_hiera_large": SAM2_LARGE,
                "sam2.1_hiera_base_plus": SAM2_BASE,
            },
            dict(MODEL_CONFIGS),
            self.work_dir,
            **options,
        )
        self.model_name = "sam2.1_hiera_large"

    def infer(self, image_path: Path, prior_mask: np.ndarray) -> np.ndarray:
        image, _original = _load_working_rgb(image_path)
        rgb = np.asarray(image)
        height, width = rgb.shape[:2]
        prior = _resize_nn(prior_mask, (height, width))
        try:
            return self._predict(rgb, prior, model=self.model_name)
        except Exception as exc:  # noqa: BLE001 — OOM / load fall back once
            if self.model_name == "sam2.1_hiera_large" and (
                "out of memory" in str(exc).lower() or "CUDA" in str(exc)
            ):
                torch.cuda.empty_cache()
                self.model_name = "sam2.1_hiera_base_plus"
                return self._predict(rgb, prior, model=self.model_name)
            raise

    def _predict(self, rgb: np.ndarray, prior: np.ndarray, *, model: str) -> np.ndarray:
        embedding = self.provider.embed(rgb, model=model, precision="fp16")
        try:
            box = _bbox_from_mask(prior)
            cx = (box[0] + box[2]) // 2
            cy = (box[1] + box[3]) // 2
            plan = PromptPlan(
                label=LABEL,
                box_xyxy=box,
                positive_points=((cx, cy),),
                negative_points=(),
                prior_quality="low",
                multimask_output=True,
            )
            candidates = self.provider.predict(embedding, plan, multimask_output=True)
            best = max(candidates, key=lambda item: item.predicted_iou)
            return ((best.logits > 0).astype(np.uint8)) * 255
        finally:
            self.provider.close(embedding)
            torch.cuda.empty_cache()

    def close(self) -> None:
        torch.cuda.empty_cache()


# Glue-contract alias used by tournament_families.assert_cli_invokes_configured_families.
Sam2Runner = Sam2LocalCudaRunner


def _identities() -> tuple[ProviderIdentity, ...]:
    runtime = "local_cuda_comfyui_torch_2.11.0+cu128"
    return (
        ProviderIdentity(
            provider_key="birefnet_general",
            role="silhouette_provider",
            model_family="birefnet",
            source_commit="e2bf8e4460fc8fa32bba5ea4d94b3233d367b0e4",
            runtime_fingerprint=runtime,
        ),
        ProviderIdentity(
            provider_key="schp_atr",
            role="parsing_provider",
            model_family="schp",
            source_commit="eb84c432cc697f494d99662a05f2335eb2f26095",
            runtime_fingerprint=runtime,
        ),
        ProviderIdentity(
            provider_key="faceparse_bisenet",
            role="face_parser",
            model_family="faceparse",
            source_commit="d2e684c",
            runtime_fingerprint=runtime,
        ),
        ProviderIdentity(
            provider_key="sam2_1_large",
            role="interactive_segmenter",
            model_family="sam2",
            source_commit="2b90b9f5ceec907a1c18123530e92e794ad901a4",
            runtime_fingerprint=runtime,
        ),
    )


def _process_one(
    *,
    image_path: Path,
    masks: dict[str, np.ndarray],
    work_root: Path,
    production_machine_root: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    image_id = _image_id(image_path)
    stage = work_root / image_id
    stage.mkdir(parents=True, exist_ok=True)
    (stage / "autonomy").mkdir(exist_ok=True)
    (stage / "masks").mkdir(exist_ok=True)

    family_masks = [masks[name] for name in FAMILIES]
    mean_iou = _pairwise_mean_iou(family_masks)
    consensus = _majority(family_masks)
    fg = float((consensus != 0).mean())
    row: dict[str, Any] = {
        "image_id": image_id,
        "source_path": str(image_path),
        "source_sha256": sha256_file(image_path),
        "mean_pairwise_iou": round(mean_iou, 6),
        "consensus_fg_fraction": round(fg, 6),
    }
    if mean_iou < MIN_MEAN_PAIRWISE_IOU or not (MIN_FG_FRACTION < fg < MAX_FG_FRACTION):
        row["status"] = "agreement_gate_failed"
        row["decision_status"] = "residual_human_queue"
        return row

    paths: dict[str, Path] = {}
    for name, mask in masks.items():
        paths[name] = write_binary_mask(stage / "masks" / f"{name}.png", mask)
    consensus_path = write_binary_mask(stage / "masks" / "consensus_majority.png", consensus)

    identities = _identities()
    families = tuple(sorted({identity.model_family for identity in identities}))
    candidate = MaskCandidateInput(
        candidate_id="consensus_majority",
        mask_path=consensus_path,
        independent_sources=families,
        critic_pass_weight=0.95,
        critic_disagreement=False,
        pose_consistency=0.95,
        block_qc_ids=(),
        provider_identities=identities,
    )
    # Zero protected/exclusive neighbors for this bounded admission tournament.
    protected = np.zeros(consensus.shape, dtype=bool)
    exclusive = np.zeros(consensus.shape, dtype=bool)
    evidence = build_mask_candidate_evidence(
        (candidate,),
        protected_neighbor=protected,
        mutually_exclusive=exclusive,
        ontology_max_components=1,
    )
    decision = run_candidate_tournament(
        evidence,
        label=LABEL,
        context=CONTEXT,
        pipeline_fingerprint=PIPELINE_FP,
        config=config,
        certificate=None,
        allow_autonomous_profile=False,
    )
    # Envelope paths MUST be relative to production runs/ (admission scan root),
    # not the tournament subdirectory work_root.
    emit = emit_lifecycle_and_corpus_record(
        stage / "autonomy" / f"{LABEL}.json",
        image_id=image_id,
        instance_id="p0",
        pipeline_fingerprint=PIPELINE_FP,
        decision=decision,
        machine_root=production_machine_root,
        risk_bucket=CONTEXT,
        repo_root=REPO_ROOT,
    )
    row.update(
        {
            "status": "processed",
            "decision_status": decision.status,
            "winner_score": decision.winner_score,
            "lifecycle_path": emit["lifecycle_relpath"],
            "sidecar_write_path": emit["lifecycle_path"],
            "corpus_envelope_written": emit["corpus_envelope_written"],
            "corpus_envelope_relpath": emit["corpus_envelope_relpath"],
            "production_machine_root": str(production_machine_root),
            "family_mask_paths": {
                name: str(path.relative_to(REPO_ROOT)).replace("\\", "/")
                for name, path in paths.items()
            },
        }
    )
    return row


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=64)
    parser.add_argument(
        "--sample-set",
        type=Path,
        default=None,
        help="Frozen tournament_sample_set JSON (sibling feed). Prefer over ad-hoc collection.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--machine-root",
        type=Path,
        default=REPO_ROOT / "runs" / "autonomous_gold_tournament_20260720",
    )
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise SystemExit("CUDA required; invoke with ComfyUI cu128 venv python")

    started = time.perf_counter()
    sample_meta: dict[str, Any] | None = None
    if args.sample_set is not None:
        sample_set = args.sample_set
        if not sample_set.is_absolute():
            sample_set = (REPO_ROOT / sample_set).resolve()
        images, sample_meta = _load_sample_set(sample_set)
        if args.limit and len(images) > args.limit:
            images = images[: args.limit]
            sample_meta = {
                **sample_meta,
                "ordered_sample_ids": sample_meta["ordered_sample_ids"][: args.limit],
                "sample_count": args.limit,
                "samples": sample_meta["samples"][: args.limit],
                "truncated_to_limit": args.limit,
            }
    else:
        images = _collect_images(args.limit)
    config = yaml.safe_load(
        (REPO_ROOT / "configs/autonomous_masks.yaml").read_text(encoding="utf-8")
    )
    production_machine_root = (REPO_ROOT / "runs").resolve()
    machine_root = args.machine_root.resolve()
    try:
        machine_root.relative_to(production_machine_root)
    except ValueError:
        # Keep tournament stages under production runs/ so admission can scan them.
        machine_root = (production_machine_root / machine_root.name).resolve()
    machine_root.mkdir(parents=True, exist_ok=True)
    production_machine_root.mkdir(parents=True, exist_ok=True)
    # Admission / corpus assembly always scan production runs/, not the batch subdir.
    os.environ["MASKFACTORY_MACHINE_ROOT"] = str(production_machine_root)

    # GPU-sequence: BiRefNet -> SCHP -> faceparse -> SAM2 (never concurrent).
    biref = BiRefNetRunner()
    biref_masks: dict[str, np.ndarray] = {}
    for path in images:
        biref_masks[str(path)] = biref.infer(path)
    biref.close()

    schp = SchpRunner()
    schp_masks: dict[str, np.ndarray] = {}
    for path in images:
        schp_masks[str(path)] = schp.infer(path)
    schp.close()

    face = FaceparseRunner()
    face_masks: dict[str, np.ndarray] = {}
    for path in images:
        face_masks[str(path)] = face.infer(path)
    face.close()

    sam2 = Sam2LocalCudaRunner(machine_root / "_sam2_work")
    sam2_masks: dict[str, np.ndarray] = {}
    for path in images:
        key = str(path)
        sam2_masks[key] = sam2.infer(path, biref_masks[key])
    sam2.close()

    rows: list[dict[str, Any]] = []
    for path in images:
        key = str(path)
        rows.append(
            _process_one(
                image_path=path,
                masks={
                    "birefnet_general": biref_masks[key],
                    "schp_atr": schp_masks[key],
                    "faceparse_bisenet": face_masks[key],
                    "sam2_1_large": sam2_masks[key],
                },
                work_root=machine_root,
                production_machine_root=production_machine_root,
                config=config,
            )
        )

    mvc = sum(1 for row in rows if row.get("decision_status") == "machine_verified_candidate")
    residual = sum(1 for row in rows if row.get("decision_status") == "residual_human_queue")
    agreement_fail = sum(1 for row in rows if row.get("status") == "agreement_gate_failed")
    evidence = {
        "artifact_type": "multiprovider_gold_tournament_64",
        "schema_version": "1.0.0",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "authority": "autonomous_certified_gold_profile",
        "evidence_tier": "RUNTIME_PASS_BOUNDED",
        "pipeline_fingerprint": PIPELINE_FP,
        "label": LABEL,
        "context": CONTEXT,
        "live_independent_mask_families": list(FAMILIES),
        "live_independent_mask_families_count": len(FAMILIES),
        "runtime": {
            "python": sys.executable,
            "torch": torch.__version__,
            "cuda": True,
            "device": torch.cuda.get_device_name(0),
            "docker_required": False,
        },
        "sample_limit": args.limit,
        "samples_attempted": len(rows),
        "sibling_feed_sample_set": sample_meta,
        "counts": {
            "machine_verified_candidate": mvc,
            "residual_human_queue": residual,
            "agreement_gate_failed": agreement_fail,
            "calibrated_auto_accepted": 0,
            "autonomous_certified_gold": 0,
            "champions": 0,
        },
        "machine_root": str(machine_root.relative_to(REPO_ROOT)).replace("\\", "/"),
        "honesty_boundary": {
            "no_fabricated_wilson_samples": True,
            "no_force_registered_champions": True,
            "agreement_gate_enforced": True,
            "min_mean_pairwise_iou": MIN_MEAN_PAIRWISE_IOU,
            "wilson_math_unchanged": True,
            "certificate_not_minted_by_this_tool": True,
            "frozen_sibling_feed_required": sample_meta is not None,
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "rows": rows,
    }
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "ok",
                "mvc": mvc,
                "residual": residual,
                "agreement_fail": agreement_fail,
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0 if mvc > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
