#!/usr/bin/env python3
"""Run one exact self-hosted critic against the frozen positive/negative corpus."""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from maskfactory.vlm.critic_catalog import load_catalog
from maskfactory.vlm.critic_qualification import evaluate_critic_qualification
from maskfactory.vlm.live_calibration import (
    LiveCalibrationError,
    build_case_prompt,
    build_prediction,
    build_qualification_evidence,
    critic_response_schema,
    materialize_case_composites,
    parse_critic_response,
    validate_live_calibration_inputs,
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", required=True, choices=("internvl", "openai"))
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--runtime-sha256", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=Path("configs/visual_critic_catalog.yaml"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--endpoint")
    return parser.parse_args()


def _canonical_response(
    raw: str, case: dict[str, Any], taxonomy: list[str]
) -> tuple[str, dict[str, Any] | None]:
    try:
        parsed = parse_critic_response(raw, case, taxonomy)
    except LiveCalibrationError:
        return raw, None
    return json.dumps(parsed, sort_keys=True, separators=(",", ":")), parsed


def _peak_vram_bytes() -> int:
    try:
        text = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-compute-apps=used_memory",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=10,
        )
        return sum(int(row.strip()) for row in text.splitlines() if row.strip()) * 1024 * 1024
    except (OSError, subprocess.SubprocessError, ValueError):
        return 0


def _data_url(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _run_openai(
    *, endpoint: str, model_id: str, prompt: str, images: list[Path], schema: dict[str, Any]
) -> tuple[str, float]:
    content = [{"type": "image_url", "image_url": {"url": _data_url(path)}} for path in images]
    content.append({"type": "text", "text": prompt})
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
        "seed": 1337,
        "max_tokens": 256,
        "response_format": {"type": "json_schema", "json_schema": schema},
    }
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=300) as response:
        body = json.load(response)
    latency_ms = (time.perf_counter() - started) * 1000
    return str(body["choices"][0]["message"].get("content") or "").strip(), latency_ms


def _internvl_transform(image: Image.Image) -> Any:
    import torch
    from torchvision import transforms

    transform = transforms.Compose(
        [
            transforms.Lambda(lambda value: value.convert("RGB")),
            transforms.Lambda(
                lambda value: ImageOps.pad(
                    value,
                    (448, 448),
                    method=Image.Resampling.BICUBIC,
                    color=(0, 0, 0),
                )
            ),
            transforms.ToTensor(),
            transforms.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
        ]
    )
    return transform(image).to(dtype=torch.bfloat16)


def _load_internvl(model_path: Path) -> tuple[Any, Any]:
    import torch
    from transformers import AutoModel, AutoTokenizer

    torch.manual_seed(1337)
    torch.cuda.manual_seed_all(1337)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    model = (
        AutoModel.from_pretrained(
            str(model_path),
            torch_dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
            use_flash_attn=False,
            trust_remote_code=True,
        )
        .eval()
        .cuda()
    )
    tokenizer = AutoTokenizer.from_pretrained(
        str(model_path), trust_remote_code=True, use_fast=False
    )
    return model, tokenizer


def _run_internvl(
    *, model: Any, tokenizer: Any, prompt: str, images: list[Path]
) -> tuple[str, float]:
    import torch

    tensors = []
    for path in images:
        with Image.open(path) as image:
            tensors.append(_internvl_transform(image))
    pixel_values = torch.stack(tensors).cuda()
    image_prefix = "\n".join(f"Image-{index}: <image>" for index in range(1, 4))
    started = time.perf_counter()
    response = model.chat(
        tokenizer,
        pixel_values,
        image_prefix + "\n" + prompt,
        {"max_new_tokens": 256, "do_sample": False},
        num_patches_list=[1, 1, 1],
    )
    torch.cuda.synchronize()
    return str(response).strip(), (time.perf_counter() - started) * 1000


def main() -> int:
    args = _args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    validate_live_calibration_inputs(manifest, args.corpus_root)
    catalog = load_catalog(args.catalog)
    taxonomy = list(manifest["defect_taxonomy"])
    if args.backend == "internvl" and args.model_path is None:
        raise SystemExit("--model-path is required for InternVL")
    if args.backend == "openai" and not args.endpoint:
        raise SystemExit("--endpoint is required for OpenAI-compatible inference")

    model = tokenizer = None
    if args.backend == "internvl":
        model, tokenizer = _load_internvl(args.model_path)

    predictions = []
    input_rows = []
    with tempfile.TemporaryDirectory(prefix="maskfactory-critic-calibration-") as temporary:
        input_root = Path(temporary)
        for case in manifest["cases"]:
            composites = materialize_case_composites(case, args.corpus_root, input_root)
            image_paths = [row["path"] for row in composites]
            prompt = build_case_prompt(case, taxonomy)
            schema = critic_response_schema(case, taxonomy)
            if args.backend == "internvl":
                first, latency = _run_internvl(
                    model=model, tokenizer=tokenizer, prompt=prompt, images=image_paths
                )
                second, _ = _run_internvl(
                    model=model, tokenizer=tokenizer, prompt=prompt, images=image_paths
                )
            else:
                first, latency = _run_openai(
                    endpoint=args.endpoint,
                    model_id=args.model_id,
                    prompt=prompt,
                    images=image_paths,
                    schema=schema,
                )
                second, _ = _run_openai(
                    endpoint=args.endpoint,
                    model_id=args.model_id,
                    prompt=prompt,
                    images=image_paths,
                    schema=schema,
                )
            first_canonical, parsed = _canonical_response(first, case, taxonomy)
            second_canonical, _ = _canonical_response(second, case, taxonomy)
            predictions.append(
                build_prediction(
                    case=case,
                    parsed=parsed,
                    raw_response=first_canonical,
                    replay_response=second_canonical,
                    latency_ms=latency,
                    peak_vram_bytes=_peak_vram_bytes(),
                )
            )
            input_rows.append(
                {
                    "case_id": case["case_id"],
                    "panel_set_sha256": case["panel_set_sha256"],
                    "composites": [
                        {
                            "index": row["index"],
                            "panel_names": row["panel_names"],
                            "sha256": row["sha256"],
                            "bytes": row["bytes"],
                        }
                        for row in composites
                    ],
                }
            )

    evidence = build_qualification_evidence(
        corpus=manifest,
        catalog=catalog,
        role_id=args.role,
        model_id=args.model_id,
        runtime_sha256=args.runtime_sha256,
        predictions=predictions,
    )
    evidence.pop("evidence_sha256")
    report = evaluate_critic_qualification(evidence, manifest, catalog)
    bundle = {
        "schema_version": "1.0.0",
        "backend": args.backend,
        "inputs": input_rows,
        "evidence": evidence,
        "report": report,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "failures": report["failures"]}))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    sys.exit(main())
