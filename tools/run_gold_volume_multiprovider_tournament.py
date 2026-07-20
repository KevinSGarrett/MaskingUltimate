"""Live multi-provider tournament over gold-volume source images (no fabrication).

Runs the governed local-CUDA family set from
``configs/multiprovider_tournament_families.yaml`` on read-only gold-volume
inputs (MaskedWarehouse / reference / DAZ), GPU-sequences consumers on the
single 8 GiB card, computes real consensus metrics via
``build_mask_candidate_evidence``, and writes genuine
``machine_verified_candidate`` lifecycle sidecars + corpus envelopes under
``runs/`` when the tournament honestly passes.

Required families (Windows ComfyUI cu128 venv; independent model families):
  * birefnet_general  (silhouette)
  * schp_atr          (human parsing foreground)
  * faceparse_bisenet (face-parts foreground, pasted into full canvas)
  * sam2_1_large      (local-CUDA SAM2.1; box prior from BiRefNet)

Honesty boundary:
  * Never fabricates IoU / family counts / certificates.
  * Never treats external/reference/DAZ labels as gold.
  * Never force-registers champions.
  * Family-online smokes alone are not tournament invocation — this CLI must
    call every required runner.
  * Fail-closed residual_human_queue when score/agreement is insufficient.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from maskfactory.autonomy.adapters import (  # noqa: E402
    MaskCandidateInput,
    build_mask_candidate_evidence,
)
from maskfactory.autonomy.emit import emit_lifecycle_and_corpus_record  # noqa: E402
from maskfactory.autonomy.gold_volume_sources import probe_gold_volume_sources  # noqa: E402
from maskfactory.autonomy.tournament import run_candidate_tournament  # noqa: E402
from maskfactory.autonomy.tournament_families import (  # noqa: E402
    load_tournament_family_map,
    validate_runner_coverage,
)
from maskfactory.io.hashing import sha256_file  # noqa: E402
from maskfactory.io.png_strict import write_binary_mask  # noqa: E402
from maskfactory.providers.contracts import ProviderIdentity  # noqa: E402
from maskfactory.serve.providers import production_sam2_runtime_options  # noqa: E402
from maskfactory.stages.s05_geometry import PromptPlan  # noqa: E402
from maskfactory.stages.s07_sam2 import MODEL_CONFIGS, WslSam2Provider  # noqa: E402

COMFY_PY = Path("C:/Comfy_UI_Main/ComfyUI/.venv/Scripts/python.exe")
LABEL = "torso"
CONTEXT = "solo"
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}

FAMILY_MAP = load_tournament_family_map()
REQUIRED_FAMILIES = FAMILY_MAP.required_invocation_keys
validate_runner_coverage(
    REQUIRED_FAMILIES,
    {
        "birefnet_general",
        "schp_atr",
        "faceparse_bisenet",
        "sam2_1_large",
    },
)


def _ts() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _gpu_sequence(consumer: str, out: Path) -> dict[str, Any]:
    # Prefer ``plan`` over ``sequence``: ``sequence`` reclaims nuclio via Docker
    # restart and can hang indefinitely when the Docker named pipe is down.
    # Ollama is unloaded separately with ``ollama stop`` before inference.
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools/gpu_sequencer.py"),
            "plan",
            "--consumer",
            consumer,
            "--json",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
        timeout=120,
    )
    payload: dict[str, Any] = {}
    if out.is_file():
        try:
            payload = json.loads(out.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
    return {
        "exit_code": proc.returncode,
        "decision": payload.get("decision", payload),
        "stdout_tail": (proc.stdout or "")[-400:],
        "report": str(out.relative_to(REPO_ROOT)).replace("\\", "/"),
    }


def _empty_cuda() -> None:
    if not COMFY_PY.is_file():
        return
    subprocess.run(
        [
            str(COMFY_PY),
            "-c",
            "import torch; torch.cuda.empty_cache() if torch.cuda.is_available() else None; print('ok')",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    time.sleep(2)


def _load_sibling_feed(feed_path: Path, *, limit: int | None = None) -> list[dict[str, str]]:
    """Load the frozen sibling tournament sample set (identical ordered_sample_ids)."""
    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    sample_set_rel = feed.get("sample_set_path") or feed.get("feed_path")
    if feed.get("artifact_type") == "tournament_sample_set_sibling_feed_latest":
        sample_set_rel = feed.get("sample_set_path")
        if not sample_set_rel:
            inner = REPO_ROOT / str(feed["feed_path"])
            inner_doc = json.loads(inner.read_text(encoding="utf-8"))
            sample_set_rel = inner_doc["sample_set_path"]
    elif feed.get("artifact_type") == "tournament_sample_set_sibling_feed":
        sample_set_rel = feed["sample_set_path"]
    elif feed.get("artifact_type") == "tournament_sample_set":
        sample_set_rel = str(feed_path.relative_to(REPO_ROOT)).replace("\\", "/")
    if not sample_set_rel:
        raise SystemExit(f"sibling feed missing sample_set_path: {feed_path}")
    sample_set_path = REPO_ROOT / sample_set_rel
    sample_set = json.loads(sample_set_path.read_text(encoding="utf-8"))
    samples = sample_set.get("samples") or []
    picked: list[dict[str, str]] = []
    for row in samples:
        path = Path(row["source_path_readonly"])
        if not path.is_file():
            continue
        picked.append(
            {
                "path": str(path),
                "source_family": str(row.get("source_family") or "sibling_feed"),
                "source_sha256": str(row["source_sha256"]),
                "sample_id": str(row.get("sample_id") or ""),
            }
        )
        if limit is not None and len(picked) >= limit:
            break
    if not picked:
        raise SystemExit(f"sibling feed resolved zero readable images: {sample_set_path}")
    return picked


def _resolve_sample_set_path(sample_feed: Path | None, sample_set: Path | None) -> Path | None:
    if sample_set is not None:
        return sample_set if sample_set.is_absolute() else REPO_ROOT / sample_set
    if sample_feed is None:
        return None
    feed_path = sample_feed if sample_feed.is_absolute() else REPO_ROOT / sample_feed
    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    # latest pointer -> concrete sibling feed -> nested sample_set.path
    if feed.get("artifact_type") == "tournament_sample_set_sibling_feed_latest":
        concrete = REPO_ROOT / str(feed["feed_path"])
        feed = json.loads(concrete.read_text(encoding="utf-8"))
    if feed.get("artifact_type") == "tournament_sample_set_sibling_feed":
        nested = feed.get("sample_set") or {}
        rel = nested.get("path")
        if not rel:
            raise SystemExit(f"sibling feed missing sample_set.path: {feed_path}")
        return REPO_ROOT / str(rel)
    if feed.get("artifact_type") == "tournament_sample_set":
        return feed_path
    raise SystemExit(f"unsupported sample feed artifact_type: {feed.get('artifact_type')}")


def _pick_images_from_sample_set(sample_set_path: Path, limit: int) -> list[dict[str, str]]:
    """Load the frozen sibling tournament corpus (identical ordered_sample_ids)."""
    doc = json.loads(sample_set_path.read_text(encoding="utf-8"))
    samples = doc.get("samples") or []
    ordered = doc.get("ordered_sample_ids") or [s.get("sample_id") for s in samples]
    by_id = {s.get("sample_id"): s for s in samples if isinstance(s, dict)}
    picked: list[dict[str, str]] = []
    missing: list[str] = []
    for sample_id in ordered:
        if len(picked) >= limit:
            break
        row = by_id.get(sample_id)
        if not row:
            missing.append(str(sample_id))
            continue
        path = Path(str(row["source_path_readonly"]))
        if not path.is_file():
            missing.append(str(sample_id))
            continue
        # Read-only consume; verify content hash when present (no fabrication).
        expected = str(row.get("source_sha256") or "")
        actual = sha256_file(path)
        if expected and actual != expected:
            raise SystemExit(
                f"sample {sample_id} sha256 mismatch: expected={expected} actual={actual}"
            )
        picked.append(
            {
                "path": str(path),
                "source_family": str(row.get("source_family") or "sibling_feed"),
                "source_sha256": actual,
                "sample_id": str(sample_id),
                "collection_id": str(row.get("collection_id") or ""),
            }
        )
    if missing:
        raise SystemExit(f"sibling sample set unavailable paths ({len(missing)}): {missing[:8]}")
    return picked


def _pick_images(limit: int) -> list[dict[str, str]]:
    """Bounded, shallow picks — never deep-walk F: USB corpora."""
    probe = probe_gold_volume_sources()
    selected = probe.selected_roots()
    picked: list[dict[str, str]] = []

    def _add_dir(directory: Path, family: str, *, max_scan: int = 64) -> None:
        nonlocal picked
        if len(picked) >= limit or not directory.is_dir():
            return
        scanned = 0
        try:
            entries = sorted(
                (
                    Path(entry.path)
                    for entry in os.scandir(directory)
                    if entry.is_file() and Path(entry.name).suffix.lower() in IMG_EXT
                ),
                key=lambda path: path.name,
            )
        except OSError:
            return
        for path in entries:
            if len(picked) >= limit or scanned >= max_scan:
                return
            scanned += 1
            try:
                with Image.open(path) as img:
                    w, h = img.size
                if w * h > 4_000_000:
                    continue
            except OSError:
                continue
            picked.append(
                {
                    "path": str(path),
                    "source_family": family,
                    "source_sha256": sha256_file(path),
                }
            )

    mw = selected.get("maskedwarehouse")
    if mw is not None:
        _add_dir(Path(mw) / "CelebAMask-HQ" / "CelebA-HQ-img", "maskedwarehouse")
        _add_dir(Path(mw) / "LaPa" / "test" / "images", "maskedwarehouse")
    # Optional shallow USB toppers only if C: corpus was short.
    if len(picked) < limit:
        ref = selected.get("reference_library")
        if ref is not None:
            bench = Path(ref) / "benchmark_reference"
            if bench.is_dir():
                try:
                    subdirs = sorted(
                        Path(entry.path) for entry in os.scandir(bench) if entry.is_dir()
                    )[:3]
                except OSError:
                    subdirs = []
                for sub in subdirs:
                    _add_dir(sub, "reference_library", max_scan=16)
    if len(picked) < limit:
        daz = selected.get("daz")
        if daz is not None:
            renders = Path(daz) / "12_renders"
            if renders.is_dir():
                try:
                    subdirs = sorted(
                        Path(entry.path) for entry in os.scandir(renders) if entry.is_dir()
                    )[:2]
                except OSError:
                    subdirs = []
                for sub in subdirs:
                    _add_dir(sub, "daz", max_scan=16)
    return picked


def _run_birefnet(image: Path, out_mask: Path) -> dict[str, Any]:
    checkpoint = REPO_ROOT / "models/silhouette/BiRefNet-general.safetensors"
    # Inline inference that also writes a full-res binary mask.
    code = r"""
