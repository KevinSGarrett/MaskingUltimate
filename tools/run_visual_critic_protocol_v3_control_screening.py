#!/usr/bin/env python3
"""Run hash-bound protocol-v3 session-agent control screening, never qualification."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import tempfile
import time
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

try:
    from tools import run_visual_critic_calibration as legacy_runner
except ModuleNotFoundError:
    import run_visual_critic_calibration as legacy_runner

from maskfactory.vlm.critic_catalog import canonical_sha256  # noqa: E402
from maskfactory.vlm.critic_protocol_v3 import parse_protocol_v3_description  # noqa: E402
from maskfactory.vlm.critic_protocol_v3_control_screening import (  # noqa: E402
    CONTROL_PROTOCOL_ID,
    CriticProtocolV3ControlScreeningError,
    build_control_description_prompt,
    build_control_judgement_prompt,
    control_registry_sha256,
    control_response_schema,
    derive_control_screening_verdict,
    materialize_control_evidence_board,
    parse_control_screening_response,
    validate_control_screening_execution,
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("internvl", "openai"), required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--runtime-sha256", required=True)
    parser.add_argument("--execution", type=Path, required=True)
    parser.add_argument("--panel-root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--endpoint")
    return parser.parse_args()


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _data_url(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _openai_text(
    endpoint: str, model_id: str, prompt: str, images: list[Path]
) -> tuple[str, float]:
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
        ).encode(),
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
    schema: dict[str, Any] | None,
) -> tuple[str, float, list[int]]:
    if backend == "internvl":
        return legacy_runner._run_internvl(
            model=model,
            tokenizer=tokenizer,
            prompt=prompt,
            images=images,
            max_new_tokens=1536 if schema is not None else 512,
        )
    if not endpoint:
        raise ValueError("OpenAI-compatible endpoint is required")
    if schema is None:
        raw, latency = _openai_text(endpoint, model_id, prompt, images)
        return raw, latency, []
    return (
        *legacy_runner._run_openai(
            endpoint=endpoint, model_id=model_id, prompt=prompt, images=images, schema=schema
        ),
        [],
    )


def _json_object(raw: str) -> Mapping[str, Any]:
    value = raw.strip()
    if value.startswith("```json"):
        value = value[7:]
    elif value.startswith("```"):
        value = value[3:]
    if value.endswith("```"):
        value = value[:-3]
    parsed = json.loads(value.strip())
    if not isinstance(parsed, Mapping):
        raise ValueError("format-repair prior response is not an object")
    return parsed


def _format_repair_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != {"description", "findings"} or not isinstance(value["description"], str):
        raise ValueError("format-repair response fields are invalid")
    findings = value["findings"]
    if not isinstance(findings, Mapping) or not findings:
        raise ValueError("format-repair findings are invalid")
    projection: dict[str, Any] = {"description": value["description"], "findings": {}}
    for dimension, finding in findings.items():
        if (
            not isinstance(dimension, str)
            or not isinstance(finding, Mapping)
            or "severity" not in finding
        ):
            raise ValueError("format-repair finding is invalid")
        projection["findings"][dimension] = (
            {"severity": finding["severity"]} if finding["severity"] == "none" else dict(finding)
        )
    return projection


def _deterministic_transport_repair(raw: str) -> tuple[dict[str, Any], str]:
    """Repair only a terminal JSON delimiter and semantically void ``none`` metadata.

    This is intentionally not a second visual judgement. The sole permitted syntax
    change is one closing brace at end of an otherwise JSON object. The sole
    permitted value change is clearing fields which the response contract says must
    be empty/null when their severity is ``none``. Description, every severity,
    and every non-none finding must survive unchanged through the projection check
    below; anything else remains an abstention.
    """

    if not isinstance(raw, str) or raw != raw.strip() or not raw:
        raise CriticProtocolV3ControlScreeningError("control-screening response is not JSON")
    candidate = raw
    closed_terminal_brace = False
    try:
        prior_response = _json_object(candidate)
    except json.JSONDecodeError as exc:
        if exc.pos != len(candidate):
            raise CriticProtocolV3ControlScreeningError(
                "control-screening response is not JSON"
            ) from exc
        candidate += "}"
        closed_terminal_brace = True
        try:
            prior_response = _json_object(candidate)
        except (TypeError, ValueError, json.JSONDecodeError) as repaired_exc:
            raise CriticProtocolV3ControlScreeningError(
                "control-screening response is not JSON"
            ) from repaired_exc
    except (TypeError, ValueError) as exc:
        raise CriticProtocolV3ControlScreeningError(
            "control-screening response is not JSON"
        ) from exc

    prior_projection = _format_repair_projection(prior_response)
    findings = prior_response["findings"]
    changed_none_metadata = False
    if not isinstance(findings, Mapping):
        raise CriticProtocolV3ControlScreeningError("control-screening findings invalid")
    repaired_response = dict(prior_response)
    repaired_findings = {
        key: dict(value) if isinstance(value, Mapping) else value for key, value in findings.items()
    }
    for finding in repaired_findings.values():
        if not isinstance(finding, dict) or finding.get("severity") != "none":
            continue
        if (
            finding.get("cited_evidence_panels") != []
            or finding.get("localization_xyxy") is not None
        ):
            finding["cited_evidence_panels"] = []
            finding["localization_xyxy"] = None
            changed_none_metadata = True
    if not closed_terminal_brace and not changed_none_metadata:
        raise CriticProtocolV3ControlScreeningError("control-screening response is not repairable")
    repaired_response["findings"] = repaired_findings
    repaired_raw = json.dumps(repaired_response, separators=(",", ":"), sort_keys=True)
    repaired = parse_control_screening_response(repaired_raw)
    if _format_repair_projection(repaired) != prior_projection:
        raise ValueError("format-repair changed response semantics")
    return repaired, repaired_raw


def _parse_with_bounded_format_repair(
    *, raw: str
) -> tuple[dict[str, Any], str | None, float, list[int]]:
    try:
        return parse_control_screening_response(raw), None, 0.0, []
    except CriticProtocolV3ControlScreeningError as exc:
        if not (
            str(exc).startswith("control-screening none finding localizes:")
            or str(exc) == "control-screening response is not JSON"
        ):
            raise
    repaired, repaired_raw = _deterministic_transport_repair(raw)
    return repaired, repaired_raw, 0.0, []


def _abstain(
    case: dict[str, Any],
    reason: str,
    error: Exception | None,
    *,
    description_response: str | None = None,
    judgement_response: str | None = None,
    replay_description_response: str | None = None,
    replay_judgement_response: str | None = None,
    judgement_format_repair_response: str | None = None,
    replay_judgement_format_repair_response: str | None = None,
) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "reference_case_id": case["reference_case_id"],
        "schema_valid": False,
        "deterministic_replay": False,
        "description_response": description_response,
        "judgement_response": judgement_response,
        "replay_description_response": replay_description_response,
        "replay_judgement_response": replay_judgement_response,
        "judgement_format_repair_response": judgement_format_repair_response,
        "replay_judgement_format_repair_response": replay_judgement_format_repair_response,
        "latency_ms": 0.0,
        "peak_vram_bytes": legacy_runner._peak_vram_bytes(),
        "screening": {
            "protocol_id": CONTROL_PROTOCOL_ID,
            "screening_outcome": "abstain",
            "reason": reason,
            "authority_claimed": False,
        },
        "error": None if error is None else str(error),
    }


def _record(
    *,
    case: dict[str, Any],
    panel_root: Path,
    temp_root: Path,
    backend: str,
    model_id: str,
    endpoint: str | None,
    model: Any,
    tokenizer: Any,
) -> dict[str, Any]:
    description_raw = None
    judgement_raw = None
    replay_description_raw = None
    replay_judgement_raw = None
    judgement_format_repair_raw = None
    replay_judgement_format_repair_raw = None
    try:
        candidate = materialize_control_evidence_board(
            side=case["candidate"],
            panel_root=panel_root,
            output_path=temp_root / case["case_id"] / "candidate.png",
        )
        reference = materialize_control_evidence_board(
            side=case["reference"],
            panel_root=panel_root,
            output_path=temp_root / case["case_id"] / "reference.png",
        )
        images = [candidate["path"], reference["path"]]
        description_prompt = build_control_description_prompt(
            label_id=case["label_id"],
            label_scale=case["label_scale"],
            reference_case_id=case["reference_case_id"],
        )
        description_raw, first_latency, first_patches = _run_pass(
            backend=backend,
            model_id=model_id,
            endpoint=endpoint,
            model=model,
            tokenizer=tokenizer,
            prompt=description_prompt,
            images=images,
            schema=None,
        )
        description = parse_protocol_v3_description(description_raw)
        judgement_prompt = build_control_judgement_prompt(
            description=description,
            label_id=case["label_id"],
            label_scale=case["label_scale"],
            reference_case_id=case["reference_case_id"],
        )
        judgement_raw, judgement_latency, judgement_patches = _run_pass(
            backend=backend,
            model_id=model_id,
            endpoint=endpoint,
            model=model,
            tokenizer=tokenizer,
            prompt=judgement_prompt,
            images=images,
            schema=control_response_schema(),
        )
        parsed, judgement_format_repair_raw, judgement_repair_latency, judgement_repair_patches = (
            _parse_with_bounded_format_repair(raw=judgement_raw)
        )
        replay_description_raw, replay_desc_latency, replay_desc_patches = _run_pass(
            backend=backend,
            model_id=model_id,
            endpoint=endpoint,
            model=model,
            tokenizer=tokenizer,
            prompt=description_prompt,
            images=images,
            schema=None,
        )
        replay_description = parse_protocol_v3_description(replay_description_raw)
        replay_prompt = build_control_judgement_prompt(
            description=replay_description,
            label_id=case["label_id"],
            label_scale=case["label_scale"],
            reference_case_id=case["reference_case_id"],
        )
        replay_judgement_raw, replay_judgement_latency, replay_judgement_patches = _run_pass(
            backend=backend,
            model_id=model_id,
            endpoint=endpoint,
            model=model,
            tokenizer=tokenizer,
            prompt=replay_prompt,
            images=images,
            schema=control_response_schema(),
        )
        (
            replay_parsed,
            replay_judgement_format_repair_raw,
            replay_judgement_repair_latency,
            replay_judgement_repair_patches,
        ) = _parse_with_bounded_format_repair(raw=replay_judgement_raw)
        screening = derive_control_screening_verdict(
            response=parsed, geometry_wh=case["candidate"]["geometry_wh"]
        )
        deterministic = (
            description == replay_description
            and json.dumps(parsed, sort_keys=True) == json.dumps(replay_parsed, sort_keys=True)
            and first_patches == replay_desc_patches
            and judgement_patches == replay_judgement_patches
            and judgement_repair_patches == replay_judgement_repair_patches
        )
        return {
            "case_id": case["case_id"],
            "reference_case_id": case["reference_case_id"],
            "candidate_board_sha256": candidate["sha256"],
            "reference_board_sha256": reference["sha256"],
            "description_response": description_raw,
            "judgement_response": judgement_raw,
            "replay_description_response": replay_description_raw,
            "replay_judgement_response": replay_judgement_raw,
            "judgement_format_repair_response": judgement_format_repair_raw,
            "replay_judgement_format_repair_response": replay_judgement_format_repair_raw,
            "format_repair_applied": judgement_format_repair_raw is not None
            or replay_judgement_format_repair_raw is not None,
            "schema_valid": True,
            "deterministic_replay": deterministic,
            "model_input_patch_counts": {
                "description": first_patches,
                "judgement": judgement_patches,
                "judgement_format_repair": judgement_repair_patches,
                "replay_description": replay_desc_patches,
                "replay_judgement": replay_judgement_patches,
                "replay_judgement_format_repair": replay_judgement_repair_patches,
            },
            "latency_ms": first_latency
            + judgement_latency
            + judgement_repair_latency
            + replay_desc_latency
            + replay_judgement_latency
            + replay_judgement_repair_latency,
            "peak_vram_bytes": legacy_runner._peak_vram_bytes(),
            "screening": screening,
            "error": None,
        }
    except Exception as exc:
        return _abstain(
            case,
            "screening_execution_invalid",
            exc,
            description_response=description_raw,
            judgement_response=judgement_raw,
            replay_description_response=replay_description_raw,
            replay_judgement_response=replay_judgement_raw,
            judgement_format_repair_response=judgement_format_repair_raw,
            replay_judgement_format_repair_response=replay_judgement_format_repair_raw,
        )


def main() -> int:
    args = _args()
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite immutable bundle: {args.output}")
    execution = json.loads(args.execution.read_text(encoding="utf-8"))
    registry = yaml.safe_load(args.registry.read_text(encoding="utf-8"))
    validate_control_screening_execution(execution, registry)
    if args.backend == "internvl" and args.model_path is None:
        raise SystemExit("--model-path is required for InternVL")
    if args.backend == "openai" and not args.endpoint:
        raise SystemExit("--endpoint is required for OpenAI-compatible inference")
    model = tokenizer = None
    if args.backend == "internvl":
        model, tokenizer = legacy_runner._load_internvl(args.model_path)
    with tempfile.TemporaryDirectory(prefix="maskfactory-v3-control-screen-") as temporary:
        records = [
            _record(
                case=case,
                panel_root=args.panel_root,
                temp_root=Path(temporary),
                backend=args.backend,
                model_id=args.model_id,
                endpoint=args.endpoint,
                model=model,
                tokenizer=tokenizer,
            )
            for case in execution["cases"]
        ]
    bundle = {
        "schema_version": "1.0.0",
        "artifact_type": "protocol_v3_session_agent_control_screening_bundle",
        "protocol_id": CONTROL_PROTOCOL_ID,
        "protocol_version": registry["protocol_version"],
        "backend": args.backend,
        "model_id": args.model_id,
        "runtime_sha256": args.runtime_sha256,
        "execution_manifest_sha256": execution["execution_manifest_sha256"],
        "registry_sha256": control_registry_sha256(registry),
        "records": records,
        "authority_claimed": False,
        "role_certificate_issuance_allowed": False,
        "strict_visual_authority_allowed": False,
        "gold_or_training_authority_allowed": False,
        "production_authority_allowed": False,
        "calibration_fitting_allowed": False,
        "holdout_role_qualification_allowed": False,
    }
    bundle["bundle_sha256"] = canonical_sha256(bundle)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "records": len(records),
                "abstentions": sum(
                    record["screening"]["screening_outcome"] == "abstain" for record in records
                ),
                "bundle_sha256": bundle["bundle_sha256"],
                "authority_claimed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
