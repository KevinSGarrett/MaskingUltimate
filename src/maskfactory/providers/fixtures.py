"""Raw external-provider fixture runs and comparison panels (MF-P0-12)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FIXTURES = ROOT / "qa" / "fixtures" / "external"
DEFAULT_OUTPUT = ROOT / "work" / "external_probe" / "fixture_runs"
IMAGE_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png", ".ppm", ".webp"}
PANEL_MODALITIES = ("silhouette", "parsing", "pose", "densepose", "sam2_proposal")


@dataclass(frozen=True)
class ProviderResult:
    provider: str
    version: str
    source_url: str
    role: str
    outputs: dict[str, np.ndarray]


class FixtureRunner(Protocol):
    def run(self, image: np.ndarray) -> ProviderResult: ...


class SelfTestRunner:
    """Deterministic infrastructure self-test; never represents model readiness."""

    def run(self, image: np.ndarray) -> ProviderResult:
        height, width = image.shape[:2]
        luminance = image.astype(np.float32).mean(axis=2)
        silhouette = (luminance > float(luminance.mean())).astype(np.uint8) * 255
        parsing = np.digitize(luminance, [64, 128, 192]).astype(np.uint8)
        pose = np.zeros((height, width, 3), dtype=np.uint8)
        pose[:, width // 2] = (0, 255, 0)
        pose[height // 2, :] = (255, 255, 0)
        x_gradient = np.linspace(0, 255, width, dtype=np.uint8)
        y_gradient = np.linspace(0, 255, height, dtype=np.uint8)[:, None]
        densepose = np.stack(
            [
                np.broadcast_to(x_gradient, (height, width)),
                np.broadcast_to(y_gradient, (height, width)),
                parsing * 60,
            ],
            axis=2,
        )
        sam2_proposal = (luminance > np.percentile(luminance, 60)).astype(np.uint8) * 255
        return ProviderResult(
            provider="maskfactory_self_test",
            version="1",
            source_url="internal://maskfactory/providers/fixtures/SelfTestRunner",
            role="infrastructure self-test only; not an external model or mask authority",
            outputs={
                "silhouette": silhouette,
                "parsing": parsing,
                "pose": pose,
                "densepose": densepose,
                "sam2_proposal": sam2_proposal,
            },
        )


def registered_runners() -> list[FixtureRunner]:
    """Return installed production runners; provider wrappers register here later."""
    return []


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_non_gold_output(output_root: Path, project_root: Path) -> None:
    gold_root = (project_root / "data" / "packages").resolve()
    resolved = output_root.resolve()
    if resolved == gold_root or gold_root in resolved.parents:
        raise ValueError("external fixture outputs may never be written under data/packages")


def _validate_output(name: str, array: np.ndarray, source_shape: tuple[int, int]) -> np.ndarray:
    output = np.asarray(array)
    if output.ndim not in {2, 3} or output.shape[:2] != source_shape:
        raise ValueError(
            f"{name}: output shape {output.shape} does not match source {source_shape}"
        )
    if output.dtype == object:
        raise ValueError(f"{name}: object arrays are forbidden")
    return output


def _visualize(array: np.ndarray) -> Image.Image:
    data = np.asarray(array)
    if data.ndim == 2:
        if data.max(initial=0) <= 16:
            scaled = (data.astype(np.float32) / max(float(data.max(initial=1)), 1.0) * 255).astype(
                np.uint8
            )
        else:
            scaled = np.clip(data, 0, 255).astype(np.uint8)
        return Image.fromarray(scaled, mode="L").convert("RGB")
    return Image.fromarray(np.clip(data[..., :3], 0, 255).astype(np.uint8), mode="RGB")


def _disagreement(outputs: dict[str, list[np.ndarray]], shape: tuple[int, int]) -> np.ndarray:
    masks = []
    for modality in ("silhouette", "sam2_proposal"):
        for output in outputs.get(modality, []):
            masks.append(np.asarray(output, dtype=np.float32) / max(float(np.max(output)), 1.0))
    if len(masks) < 2:
        return np.zeros(shape, dtype=np.uint8)
    return (np.std(np.stack(masks), axis=0) * 510).clip(0, 255).astype(np.uint8)


def _panel(source: Image.Image, outputs: dict[str, list[np.ndarray]], destination: Path) -> None:
    disagreement = _disagreement(outputs, (source.height, source.width))
    tiles: list[tuple[str, Image.Image]] = [("source", source.convert("RGB"))]
    for modality in PANEL_MODALITIES:
        values = outputs.get(modality, [])
        tile = _visualize(values[0]) if values else Image.new("RGB", source.size, (30, 30, 30))
        tiles.append((modality, tile))
    tiles.append(("disagreement", _visualize(disagreement)))

    rendered = []
    for label, tile in tiles:
        fitted = ImageOps.contain(tile, (512, 480))
        canvas = Image.new("RGB", (512, 512), "black")
        canvas.paste(fitted, ((512 - fitted.width) // 2, 32 + (480 - fitted.height) // 2))
        ImageDraw.Draw(canvas).text((8, 8), label, fill="white")
        rendered.append(canvas)
    panel = Image.new("RGB", (512 * len(rendered), 512), "black")
    for index, tile in enumerate(rendered):
        panel.paste(tile, (index * 512, 0))
    destination.parent.mkdir(parents=True, exist_ok=True)
    panel.save(  # png-strict: allow -- RGB QA panel, never a gold mask
        destination, format="PNG", optimize=False, compress_level=6
    )


def run_external_fixtures(
    *,
    fixtures_dir: Path = DEFAULT_FIXTURES,
    output_root: Path = DEFAULT_OUTPUT,
    runners: list[FixtureRunner] | None = None,
    project_root: Path = ROOT,
) -> dict:
    """Run providers on fixtures, saving untouched arrays before any visualization."""
    _assert_non_gold_output(output_root, project_root)
    fixture_paths = sorted(
        path
        for path in fixtures_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    if not fixture_paths:
        raise ValueError(f"no fixture images found in {fixtures_dir}")
    active_runners = registered_runners() if runners is None else runners
    manifest = {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "raw_outputs_preserved_before_visualization": True,
        "promoted_to_gold": False,
        "gold_output_forbidden": True,
        "fixture_count": len(fixture_paths),
        "runner_count": len(active_runners),
        "fixtures": [],
    }
    for fixture_path in fixture_paths:
        source_hash = _sha256(fixture_path)
        source = Image.open(fixture_path).convert("RGB")
        image = np.asarray(source)
        fixture_id = f"{fixture_path.stem}_{source_hash[:12]}"
        fixture_root = output_root / fixture_id
        collected: dict[str, list[np.ndarray]] = {}
        provider_records = []
        for runner in active_runners:
            result = runner.run(image.copy())
            provider_root = fixture_root / "raw" / result.provider
            provider_root.mkdir(parents=True, exist_ok=True)
            output_records = []
            for name, raw_output in sorted(result.outputs.items()):
                output = _validate_output(name, raw_output, image.shape[:2])
                output_path = provider_root / f"{name}.npy"
                np.save(  # png-strict: allow -- untouched raw provider array evidence
                    output_path, output, allow_pickle=False
                )
                output_records.append(
                    {
                        "name": name,
                        "path": str(output_path),
                        "sha256": _sha256(output_path),
                        "shape": list(output.shape),
                        "dtype": str(output.dtype),
                    }
                )
                collected.setdefault(name, []).append(output)
            provider_record = {
                "provider": result.provider,
                "version": result.version,
                "source_url": result.source_url,
                "role": result.role,
                "authority": "proposal_only_never_gold",
                "source_image_sha256": source_hash,
                "outputs": output_records,
            }
            metadata_path = provider_root / "provenance.json"
            metadata_path.write_text(
                json.dumps(provider_record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            provider_records.append(provider_record)
        panel_path = fixture_root / "panels" / "provider_comparison.png"
        _panel(source, collected, panel_path)
        manifest["fixtures"].append(
            {
                "fixture_id": fixture_id,
                "source_path": str(fixture_path),
                "source_image_sha256": source_hash,
                "providers": provider_records,
                "panel_path": str(panel_path),
                "panel_sha256": _sha256(panel_path),
            }
        )
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