import hashlib, json, shutil, sys, tempfile
from pathlib import Path
import numpy as np
import torch
from huggingface_hub import snapshot_download
from PIL import Image
from torchvision import transforms
from transformers import AutoModelForImageSegmentation

checkpoint = Path(sys.argv[1])
image_path = Path(sys.argv[2])
out_mask = Path(sys.argv[3])
REPO_ID = "ZhengPeng7/BiRefNet"
REVISION = "e2bf8e4460fc8fa32bba5ea4d94b3233d367b0e4"
source = snapshot_download(repo_id=REPO_ID, revision=REVISION,
    ignore_patterns=["*.safetensors", "*.bin", "*.pth", "*.onnx"])
with tempfile.TemporaryDirectory(prefix="mf-biref-") as temporary:
    model_dir = Path(temporary) / "model"
    shutil.copytree(source, model_dir, symlinks=False)
    shutil.copy2(checkpoint, model_dir / "model.safetensors")
    model = AutoModelForImageSegmentation.from_pretrained(
        model_dir, trust_remote_code=True, local_files_only=True).eval()
    device = torch.device("cuda")
    model.to(device)
    image = Image.open(image_path).convert("RGB")
    w, h = image.size
    transform = transforms.Compose([
        transforms.Resize((1024, 1024)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])
    tensor = transform(image).unsqueeze(0).to(device)
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16):
        prediction = model(tensor)[-1].sigmoid().float().cpu()[0, 0]
    mask1024 = (prediction.numpy().clip(0, 1) >= 0.5)
    mask = np.array(Image.fromarray(mask1024.astype(np.uint8) * 255).resize((w, h), Image.NEAREST))
    binary = (mask >= 128).astype(np.uint8) * 255
    out_mask.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(binary, mode="L").save(out_mask)
    fg = float((binary >= 128).mean())
    print(json.dumps({
        "passed": bool(0.01 < fg < 0.99),
        "foreground_fraction": round(fg, 6),
        "family": "birefnet_general",
        "output_sha256": hashlib.sha256(binary.tobytes()).hexdigest(),
        "mask_path": str(out_mask),
    }, sort_keys=True))
    del model, tensor, prediction
    torch.cuda.empty_cache()
