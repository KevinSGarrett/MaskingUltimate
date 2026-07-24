#!/usr/bin/env python3
"""Execute one reference-paired, fail-closed critic protocol-v3 calibration run.

This is deliberately separate from the frozen single-board critic runner.  It
loads nothing until its base corpus, real-source bindings, execution overlay,
and protocol registry are exact.  It produces calibration evidence only: no
role certificate, visual authority, gold, or promotion can be issued here.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

try:
    from tools import run_visual_critic_calibration as legacy_runner
except ModuleNotFoundError:  # Direct `python tools/...` execution.
    import run_visual_critic_calibration as legacy_runner

from maskfactory.vlm.critic_catalog import canonical_sha256  # noqa: E402
from maskfactory.vlm.critic_protocol_v3 import (  # noqa: E402
    PROTOCOL_ID,
    CriticProtocolV3Error,
    build_description_prompt,
    build_judgement_prompt,
    derive_protocol_v3_verdict,
    parse_protocol_v3_description,
    parse_protocol_v3_response,
    protocol_registry_sha256,
    protocol_v3_response_schema,
)
from maskfactory.vlm.critic_protocol_v3_execution import (  # noqa: E402
    CriticProtocolV3ExecutionError,
    build_calibration_observations,
    resolve_protocol_v3_execution_cases,
)
from maskfactory.vlm.live_calibration import (  # noqa: E402
    materialize_case_composites,
    validate_live_calibration_inputs,
)
from maskfactory.vlm.real_corpus_policy import (  # noqa: E402
    load_bindings,
    load_real_corpus_policy,
    validate_real_source_bindings,
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", required=True, choices=("internvl", "openai"))
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--runtime-sha256", required=True)
    parser.add_argument("--execution-manifest", type=Path, required=True)
    parser.add_argument("--corpus-manifest", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--source-bindings", type=Path, required=True)
    parser.add_argument(
        "--real-corpus-policy",
        type=Path,
        default=Path("configs/visual_critic_real_corpus.yaml"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--endpoint")
    return parser.parse_args()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _data_url(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _run_openai_text(
    *, endpoint: str, model_id: str, prompt: str, images: list[Path]
) -> tuple[str, float]:
    """Request a text-only first pass; it must later pass the non-verdict parser."""

    content = [{"type": "image_url", "image_url": {"url": _data_url(path)}} for path in images]
    content.append({"type": "text", "text": prompt})
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(
            {
                "model": model_id,
                "messages": [{"role": "user", "content": content}],
                "temperature": 0,
                "seed": 1337,
                "max_tokens": 256,
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=300) as response:
        body = json.load(response)
    return (
        str(body["choices"][0]["message"].get("content") or "").strip(),
        (time.perf_counter() - started) * 1000,
    )


def _run_pass(
    *,
    backend: str,
    model_id: str,
    endpoint: str | None,
    model: Any,
    tokenizer: Any,
    prompt: str,
    images: list[Path],
    is_judgement: bool,
) -> tuple[str, float, list[int]]:
    if backend == "internvl":
        raw, latency, patch_counts = legacy_runner._run_internvl(
            model=model, tokenizer=tokenizer, prompt=prompt, images=images
        )
        return raw, latency, patch_counts
    if endpoint is None:
        raise CriticProtocolV3Error("OpenAI-compatible endpoint is required")
    if not is_judgement:
        raw, latency = _run_openai_text(
            endpoint=endpoint, model_id=model_id, prompt=prompt, images=images
        )
        return raw, latency, []
    raw, latency = legacy_runner._run_openai(
        endpoint=endpoint,
        model_id=model_id,
        prompt=prompt,
        images=images,
        schema=protocol_v3_response_schema(),
    )
    return raw, latency, []


def _abstention(*, reason: str, error: Exception | None = None) -> dict[str, Any]:
    return {
        "protocol_id": PROTOCOL_ID,
        "verdict": "abstain",
        "reason": reason,
        "serious_dimensions": [],
        "minor_dimensions": [],
        "incoherent_localization_dimensions": [],
        "evidence_localization_coherent": False,
        "authority_claimed": False,
        "role_certificate_issuance_allowed": False,
        "error": None if error is None else str(error),
    }


def _case_record(
    *,
    execution_case: dict[str, Any],
    candidate_case: dict[str, Any],
    reference_case: dict[str, Any],
    corpus_root: Path,
    temporary_root: Path,
    backend: str,
    model_id: str,
    endpoint: str | None,
    model: Any,
    tokenizer: Any,
    registry: dict[str, Any],
) -> dict[str, Any]:
    """Run describe->judge twice; any malformed pass becomes a typed abstention."""

    candidate_composites = materialize_case_composites(
        candidate_case, corpus_root, temporary_root / execution_case["case_id"] / "candidate"
    )
    reference_composites = materialize_case_composites(
        reference_case, corpus_root, temporary_root / execution_case["case_id"] / "reference"
    )
    images = [row["path"] for row in candidate_composites + reference_composites]
    panel_layout = {
        "candidate": [
            {"sha256": row["sha256"], "panel_names": row["panel_names"]}
            for row in candidate_composites
        ],
        "reference": [
            {"sha256": row["sha256"], "panel_names": row["panel_names"]}
            for row in reference_composites
        ],
    }
    ordered_images_note = (
        "\nThe candidate evidence-board image(s) appear first; image-disjoint known-good "
        "reference evidence-board image(s) follow in the same panel order."
    )
    description_prompt = (
        build_description_prompt(
            label_id=execution_case["label_id"],
            source_authority_tier=execution_case["source_authority_tier"],
            label_scale=execution_case["label_scale"],
            reference_case_id=execution_case["reference_case_id"],
        )
        + ordered_images_note
    )
    first_description_raw, description_latency, first_patch_counts = _run_pass(
        backend=backend,
        model_id=model_id,
        endpoint=endpoint,
        model=model,
        tokenizer=tokenizer,
        prompt=description_prompt,
        images=images,
        is_judgement=False,
    )
    try:
        first_description = parse_protocol_v3_description(first_description_raw)
    except CriticProtocolV3Error as exc:
        return {
            "case_id": execution_case["case_id"],
            "reference_case_id": execution_case["reference_case_id"],
            "panel_layout": panel_layout,
            "description_prompt_sha256": _sha256(description_prompt),
            "description_response": first_description_raw,
            "description_response_sha256": _sha256(first_description_raw),
            "judgement_response": None,
            "judgement_response_sha256": None,
            "replay_description_response": None,
            "replay_judgement_response": None,
            "schema_valid": False,
            "deterministic_replay": False,
            "model_input_patch_counts": first_patch_counts,
            "latency_ms": description_latency,
            "peak_vram_bytes": legacy_runner._peak_vram_bytes(),
            "verdict": _abstention(reason="first_pass_not_non_verdict_description", error=exc),
        }

    judgement_prompt = (
        build_judgement_prompt(
            description=first_description,
            label_id=execution_case["label_id"],
            source_authority_tier=execution_case["source_authority_tier"],
            label_scale=execution_case["label_scale"],
            reference_case_id=execution_case["reference_case_id"],
            registry=registry,
        )
        + ordered_images_note
    )
    first_judgement_raw, judgement_latency, judgement_patch_counts = _run_pass(
        backend=backend,
        model_id=model_id,
        endpoint=endpoint,
        model=model,
        tokenizer=tokenizer,
        prompt=judgement_prompt,
        images=images,
        is_judgement=True,
    )
    replay_description_raw, replay_description_latency, replay_description_patch_counts = _run_pass(
        backend=backend,
        model_id=model_id,
        endpoint=endpoint,
        model=model,
        tokenizer=tokenizer,
        prompt=description_prompt,
        images=images,
        is_judgement=False,
    )
    try:
        replay_description = parse_protocol_v3_description(replay_description_raw)
        replay_judgement_prompt = (
            build_judgement_prompt(
                description=replay_description,
                label_id=execution_case["label_id"],
                source_authority_tier=execution_case["source_authority_tier"],
                label_scale=execution_case["label_scale"],
                reference_case_id=execution_case["reference_case_id"],
                registry=registry,
            )
            + ordered_images_note
        )
        replay_judgement_raw, replay_judgement_latency, replay_judgement_patch_counts = _run_pass(
            backend=backend,
            model_id=model_id,
            endpoint=endpoint,
            model=model,
            tokenizer=tokenizer,
            prompt=replay_judgement_prompt,
            images=images,
            is_judgement=True,
        )
        first_parsed = parse_protocol_v3_response(first_judgement_raw)
        replay_parsed = parse_protocol_v3_response(replay_judgement_raw)
        first_canonical = json.dumps(first_parsed, sort_keys=True, separators=(",", ":"))
        replay_canonical = json.dumps(replay_parsed, sort_keys=True, separators=(",", ":"))
        verdict = derive_protocol_v3_verdict(
            response=first_parsed,
            registry=registry,
            label_id=execution_case["label_id"],
            source_authority_tier=execution_case["source_authority_tier"],
            label_scale=execution_case["label_scale"],
            target_roi_xyxy=execution_case["target_roi_xyxy"],
        )
        schema_valid = True
        deterministic_replay = (
            first_description == replay_description
            and first_canonical == replay_canonical
            and first_patch_counts == replay_description_patch_counts
            and judgement_patch_counts == replay_judgement_patch_counts
        )
        error = None
    except CriticProtocolV3Error as exc:
        replay_judgement_raw = locals().get("replay_judgement_raw")
        replay_judgement_latency = locals().get("replay_judgement_latency", 0.0)
        replay_judgement_patch_counts = locals().get("replay_judgement_patch_counts", [])
        verdict = _abstention(reason="judgement_or_replay_invalid", error=exc)
        schema_valid = False
        deterministic_replay = False
        error = str(exc)

    return {
        "case_id": execution_case["case_id"],
        "reference_case_id": execution_case["reference_case_id"],
        "panel_layout": panel_layout,
        "description_prompt_sha256": _sha256(description_prompt),
        "judgement_prompt_sha256": _sha256(judgement_prompt),
        "description_response": first_description_raw,
        "description_response_sha256": _sha256(first_description_raw),
        "judgement_response": first_judgement_raw,
        "judgement_response_sha256": _sha256(first_judgement_raw),
        "replay_description_response": replay_description_raw,
        "replay_judgement_response": replay_judgement_raw,
        "schema_valid": schema_valid,
        "deterministic_replay": deterministic_replay,
        "model_input_patch_counts": {
            "description": first_patch_counts,
            "judgement": judgement_patch_counts,
            "replay_description": replay_description_patch_counts,
            "replay_judgement": replay_judgement_patch_counts,
        },
        "latency_ms": description_latency
        + judgement_latency
        + replay_description_latency
        + replay_judgement_latency,
        "peak_vram_bytes": legacy_runner._peak_vram_bytes(),
        "verdict": verdict,
        "error": error,
    }


def main() -> int:
    args = _args()
    corpus = json.loads(args.corpus_manifest.read_text(encoding="utf-8"))
    execution_manifest = json.loads(args.execution_manifest.read_text(encoding="utf-8"))
    registry = yaml.safe_load(args.registry.read_text(encoding="utf-8"))
    validate_live_calibration_inputs(corpus, args.corpus_root)
    validate_real_source_bindings(
        corpus=corpus,
        corpus_root=args.corpus_root,
        bindings=load_bindings(args.source_bindings),
        policy=load_real_corpus_policy(args.real_corpus_policy),
    )
    execution_cases = resolve_protocol_v3_execution_cases(execution_manifest, corpus, registry)
    if args.backend == "internvl" and args.model_path is None:
        raise SystemExit("--model-path is required for InternVL")
    if args.backend == "openai" and not args.endpoint:
        raise SystemExit("--endpoint is required for OpenAI-compatible inference")

    model = tokenizer = None
    if args.backend == "internvl":
        model, tokenizer = legacy_runner._load_internvl(args.model_path)
    corpus_cases = {str(case["case_id"]): case for case in corpus["cases"]}
    records: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="maskfactory-critic-v3-") as temporary:
        temporary_root = Path(temporary)
        for execution_case in execution_cases:
            records.append(
                _case_record(
                    execution_case=execution_case,
                    candidate_case=corpus_cases[execution_case["case_id"]],
                    reference_case=corpus_cases[execution_case["reference_case_id"]],
                    corpus_root=args.corpus_root,
                    temporary_root=temporary_root,
                    backend=args.backend,
                    model_id=args.model_id,
                    endpoint=args.endpoint,
                    model=model,
                    tokenizer=tokenizer,
                    registry=registry,
                )
            )

    derived_results = [
        {
            "case_id": row["case_id"],
            "verdict": row["verdict"]["verdict"],
            "serious_dimensions": row["verdict"]["serious_dimensions"],
            "minor_dimensions": row["verdict"]["minor_dimensions"],
        }
        for row in records
    ]
    try:
        observations = build_calibration_observations(execution_cases, derived_results)
        fit_eligibility = {"status": "calibration_evidence_captured_unsealed", "error": None}
    except CriticProtocolV3ExecutionError as exc:
        observations = []
        fit_eligibility = {"status": "not_fit_eligible", "error": str(exc)}
    bundle = {
        "schema_version": "1.0.0",
        "protocol_id": PROTOCOL_ID,
        "protocol_version": registry["protocol_version"],
        "backend": args.backend,
        "model_id": args.model_id,
        "runtime_sha256": args.runtime_sha256,
        "execution_manifest_sha256": execution_manifest["execution_manifest_sha256"],
        "corpus_sha256": corpus["corpus_sha256"],
        "registry_sha256": protocol_registry_sha256(registry),
        "records": records,
        "calibration_observations": observations,
        "fit_eligibility": fit_eligibility,
        "authority_claimed": False,
        "role_certificate_issuance_allowed": False,
    }
    bundle["bundle_sha256"] = canonical_sha256(bundle)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": fit_eligibility["status"], "records": len(records)}))
    return 0 if fit_eligibility["status"] == "calibration_evidence_captured_unsealed" else 2


if __name__ == "__main__":
    sys.exit(main())
