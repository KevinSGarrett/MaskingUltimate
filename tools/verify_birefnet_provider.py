from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from maskfactory.providers.birefnet_variants import BiRefNetVariantProvider
from maskfactory.providers.contracts import BoxProposal, SilhouetteProvider

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "qa" / "fixtures" / "smoke" / "ultralytics_bus_adults.jpg"
OUTPUT = ROOT / "qa" / "live_verification" / "birefnet_provider_integration_20260714.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    person_box = BoxProposal(
        (49.75, 398.25, 247.625, 905.5),
        0.9,
        "person",
        "adult-bus-left",
    )
    with Image.open(FIXTURE) as image:
        expected_shape = (image.height, image.width)
    records: dict[str, Any] = {}
    for variant in ("birefnet_dynamic", "birefnet_hr", "birefnet_hr_matting"):
        provider = BiRefNetVariantProvider(variant)
        if not isinstance(provider, SilhouetteProvider):
            raise RuntimeError(f"{variant} does not implement SilhouetteProvider")
        started = time.perf_counter()
        proposal = provider.infer_silhouette(FIXTURE, person_box=person_box)
        elapsed = time.perf_counter() - started
        if proposal.mask.shape != expected_shape or proposal.mask.dtype != np.bool_:
            raise RuntimeError(f"{variant} violated strict full-canvas mask contract")
        if not proposal.mask.any() or proposal.mask.all():
            raise RuntimeError(f"{variant} produced a degenerate strict mask")
        records[variant] = {
            "provider_key": proposal.provider.provider_key,
            "model_family": proposal.provider.model_family,
            "source_commit": proposal.provider.source_commit,
            "runtime_fingerprint": proposal.provider.runtime_fingerprint,
            "resolution": provider.resolution or "native_divisible_by_32",
            "strict_mask_shape": list(proposal.mask.shape),
            "strict_mask_dtype": str(proposal.mask.dtype),
            "strict_mask_sha256": hashlib.sha256(
                proposal.mask.astype(np.uint8).tobytes()
            ).hexdigest(),
            "foreground_fraction": float(proposal.mask.mean()),
            "proposal_confidence": proposal.confidence,
            "prompt_fingerprint": proposal.prompt_fingerprint,
            "wall_seconds": round(elapsed, 6),
            "silhouette_contract": True,
        }

    matte_provider = BiRefNetVariantProvider("birefnet_hr_matting")
    started = time.perf_counter()
    matte = matte_provider.infer_matte(FIXTURE, person_box=person_box)
    matte_elapsed = time.perf_counter() - started
    if matte.alpha.shape != expected_shape or matte.alpha.dtype != np.float32:
        raise RuntimeError("HR-matting violated the full-canvas float32 alpha contract")
    fractional_fraction = float(((matte.alpha > 0.001) & (matte.alpha < 0.999)).mean())
    if fractional_fraction <= 0.001:
        raise RuntimeError("HR-matting did not preserve a measurable soft alpha boundary")
    records["birefnet_hr_matting"]["matting"] = {
        "alpha_shape": list(matte.alpha.shape),
        "alpha_dtype": str(matte.alpha.dtype),
        "alpha_min": float(matte.alpha.min()),
        "alpha_max": float(matte.alpha.max()),
        "alpha_sha256": hashlib.sha256(matte.alpha.tobytes()).hexdigest(),
        "fractional_alpha_fraction": fractional_fraction,
        "prompt_fingerprint": matte.prompt_fingerprint,
        "wall_seconds": round(matte_elapsed, 6),
    }

    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "captured_at": datetime.now(UTC).isoformat(),
        "result": "pass",
        "fixture": {
            "path": FIXTURE.relative_to(ROOT).as_posix(),
            "sha256": _sha256(FIXTURE),
            "person_box_xyxy": list(person_box.bbox_xyxy),
            "adult_lane": "adult_nonexplicit_allowed",
        },
        "variants": records,
        "fallback_selection": {
            "active": "birefnet_general",
            "rollback": "birefnet_general",
            "challengers": [
                "birefnet_dynamic",
                "birefnet_hr",
                "birefnet_hr_matting",
            ],
            "challenger_failure_returns_incumbent_identity": True,
            "verified_by": "tests/test_birefnet_variant_provider.py",
        },
        "authority": {
            "lifecycle_state": "installed",
            "shadow_only": True,
            "promotion_claimed": False,
            "may_author_gold": False,
        },
    }
    document["sha256"] = hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(document, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