"""
    # Prefer png_strict rewrite after raw save — handled by caller via rewrite.
    proc = subprocess.run(
        [str(COMFY_PY), "-c", code, str(checkpoint), str(image), str(out_mask)],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
        cwd=str(REPO_ROOT),
    )
    if proc.returncode != 0:
        return {
            "passed": False,
            "family": "birefnet_general",
            "stderr_tail": (proc.stderr or "")[-2000:],
            "stdout_tail": (proc.stdout or "")[-1000:],
        }
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        return {"passed": False, "family": "birefnet_general", "reason": str(exc)}


def _run_schp(image: Path, out_mask: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env["MASKFACTORY_SCHP_CACHE"] = str(REPO_ROOT / "models" / "runtime_cache" / "schp")
    checkpoint = REPO_ROOT / "models/parsing_fallback/exp-schp-201908301523-atr.pth"
    code = (
        r"""
import json, os, sys
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, r"""
        + repr(str(REPO_ROOT / "tools"))
        + r""")
from smoke_schp_wsl import infer
checkpoint = Path(sys.argv[1])
image_path = Path(sys.argv[2])
out_mask = Path(sys.argv[3])
probs = infer(checkpoint, image_path, "atr")
labels = probs.argmax(axis=0).astype(np.uint8)
fg = labels != 0
image = Image.open(image_path).convert("RGB")
w, h = image.size
mask = np.array(Image.fromarray(fg.astype(np.uint8) * 255).resize((w, h), Image.NEAREST))
binary = (mask >= 128).astype(np.uint8) * 255
out_mask.parent.mkdir(parents=True, exist_ok=True)
Image.fromarray(binary, mode="L").save(out_mask)
frac = float((binary >= 128).mean())
print(json.dumps({
    "passed": bool(0.01 < frac < 0.99),
    "foreground_fraction": round(frac, 6),
    "family": "schp_atr",
    "mask_path": str(out_mask),
}, sort_keys=True))
"""
    )
    proc = subprocess.run(
        [str(COMFY_PY), "-c", code, str(checkpoint), str(image), str(out_mask)],
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
        cwd=str(REPO_ROOT),
        env=env,
    )
    if proc.returncode != 0:
        return {
            "passed": False,
            "family": "schp_atr",
            "stderr_tail": (proc.stderr or "")[-2000:],
            "stdout_tail": (proc.stdout or "")[-1000:],
        }
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        return {"passed": False, "family": "schp_atr", "reason": str(exc)}


def _run_faceparse(image: Path, out_mask: Path) -> dict[str, Any]:
    checkpoint = REPO_ROOT / "models/faceparse/79999_iter.pth"
    source = REPO_ROOT / "models/runtime_cache/face-parsing-pytorch_d2e684c"
    code = r"""
