"""Run one governed box-prompt mask provider over a sealed person catalog batch."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from maskfactory.nude_box_mask_generation import (  # noqa: E402
    Sam2BoxPromptInteractiveSegmenter,
    generate_box_prompt_provider_batch,
)
from maskfactory.nude_reference_mask_hard_qc import (  # noqa: E402
    run_reference_person_mask_hard_qc,
)
from maskfactory.production_runpod_routing import (  # noqa: E402
    require_bounded_sam21_fallback,
)
from maskfactory.providers.contracts import ProviderIdentity  # noqa: E402
from maskfactory.providers.sam31_runtime import OfficialSam31Runtime  # noqa: E402
from maskfactory.providers.sam31_shadow import Sam31InteractiveSegmenter  # noqa: E402
from maskfactory.stages.s07_sam2 import WslSam2Provider  # noqa: E402

SHA256 = re.compile(r"^[a-f0-9]{64}$")
SAM2_SOURCE_COMMIT = "2b90b9f5ceec907a1c18123530e92e794ad901a4"
SAM2_CONFIGS = {
    "sam2.1_hiera_large": "configs/sam2.1/sam2.1_hiera_l.yaml",
    "sam2.1_hiera_base_plus": "configs/sam2.1/sam2.1_hiera_b+.yaml",
}


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _source_paths_from_shard(shard_path: Path) -> dict[str, Path]:
    shard = _load_json(shard_path)
    if shard.get("schema_version") != "maskfactory.nude_batch_shard.v1":
        raise ValueError("source shard schema is invalid")
    body = {key: value for key, value in shard.items() if key != "self_sha256"}
    if shard.get("self_sha256") != _canonical_sha256(body):
        raise ValueError("source shard self hash is stale")
    samples = shard.get("samples")
    if not isinstance(samples, list) or len(samples) != shard.get("sample_count"):
        raise ValueError("source shard sample count is invalid")
    result = {}
    for sample in samples:
        if (
            not isinstance(sample, dict)
            or sample.get("source_role") != "reference_and_tournament_input"
            or sample.get("source_labels") != []
            or sample.get("annotation_ref") is not None
        ):
            raise ValueError("source shard reference-only role drifted")
        sample_id = sample.get("sample_id")
        path = sample.get("source_path_readonly")
        if not isinstance(sample_id, str) or not isinstance(path, str) or sample_id in result:
            raise ValueError("source shard sample identity is invalid")
        result[sample_id] = Path(path)
    return result


def _direct_linux_executor(argv: tuple[str, ...], timeout_seconds: int):
    if tuple(argv[:4]) != ("wsl.exe", "-d", "Ubuntu-22.04", "--"):
        raise ValueError("SAM 3.1 direct executor received an unexpected launcher prefix")
    return subprocess.run(
        argv[4:],
        timeout=timeout_seconds,
        text=True,
        capture_output=True,
        check=False,
    )


def _sam31_provider():
    if os.name == "nt":
        runtime = OfficialSam31Runtime()
    else:
        runtime = OfficialSam31Runtime(
            executor=_direct_linux_executor,
            path_mapper=lambda path: str(Path(path).resolve()),
        )
    return Sam31InteractiveSegmenter(runtime.embed, runtime.refine)


def _sam2_provider(args: argparse.Namespace):
    required = (
        args.sam2_large_checkpoint,
        args.sam2_base_checkpoint,
        args.sam2_python,
        args.sam2_source_root,
        args.sam2_dependency_site,
    )
    if any(value is None for value in required):
        raise ValueError("SAM2 requires both checkpoints, Python, source root, and dependency site")
    if (
        not isinstance(args.runtime_fingerprint, str)
        or SHA256.fullmatch(args.runtime_fingerprint) is None
    ):
        raise ValueError("SAM2 requires an exact 64-hex runtime fingerprint")
    runtime = WslSam2Provider(
        {
            "sam2.1_hiera_large": args.sam2_large_checkpoint,
            "sam2.1_hiera_base_plus": args.sam2_base_checkpoint,
        },
        SAM2_CONFIGS,
        args.output_dir / "_sam2_runtime",
        local_cuda_python=args.sam2_python,
        source_path=args.sam2_source_root,
        dependency_site=args.sam2_dependency_site,
    )
    identity = ProviderIdentity(
        "sam2_1_large_with_base_plus_oom",
        "interactive_segmenter",
        "sam2",
        SAM2_SOURCE_COMMIT,
        args.runtime_fingerprint,
    )
    return Sam2BoxPromptInteractiveSegmenter(runtime, identity)


def _write_json_atomic(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog-batch", type=Path, required=True)
    parser.add_argument("--source-shard", type=Path, required=True)
    parser.add_argument("--provider", choices=("sam2_1", "sam3_1"), required=True)
    parser.add_argument("--execution-platform", choices=("runpod",), required=True)
    parser.add_argument("--allow-bounded-sam21-fallback", action="store_true")
    parser.add_argument("--sam21-fallback-reason")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--hard-qc-json", type=Path)
    parser.add_argument("--sample-id", action="append")
    parser.add_argument("--runtime-fingerprint")
    parser.add_argument("--sam2-large-checkpoint", type=Path)
    parser.add_argument("--sam2-base-checkpoint", type=Path)
    parser.add_argument("--sam2-python", type=Path)
    parser.add_argument("--sam2-source-root", type=Path)
    parser.add_argument("--sam2-dependency-site", type=Path)
    args = parser.parse_args()

    if args.provider == "sam2_1":
        require_bounded_sam21_fallback(
            enabled=args.allow_bounded_sam21_fallback,
            reason=args.sam21_fallback_reason,
        )

    catalog = _load_json(args.catalog_batch)
    source_paths = _source_paths_from_shard(args.source_shard)
    provider = _sam31_provider() if args.provider == "sam3_1" else _sam2_provider(args)
    result = generate_box_prompt_provider_batch(
        catalog_batch=catalog,
        source_paths=source_paths,
        provider=provider,
        output_root=args.output_dir,
        sample_ids=args.sample_id,
    )
    _write_json_atomic(args.output_json, result)
    hard_qc = None
    if args.hard_qc_json is not None:
        hard_qc = run_reference_person_mask_hard_qc(
            result,
            output_root=args.output_dir,
            source_paths=source_paths,
        )
        _write_json_atomic(args.hard_qc_json, hard_qc)
    print(
        json.dumps(
            {
                "status": "complete",
                "provider": result["provider"]["provider_key"],
                "record_count": result["record_count"],
                "candidate_count": result["candidate_count"],
                "status_counts": result["status_counts"],
                "self_sha256": result["self_sha256"],
                "output_json": str(args.output_json.resolve()),
                "hard_qc_status_counts": hard_qc["status_counts"] if hard_qc else None,
                "hard_qc_self_sha256": hard_qc["self_sha256"] if hard_qc else None,
                "hard_qc_json": (
                    str(args.hard_qc_json.resolve()) if args.hard_qc_json is not None else None
                ),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