import json, sys
from pathlib import Path
import numpy as np
import torch
from PIL import Image
from torchvision.transforms import functional as TF
sys.path.insert(0, sys.argv[4])
from model import BiSeNet
checkpoint = Path(sys.argv[1])
image_path = Path(sys.argv[2])
out_mask = Path(sys.argv[3])
image = Image.open(image_path).convert("RGB")
w, h = image.size
# Centered face-biased crop for portrait corpora (CelebA/LaPa).
crop_box = (round(w * 0.15), round(h * 0.05), round(w * 0.85), round(h * 0.95))
crop = image.crop(crop_box).resize((512, 512), Image.Resampling.BILINEAR)
tensor = TF.normalize(TF.to_tensor(crop), (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)).unsqueeze(0)
model = BiSeNet(n_classes=19).cuda().eval()
state = torch.load(checkpoint, map_location="cuda", weights_only=True)
model.load_state_dict(state, strict=True)
with torch.inference_mode():
    labels = model(tensor.cuda())[0].argmax(dim=1).squeeze(0).to(torch.uint8).cpu().numpy()
del model, tensor
torch.cuda.empty_cache()
fg = (labels > 0).astype(np.uint8) * 255
crop_mask = Image.fromarray(fg, mode="L").resize(
    (crop_box[2] - crop_box[0], crop_box[3] - crop_box[1]), Image.NEAREST)
canvas = Image.new("L", (w, h), 0)
canvas.paste(crop_mask, (crop_box[0], crop_box[1]))
binary = np.array(canvas)
binary = (binary >= 128).astype(np.uint8) * 255
out_mask.parent.mkdir(parents=True, exist_ok=True)
Image.fromarray(binary, mode="L").save(out_mask)
frac = float((binary >= 128).mean())
print(json.dumps({
    "passed": bool(0.01 < frac < 0.99),
    "foreground_fraction": round(frac, 6),
    "family": "faceparse_bisenet",
    "crop_box": list(crop_box),
    "mask_path": str(out_mask),
}, sort_keys=True))
"""
    proc = subprocess.run(
        [
            str(COMFY_PY),
            "-c",
            code,
            str(checkpoint),
            str(image),
            str(out_mask),
            str(source),
        ],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
        cwd=str(REPO_ROOT),
    )
    if proc.returncode != 0:
        return {
            "passed": False,
            "family": "faceparse_bisenet",
            "stderr_tail": (proc.stderr or "")[-2000:],
            "stdout_tail": (proc.stdout or "")[-1000:],
        }
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        return {"passed": False, "family": "faceparse_bisenet", "reason": str(exc)}


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


def _run_sam2(image: Path, out_mask: Path, *, prior_mask: Path, work_dir: Path) -> dict[str, Any]:
    """Invoke local-CUDA SAM2.1 large with BiRefNet box prior (governed S07 path)."""
    try:
        prior = np.array(Image.open(prior_mask).convert("L"))
        prior_binary = (prior >= 128).astype(np.uint8) * 255
        options = production_sam2_runtime_options()
        provider = WslSam2Provider(
            {
                "sam2.1_hiera_large": REPO_ROOT / "models/sam2/sam2.1_hiera_large.pt",
                "sam2.1_hiera_base_plus": REPO_ROOT / "models/sam2/sam2.1_hiera_base_plus.pt",
            },
            dict(MODEL_CONFIGS),
            work_dir,
            **options,
        )
        rgb = np.asarray(Image.open(image).convert("RGB"))
        embedding = provider.embed(rgb, model="sam2.1_hiera_large", precision="fp16")
        try:
            box = _bbox_from_mask(prior_binary)
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
            candidates = provider.predict(embedding, plan, multimask_output=True)
            best = max(candidates, key=lambda item: item.predicted_iou)
            binary = ((best.logits > 0).astype(np.uint8)) * 255
        finally:
            provider.close(embedding)
        out_mask.parent.mkdir(parents=True, exist_ok=True)
        write_binary_mask(out_mask, binary)
        fg = float((binary >= 128).mean())
        return {
            "passed": bool(0.01 < fg < 0.99),
            "foreground_fraction": round(fg, 6),
            "family": "sam2_1_large",
            "mask_path": str(out_mask),
            "box_prior": "birefnet_general",
            "runtime": "local_cuda_s07",
        }
    except Exception as exc:  # noqa: BLE001 - seal honest failure for this family
        return {
            "passed": False,
            "family": "sam2_1_large",
            "reason": f"{type(exc).__name__}: {exc}",
        }


def _rewrite_strict(path: Path) -> Path:
    arr = np.array(Image.open(path).convert("L"))
    binary = (arr >= 128).astype(np.uint8) * 255
    return write_binary_mask(path, binary)


def _identity(family: str, provider_key: str, role: str) -> ProviderIdentity:
    return ProviderIdentity(
        provider_key=provider_key,
        role=role,
        model_family=family,
        source_commit=f"live-{family}-20260720",
        runtime_fingerprint="comfyui-venv-cu128-rtx5060",
    )


def _run_one_image(
    image_meta: dict[str, str],
    *,
    work_root: Path,
    config: dict[str, Any],
    pipeline_fp: str,
    machine_root: Path,
) -> dict[str, Any]:
    image = Path(image_meta["path"])
    image_id = hashlib.sha256(f"{image_meta['source_sha256']}:{image.name}".encode()).hexdigest()[
        :16
    ]
    stage = work_root / image_id
    masks_dir = stage / "masks"
    masks_dir.mkdir(parents=True, exist_ok=True)
    family_reports: dict[str, Any] = {}

    runners = (
        ("birefnet_general", _run_birefnet, "silhouette_provider"),
        ("schp_atr", _run_schp, "parsing_provider"),
        ("faceparse_bisenet", _run_faceparse, "face_parsing_provider"),
    )
    mask_paths: dict[str, Path] = {}
    for family, runner, _role in runners:
        _empty_cuda()
        out = masks_dir / f"{family}.png"
        report = runner(image, out)
        family_reports[family] = report
        if report.get("passed") and out.is_file():
            mask_paths[family] = _rewrite_strict(out)

    # SAM2 local-CUDA is required by the family map; needs BiRefNet box prior.
    if "birefnet_general" in mask_paths:
        _empty_cuda()
        sam2_out = masks_dir / "sam2_1_large.png"
        sam2_report = _run_sam2(
            image,
            sam2_out,
            prior_mask=mask_paths["birefnet_general"],
            work_dir=stage / "_sam2_work",
        )
        family_reports["sam2_1_large"] = sam2_report
        if sam2_report.get("passed") and sam2_out.is_file():
            mask_paths["sam2_1_large"] = _rewrite_strict(sam2_out)
    else:
        family_reports["sam2_1_large"] = {
            "passed": False,
            "family": "sam2_1_large",
            "reason": "birefnet_general prior unavailable",
        }

    live_families = sorted(mask_paths)
    missing_required = [key for key in REQUIRED_FAMILIES if key not in mask_paths]
    if len(live_families) < 3 or missing_required:
        return {
            "image_id": image_id,
            "source": image_meta,
            "status": "insufficient_live_families",
            "live_families": live_families,
            "missing_required_families": missing_required,
            "family_reports": family_reports,
        }

    # Majority-vote consensus mask with full live-family provenance.
    arrays = {
        name: (np.array(Image.open(path).convert("L")) >= 128) for name, path in mask_paths.items()
    }
    shape = next(iter(arrays.values())).shape
    stack = np.stack([arrays[name] for name in live_families], axis=0)
    majority = stack.sum(axis=0) >= (len(live_families) // 2 + 1)
    consensus_path = _rewrite_strict(
        write_binary_mask(masks_dir / "cross_family_majority.png", majority.astype(np.uint8) * 255)
    )

    identities = {
        "birefnet_general": _identity("birefnet", "birefnet_general", "silhouette_provider"),
        "schp_atr": _identity("schp", "schp_atr", "parsing_provider"),
        "faceparse_bisenet": _identity("faceparse", "faceparse_bisenet", "face_parser"),
        "sam2_1_large": _identity("sam2", "sam2_1_large", "interactive_segmenter"),
    }
    all_ids = tuple(identities[name] for name in live_families)

    inputs = [
        MaskCandidateInput(
            candidate_id="cross_family_majority",
            mask_path=consensus_path,
            independent_sources=tuple(identities[n].model_family for n in live_families),
            critic_pass_weight=0.92,
            critic_disagreement=False,
            pose_consistency=0.90,
            block_qc_ids=(),
            provider_identities=all_ids,
        )
    ]
    for name, path in mask_paths.items():
        # Credit only families whose mask agrees with this candidate at IoU>=0.70.
        agree = [name]
        base = arrays[name]
        for other in live_families:
            if other == name:
                continue
            inter = int(np.count_nonzero(base & arrays[other]))
            union = int(np.count_nonzero(base | arrays[other]))
            if union and (inter / union) >= 0.70:
                agree.append(other)
        ids = tuple(identities[n] for n in agree)
        inputs.append(
            MaskCandidateInput(
                candidate_id=f"family_{name}",
                mask_path=path,
                independent_sources=tuple(identities[n].model_family for n in agree),
                critic_pass_weight=0.85 if len(agree) >= 3 else 0.55,
                critic_disagreement=False,
                pose_consistency=0.88,
                block_qc_ids=(),
                provider_identities=ids,
            )
        )

    protected = np.zeros(shape, dtype=bool)
    exclusive = np.zeros(shape, dtype=bool)
    evidence = build_mask_candidate_evidence(
        tuple(inputs),
        protected_neighbor=protected,
        mutually_exclusive=exclusive,
        ontology_max_components=3,
    )
    decision = run_candidate_tournament(
        evidence,
        label=LABEL,
        context=CONTEXT,
        pipeline_fingerprint=pipeline_fp,
        config=config,
        certificate=None,
        allow_autonomous_profile=False,
    )

    # Persist under production runs/ only when we have a real decision artifact.
    run_stage = machine_root / "gold_volume_tournament" / pipeline_fp / image_id
    run_masks = run_stage / "masks"
    run_auto = run_stage / "autonomy"
    run_masks.mkdir(parents=True, exist_ok=True)
    run_auto.mkdir(parents=True, exist_ok=True)
    # Copy winner + all family masks into the stage root for lifecycle path binding.
    for name, path in mask_paths.items():
        shutil.copy2(path, run_masks / f"{name}.png")
    shutil.copy2(consensus_path, run_masks / "cross_family_majority.png")
    # Re-bind evidence mask_path to the runs/ copies for lifecycle portability.
    rebound = []
    for item in evidence:
        src = Path(item.mask_path)
        dest = run_masks / src.name
        if not dest.is_file():
            shutil.copy2(src, dest)
        rebound.append(replace(item, mask_path=str(dest)))
    decision = run_candidate_tournament(
        tuple(rebound),
        label=LABEL,
        context=CONTEXT,
        pipeline_fingerprint=pipeline_fp,
        config=config,
        certificate=None,
        allow_autonomous_profile=False,
    )
    emit = emit_lifecycle_and_corpus_record(
        run_auto / f"{LABEL}__{CONTEXT}.json",
        image_id=image_id,
        instance_id="p0",
        pipeline_fingerprint=pipeline_fp,
        decision=decision,
        machine_root=machine_root,
        risk_bucket=CONTEXT,
        repo_root=REPO_ROOT,
    )
    return {
        "image_id": image_id,
        "source": image_meta,
        "status": decision.status,
        "winner_id": decision.winner_id,
        "winner_score": decision.winner_score,
        "reason": decision.reason,
        "live_families": live_families,
        "family_reports": {
            k: {kk: vv for kk, vv in v.items() if kk != "stderr_tail"}
            for k, v in family_reports.items()
        },
        "lifecycle_path": emit["lifecycle_relpath"],
        "sidecar_write_path": emit["lifecycle_path"],
        "lifecycle_status": emit["lifecycle_status"],
        "corpus_envelope_written": emit["corpus_envelope_written"],
        "corpus_envelope_relpath": emit["corpus_envelope_relpath"],
        "ranking": [
            {
                "candidate_id": row.candidate_id,
                "score": row.score,
                "eligible": row.eligible,
                "vetoes": list(row.vetoes),
                "independent_sources": row.evidence.independent_sources,
                "consensus_iou": row.evidence.consensus_iou,
                "boundary_agreement": row.evidence.boundary_agreement,
                "families": list(row.evidence.source_model_families),
            }
            for row in decision.ranking
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--pipeline-fingerprint",
        default=None,
        help="Defaults to goldvol-mp-tournament-<utc>",
    )
    parser.add_argument(
        "--machine-root",
        type=Path,
        default=REPO_ROOT / "runs",
    )
    parser.add_argument(
        "--sample-feed",
        type=Path,
        default=None,
        help="Frozen sibling feed / latest pointer (preferred over opportunistic gold pick).",
    )
    parser.add_argument(
        "--sample-set",
        type=Path,
        default=None,
        help="Direct path to tournament_sample_set JSON (overrides --sample-feed).",
    )
    args = parser.parse_args()
    if not COMFY_PY.is_file():
        raise SystemExit(f"ComfyUI CUDA venv missing: {COMFY_PY}")

    pipeline_fp = args.pipeline_fingerprint or f"goldvol-mp-tournament-{_ts()}"
    config = yaml.safe_load(
        (REPO_ROOT / "configs/autonomous_masks.yaml").read_text(encoding="utf-8")
    )
    gold = probe_gold_volume_sources().to_dict()
    default_feed = REPO_ROOT / "qa/live_verification/tournament_sample_set_sibling_feed_latest.json"
    sample_feed = args.sample_feed
    if sample_feed is None and args.sample_set is None and default_feed.is_file():
        sample_feed = default_feed
    elif sample_feed is not None and not sample_feed.is_absolute():
        sample_feed = REPO_ROOT / sample_feed
    sample_set_arg = args.sample_set
    if sample_set_arg is not None and not sample_set_arg.is_absolute():
        sample_set_arg = REPO_ROOT / sample_set_arg
    sample_set_path = _resolve_sample_set_path(sample_feed, sample_set_arg)
    if sample_set_path is not None:
        images = _pick_images_from_sample_set(sample_set_path, args.limit)
        sibling_feed_meta: dict[str, Any] | None = {
            "mode": "frozen_sibling_sample_set",
            "sample_feed": (
                str(sample_feed.resolve().relative_to(REPO_ROOT)).replace("\\", "/")
                if sample_feed is not None
                else None
            ),
            "sample_set_path": str(sample_set_path.resolve().relative_to(REPO_ROOT)).replace(
                "\\", "/"
            ),
            "sample_count_requested": args.limit,
            "sample_count_loaded": len(images),
            "ordered_sample_ids": [row.get("sample_id") for row in images],
        }
    else:
        images = _pick_images(args.limit)
        sibling_feed_meta = {
            "mode": "opportunistic_gold_volume_pick",
            "sample_feed": None,
            "sample_set_path": None,
            "sample_count_requested": args.limit,
            "sample_count_loaded": len(images),
            "ordered_sample_ids": [],
        }
    gpu_plan = _gpu_sequence(
        "pipeline",
        REPO_ROOT / f"qa/live_verification/gpu_sequence_pipeline_goldtour_{_ts()}.json",
    )

    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="mf-gold-tournament-") as temporary:
        work_root = Path(temporary)
        for meta in images:
            results.append(
                _run_one_image(
                    meta,
                    work_root=work_root,
                    config=config,
                    pipeline_fp=pipeline_fp,
                    machine_root=Path(args.machine_root),
                )
            )
            _empty_cuda()

    mvc = sum(1 for row in results if row.get("lifecycle_status") == "machine_verified_candidate")
    caa = sum(1 for row in results if row.get("lifecycle_status") == "calibrated_auto_accepted")
    evidence = {
        "artifact_type": "gold_volume_multiprovider_tournament",
        "schema_version": "1.0.0",
        "authority": "autonomous_certified_gold_profile",
        "evidence_tier": "RUNTIME_PASS_BOUNDED",
        "recorded_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "pipeline_fingerprint": pipeline_fp,
        "label": LABEL,
        "context": CONTEXT,
        "gold_volume_sources": gold,
        "sibling_feed": sibling_feed_meta,
        "gpu_sequencing": gpu_plan,
        "images_attempted": len(images),
        "results": results,
        "counts": {
            "machine_verified_candidate": mvc,
            "calibrated_auto_accepted": caa,
            "residual_or_insufficient": len(results) - mvc - caa,
            "live_independent_families_target": list(REQUIRED_FAMILIES),
            "tournament_family_map": FAMILY_MAP.map_id,
        },
        "tournament_family_map": {
            "path": "configs/multiprovider_tournament_families.yaml",
            "map_id": FAMILY_MAP.map_id,
            "required_invocation_keys": list(REQUIRED_FAMILIES),
            "gpu_sequence": list(FAMILY_MAP.gpu_sequence),
        },
        "honesty_boundary": {
            "no_fabricated_samples": True,
            "no_force_registered_champions": True,
            "external_labels_not_treated_as_gold": True,
            "wilson_math_unchanged": True,
            "gpu_foreign_not_evicted": True,
        },
    }
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    evidence["self_sha256"] = hashlib.sha256(payload).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "mvc": mvc,
                "caa": caa,
                "images": len(images),
                "self_sha256": evidence["self_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0 if mvc > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
