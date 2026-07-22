"""Strict per-record visual review for reference-only generated person masks."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

import numpy as np
from PIL import Image

from .authority.operational_certificate import canonical_decoded_raster_sha256
from .nude_box_mask_generation import validate_box_prompt_provider_batch
from .nude_reference_mask_hard_qc import validate_reference_person_mask_hard_qc
from .providers.disagreement import binary_mask_sha256
from .qa.panels import render_workhorse_evidence
from .vlm.client import OllamaClient
from .vlm.critic_authority import evaluate_pass_quorum
from .vlm.target_contract import authorize_critic_invocation, validate_target_contract


class NudeReferenceStrictVisualReviewError(ValueError):
    """Visual-review inputs or retained evidence violated the sealed contract."""


@dataclass(frozen=True)
class VisualReviewerIdentity:
    role: str
    model_id: str
    model_family: str
    runtime_fingerprint: str


class VisualReviewer(Protocol):
    identity: VisualReviewerIdentity

    def review(self, *, prompt: str, images: tuple[Path, ...]) -> str: ...


class OllamaVisualReviewer:
    """Adapter over the existing local-only Ollama client."""

    def __init__(self, identity: VisualReviewerIdentity, client: OllamaClient):
        self.identity = identity
        self.client = client

    def review(self, *, prompt: str, images: tuple[Path, ...]) -> str:
        return self.client.generate(
            model=self.identity.model_id,
            prompt=prompt,
            images=images,
            options={"temperature": 0, "seed": 1337, "num_predict": 768, "num_ctx": 32768},
            think=False,
            format_schema=STRICT_VERDICT_SCHEMA,
        )


EVIDENCE_NAMES = (
    "full_context",
    "source_crop",
    "mask",
    "overlay",
    "contour",
    "neighbor_overlap",
)
ALLOWED_PROBLEMS = {
    "wrong_person",
    "boundary_too_loose",
    "boundary_too_tight",
    "includes_background",
    "includes_neighbor_person",
    "missing_visible_person_area",
    "occlusion_error",
    "other",
}
STRICT_VERDICT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "confidence", "observations", "problems", "evidence"],
    "properties": {
        "verdict": {"type": "string", "enum": ["pass", "fail", "uncertain"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "observations": {
            "type": "object",
            "additionalProperties": False,
            "required": list(EVIDENCE_NAMES),
            "properties": {name: {"type": "string", "minLength": 1} for name in EVIDENCE_NAMES},
        },
        "problems": {
            "type": "array",
            "uniqueItems": True,
            "items": {"type": "string", "enum": sorted(ALLOWED_PROBLEMS)},
        },
        "evidence": {"type": "string", "minLength": 1},
    },
}
PROMPT_VERSION = "nude-reference-person-strict-v1"
PROMPT_TEMPLATE = """You are one independent visual critic reviewing ONE generated person mask.
The source image is reference-only and is not pixel truth. Prompt text and NSFW metadata are
weak scene context only and must not be used to infer pixels. Inspect every supplied image in
this exact order: full_context, source_crop, mask, overlay, contour, neighbor_overlap. Decide
whether the binary mask belongs only to PERSON_INDEX and includes the complete visible person
without background or another person. Hard QC already ran, but you may never clear or override
a hard-QC failure. Return exactly the required JSON object. A pass requires no problems.
SAMPLE_ID=<sample_id> PERSON_INDEX=<person_index> SOURCE_SHA256=<source_sha256>
MASK_SHA256=<mask_sha256> HARD_QC_REPORT_SHA256=<hard_qc_report_sha256>
TARGET_CONTRACT=<target_contract>
"""


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _identity(identity: VisualReviewerIdentity) -> dict[str, str]:
    if identity.role not in {"primary_visual_critic", "independent_juror"}:
        raise NudeReferenceStrictVisualReviewError("strict_visual_reviewer_role_invalid")
    if not all((identity.model_id, identity.model_family, identity.runtime_fingerprint)):
        raise NudeReferenceStrictVisualReviewError("strict_visual_reviewer_identity_invalid")
    return {
        "role": identity.role,
        "model_id": identity.model_id,
        "model_family": identity.model_family,
        "runtime_fingerprint": identity.runtime_fingerprint,
    }


def _parse(raw: str) -> tuple[dict[str, Any] | None, str]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None, "response_not_json"
    required = {"verdict", "confidence", "observations", "problems", "evidence"}
    if not isinstance(value, dict) or set(value) != required:
        return None, "response_keys_invalid"
    if value["verdict"] not in {"pass", "fail", "uncertain"}:
        return None, "verdict_invalid"
    confidence = value["confidence"]
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
    ):
        return None, "confidence_invalid"
    observations = value["observations"]
    if (
        not isinstance(observations, dict)
        or set(observations) != set(EVIDENCE_NAMES)
        or any(not isinstance(text, str) or not text.strip() for text in observations.values())
    ):
        return None, "observations_invalid"
    problems = value["problems"]
    if (
        not isinstance(problems, list)
        or len(problems) != len(set(problems))
        or not set(problems) <= ALLOWED_PROBLEMS
    ):
        return None, "problems_invalid"
    if not isinstance(value["evidence"], str) or not value["evidence"].strip():
        return None, "evidence_invalid"
    if value["verdict"] == "pass" and problems:
        return None, "pass_with_problems"
    return value, "valid"


def _review_once(
    reviewer: VisualReviewer, *, prompt: str, images: tuple[Path, ...]
) -> dict[str, Any]:
    identity = _identity(reviewer.identity)
    raw = ""
    error = "no_response"
    for attempt in range(2):
        try:
            raw = reviewer.review(
                prompt=(
                    prompt
                    if attempt == 0
                    else prompt + f"\nPrior output invalid: {error}. JSON only."
                ),
                images=images,
            )
        except Exception as exc:  # a reviewer outage is an abstention, never a pass
            return {
                "reviewer": identity,
                "status": "blocked",
                "verdict": "uncertain",
                "confidence": 0.0,
                "observations": {},
                "problems": [],
                "evidence": f"reviewer_unavailable:{type(exc).__name__}:{exc}",
                "raw_response": raw,
                "raw_response_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            }
        parsed, error = _parse(raw)
        if parsed is not None:
            return {
                "reviewer": identity,
                "status": "complete",
                **parsed,
                "raw_response": raw,
                "raw_response_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            }
    return {
        "reviewer": identity,
        "status": "blocked",
        "verdict": "uncertain",
        "confidence": 0.0,
        "observations": {},
        "problems": [],
        "evidence": f"invalid_response_after_retry:{error}",
        "raw_response": raw,
        "raw_response_sha256": hashlib.sha256(raw.encode()).hexdigest(),
    }


def run_reference_person_strict_visual_review(
    *,
    provider_batch: Mapping[str, Any],
    hard_qc: Mapping[str, Any],
    output_root: Path,
    source_paths: Mapping[str, Path],
    evidence_root: Path,
    reviewers: Sequence[VisualReviewer],
    target_contracts: Mapping[str, Mapping[int, Mapping[str, Any]]],
    critic_catalog: Mapping[str, Any],
    critic_certificates: Sequence[Mapping[str, Any]],
    now: datetime,
    minimum_pass_confidence: float = 0.7,
) -> dict[str, Any]:
    """Review every hard-QA-passing candidate with two independent model families."""

    if not 0.7 <= minimum_pass_confidence <= 1:
        raise NudeReferenceStrictVisualReviewError("strict_visual_confidence_policy_invalid")
    batch = validate_box_prompt_provider_batch(provider_batch, output_root=output_root)
    qc = validate_reference_person_mask_hard_qc(
        hard_qc, provider_batch=batch, output_root=output_root, source_paths=source_paths
    )
    if len(reviewers) != 2:
        raise NudeReferenceStrictVisualReviewError("strict_visual_two_reviewers_required")
    reviewer_ids = [_identity(reviewer.identity) for reviewer in reviewers]
    if {item["role"] for item in reviewer_ids} != {"primary_visual_critic", "independent_juror"}:
        raise NudeReferenceStrictVisualReviewError("strict_visual_roles_incomplete")
    if len({item["model_family"] for item in reviewer_ids}) != 2:
        raise NudeReferenceStrictVisualReviewError("strict_visual_model_families_not_independent")
    quorum = evaluate_pass_quorum(
        critic_certificates,
        critic_catalog,
        now=now,
        deterministic_hard_veto=False,
    )
    if quorum.get("status") != "eligible":
        raise NudeReferenceStrictVisualReviewError(
            f"strict_visual_qualified_quorum_unavailable:{quorum.get('reason')}"
        )
    certificates_by_role = {
        certificate["role_id"]: certificate for certificate in critic_certificates
    }
    for identity in reviewer_ids:
        certificate = certificates_by_role.get(identity["role"])
        if (
            certificate is None
            or certificate["model_id"] != identity["model_id"]
            or certificate["family_id"] != identity["model_family"]
            or certificate["runtime_sha256"] != identity["runtime_fingerprint"]
        ):
            raise NudeReferenceStrictVisualReviewError(
                "strict_visual_reviewer_certificate_mismatch"
            )

    provider_records = {record["sample_id"]: record for record in batch["records"]}
    qc_records = {record["sample_id"]: record for record in qc["records"]}
    output_records = []
    for sample_id in (record["sample_id"] for record in batch["records"]):
        provider_record = provider_records[sample_id]
        qc_record = qc_records[sample_id]
        if qc_record["status"] != "pass":
            output_records.append(
                {
                    "sample_id": sample_id,
                    "source_sha256": provider_record["source_sha256"],
                    "status": "upstream_rejected",
                    "blockers": list(qc_record["blockers"]),
                    "candidate_reports": [],
                }
            )
            continue
        source_path = Path(source_paths[sample_id])
        with Image.open(source_path) as opened:
            source = opened.convert("RGB")
        source_pixels = np.asarray(source)
        source_decoded_sha256 = canonical_decoded_raster_sha256(source_pixels, channel_layout="RGB")
        masks: dict[int, np.ndarray] = {}
        candidates = {int(item["person_index"]): item for item in provider_record["candidates"]}
        for person_index, candidate in candidates.items():
            with Image.open(Path(output_root) / candidate["artifact_relative_path"]) as opened:
                masks[person_index] = np.asarray(opened.convert("L")) != 0
        candidate_reports = []
        for qc_candidate in qc_record["candidate_reports"]:
            person_index = int(qc_candidate["person_index"])
            candidate = candidates[person_index]
            try:
                target_contract = target_contracts[sample_id][person_index]
            except (KeyError, TypeError) as exc:
                raise NudeReferenceStrictVisualReviewError(
                    f"strict_visual_target_contract_missing:{sample_id}:{person_index}"
                ) from exc
            validate_target_contract(target_contract)
            if target_contract.get("schema_version") != "2.0.0":
                raise NudeReferenceStrictVisualReviewError(
                    "strict_visual_target_contract_v2_required"
                )
            if (
                target_contract["source"]["encoded_sha256"] != provider_record["source_sha256"]
                or target_contract["candidate"]["encoded_sha256"] != candidate["artifact_sha256"]
                or target_contract["owner"]["person_index"] != person_index
            ):
                raise NudeReferenceStrictVisualReviewError("strict_visual_target_binding_mismatch")
            authorize_critic_invocation(
                target_contract,
                source_sha256=source_decoded_sha256,
                candidate_mask_sha256=binary_mask_sha256(masks[person_index]),
                source_size=source.size,
            )
            protected = np.zeros_like(masks[person_index], dtype=bool)
            for other_index, other_mask in masks.items():
                if other_index != person_index:
                    protected |= other_mask
            evidence = render_workhorse_evidence(
                source,
                masks[person_index],
                protected,
                Path(evidence_root) / sample_id / f"person_{person_index:03d}",
            )
            evidence_files = [
                {
                    "name": name,
                    "path": path.relative_to(evidence_root).as_posix(),
                    "sha256": _file_sha256(path),
                }
                for name, path in zip(EVIDENCE_NAMES, evidence.images, strict=True)
            ]
            prompt = (
                PROMPT_TEMPLATE.replace("<sample_id>", sample_id)
                .replace("<person_index>", str(person_index))
                .replace("<source_sha256>", provider_record["source_sha256"])
                .replace("<mask_sha256>", candidate["mask_sha256"])
                .replace("<hard_qc_report_sha256>", qc_candidate["report_sha256"])
                .replace(
                    "<target_contract>",
                    json.dumps(target_contract, sort_keys=True, separators=(",", ":")),
                )
            )
            verdicts = [
                _review_once(reviewer, prompt=prompt, images=evidence.images)
                for reviewer in reviewers
            ]
            blocked = any(item["status"] != "complete" for item in verdicts)
            passed = all(
                item["verdict"] == "pass" and item["confidence"] >= minimum_pass_confidence
                for item in verdicts
            )
            status = "blocked" if blocked else "pass" if passed else "fail"
            candidate_body = {
                "person_index": person_index,
                "mask_sha256": candidate["mask_sha256"],
                "hard_qc_report_sha256": qc_candidate["report_sha256"],
                "target_contract_sha256": target_contract["contract_sha256"],
                "prompt_version": PROMPT_VERSION,
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "evidence_files": evidence_files,
                "reviewer_verdicts": verdicts,
                "status": status,
                "production_mask_authority": False,
                "operational_certificate_eligible": False,
            }
            candidate_reports.append(
                {**candidate_body, "report_sha256": _canonical_sha256(candidate_body)}
            )
        blockers = sorted(
            {
                (
                    "STRICT_VISUAL_CRITIC_BLOCKED"
                    if report["status"] == "blocked"
                    else "STRICT_VISUAL_REVIEW_FAILED"
                )
                for report in candidate_reports
                if report["status"] != "pass"
            }
        )
        output_records.append(
            {
                "sample_id": sample_id,
                "source_sha256": provider_record["source_sha256"],
                "status": (
                    "pass"
                    if not blockers
                    else "blocked" if "STRICT_VISUAL_CRITIC_BLOCKED" in blockers else "fail"
                ),
                "blockers": blockers,
                "candidate_reports": candidate_reports,
            }
        )
    counts = Counter(record["status"] for record in output_records)
    body = {
        "schema_version": "maskfactory.nude_reference_person_strict_visual_review.v1",
        "provider_batch_sha256": batch["self_sha256"],
        "hard_qc_sha256": qc["self_sha256"],
        "reviewers": reviewer_ids,
        "critic_catalog_sha256": critic_catalog["sha256"],
        "critic_quorum_sha256": quorum["quorum_sha256"],
        "critic_certificate_sha256s": quorum["certificate_sha256s"],
        "prompt_version": PROMPT_VERSION,
        "prompt_template_sha256": hashlib.sha256(PROMPT_TEMPLATE.encode()).hexdigest(),
        "minimum_pass_confidence": minimum_pass_confidence,
        "record_count": len(output_records),
        "status_counts": dict(sorted(counts.items())),
        "records": output_records,
        "complete_source_mask_overlay_contour_evidence": True,
        "contact_sheet_approval_forbidden": True,
        "hard_qc_may_be_overridden": False,
        "source_images_are_pixel_truth": False,
        "production_mask_authority": False,
        "operational_certificates_issued": False,
    }
    return {**body, "self_sha256": _canonical_sha256(body)}


def validate_reference_person_strict_visual_review(
    document: Mapping[str, Any], *, evidence_root: Path
) -> dict[str, Any]:
    """Validate the sealed review and every retained panel/response hash without rerunning a VLM."""

    if (
        document.get("schema_version")
        != "maskfactory.nude_reference_person_strict_visual_review.v1"
    ):
        raise NudeReferenceStrictVisualReviewError("strict_visual_schema_invalid")
    body = {key: value for key, value in document.items() if key != "self_sha256"}
    if document.get("self_sha256") != _canonical_sha256(body):
        raise NudeReferenceStrictVisualReviewError("strict_visual_hash_mismatch")
    if (
        document.get("contact_sheet_approval_forbidden") is not True
        or document.get("hard_qc_may_be_overridden") is not False
        or document.get("source_images_are_pixel_truth") is not False
        or document.get("production_mask_authority") is not False
        or document.get("operational_certificates_issued") is not False
    ):
        raise NudeReferenceStrictVisualReviewError("strict_visual_authority_invalid")
    if (
        not _is_sha256(document.get("critic_catalog_sha256"))
        or not _is_sha256(document.get("critic_quorum_sha256"))
        or not isinstance(document.get("critic_certificate_sha256s"), list)
        or len(document["critic_certificate_sha256s"]) != 2
        or len(set(document["critic_certificate_sha256s"])) != 2
        or not all(_is_sha256(value) for value in document["critic_certificate_sha256s"])
    ):
        raise NudeReferenceStrictVisualReviewError("strict_visual_quorum_binding_invalid")
    reviewer_ids = document.get("reviewers")
    if (
        not isinstance(reviewer_ids, list)
        or len(reviewer_ids) != 2
        or {item.get("role") for item in reviewer_ids}
        != {"primary_visual_critic", "independent_juror"}
        or len({item.get("model_family") for item in reviewer_ids}) != 2
    ):
        raise NudeReferenceStrictVisualReviewError("strict_visual_reviewers_invalid")
    records = document.get("records")
    if not isinstance(records, list) or len(records) != document.get("record_count"):
        raise NudeReferenceStrictVisualReviewError("strict_visual_records_invalid")
    counts = Counter()
    root = Path(evidence_root).resolve()
    for record in records:
        status = record.get("status")
        if status not in {"pass", "fail", "blocked", "upstream_rejected"}:
            raise NudeReferenceStrictVisualReviewError("strict_visual_record_status_invalid")
        counts[status] += 1
        for report in record.get("candidate_reports", ()):
            report_body = {key: value for key, value in report.items() if key != "report_sha256"}
            if report.get("report_sha256") != _canonical_sha256(report_body):
                raise NudeReferenceStrictVisualReviewError("strict_visual_report_hash_mismatch")
            if (
                report.get("production_mask_authority") is not False
                or report.get("operational_certificate_eligible") is not False
                or not _is_sha256(report.get("target_contract_sha256"))
            ):
                raise NudeReferenceStrictVisualReviewError("strict_visual_report_authority_invalid")
            files = report.get("evidence_files")
            if not isinstance(files, list) or [item.get("name") for item in files] != list(
                EVIDENCE_NAMES
            ):
                raise NudeReferenceStrictVisualReviewError("strict_visual_evidence_set_invalid")
            for item in files:
                path = (root / str(item.get("path") or "")).resolve()
                if path == root or root not in path.parents or not path.is_file():
                    raise NudeReferenceStrictVisualReviewError(
                        "strict_visual_evidence_path_invalid"
                    )
                if _file_sha256(path) != item.get("sha256"):
                    raise NudeReferenceStrictVisualReviewError(
                        "strict_visual_evidence_hash_mismatch"
                    )
            votes = report.get("reviewer_verdicts")
            if not isinstance(votes, list) or len(votes) != 2:
                raise NudeReferenceStrictVisualReviewError("strict_visual_votes_invalid")
            if [vote.get("reviewer") for vote in votes] != reviewer_ids:
                raise NudeReferenceStrictVisualReviewError("strict_visual_vote_identity_mismatch")
            for vote in votes:
                raw = vote.get("raw_response")
                if not isinstance(raw, str) or hashlib.sha256(raw.encode()).hexdigest() != vote.get(
                    "raw_response_sha256"
                ):
                    raise NudeReferenceStrictVisualReviewError(
                        "strict_visual_response_hash_mismatch"
                    )
            blocked = any(vote.get("status") != "complete" for vote in votes)
            passed = all(
                vote.get("verdict") == "pass"
                and float(vote.get("confidence", -1)) >= float(document["minimum_pass_confidence"])
                for vote in votes
            )
            expected = "blocked" if blocked else "pass" if passed else "fail"
            if report.get("status") != expected:
                raise NudeReferenceStrictVisualReviewError("strict_visual_report_status_mismatch")
    if dict(sorted(counts.items())) != document.get("status_counts"):
        raise NudeReferenceStrictVisualReviewError("strict_visual_status_counts_mismatch")
    return dict(document)


def build_reference_strict_visual_stage_receipt(
    *, provider: Mapping[str, Any], visual_review_sha256: str, record: Mapping[str, Any]
) -> dict[str, Any]:
    """Seal one nonterminal strict-visual decision for resumable queue replay."""

    provider_key = provider.get("provider_key") if isinstance(provider, Mapping) else None
    if not isinstance(provider_key, str) or not provider_key:
        raise NudeReferenceStrictVisualReviewError("strict_visual_stage_provider_invalid")
    if not _is_sha256(visual_review_sha256):
        raise NudeReferenceStrictVisualReviewError("strict_visual_stage_review_hash_invalid")
    if not isinstance(record.get("sample_id"), str) or not record["sample_id"]:
        raise NudeReferenceStrictVisualReviewError("strict_visual_stage_sample_id_invalid")
    if not _is_sha256(record.get("source_sha256")):
        raise NudeReferenceStrictVisualReviewError("strict_visual_stage_source_hash_invalid")
    status = record.get("status")
    blockers = record.get("blockers")
    if status not in {"pass", "fail", "blocked", "upstream_rejected"}:
        raise NudeReferenceStrictVisualReviewError("strict_visual_stage_status_invalid")
    if not isinstance(blockers, list) or (status == "pass") == bool(blockers):
        raise NudeReferenceStrictVisualReviewError("strict_visual_stage_blockers_invalid")
    body = {
        "schema_version": "maskfactory.nude_reference_strict_visual_stage.v1",
        "stage": f"reference_person_strict_visual_review:{provider_key}",
        "sample_id": record.get("sample_id"),
        "source_sha256": record.get("source_sha256"),
        "provider": dict(provider),
        "visual_review_sha256": visual_review_sha256,
        "status": status,
        "blockers": list(blockers),
        "candidate_reports": [dict(report) for report in record.get("candidate_reports", ())],
        "authority": "intermediate_strict_visual_evidence",
        "hard_qc_may_be_overridden": False,
        "production_mask_authority": False,
        "operational_certificate_issued": False,
    }
    return {**body, "evidence_sha256": _canonical_sha256(body)}


def validate_reference_strict_visual_stage_receipt(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != "maskfactory.nude_reference_strict_visual_stage.v1":
        raise NudeReferenceStrictVisualReviewError("strict_visual_stage_schema_invalid")
    rebuilt = build_reference_strict_visual_stage_receipt(
        provider=payload.get("provider", {}),
        visual_review_sha256=str(payload.get("visual_review_sha256") or ""),
        record={
            key: payload.get(key)
            for key in ("sample_id", "source_sha256", "status", "blockers", "candidate_reports")
        },
    )
    if dict(payload) != rebuilt:
        raise NudeReferenceStrictVisualReviewError("strict_visual_stage_evidence_drift")
    return rebuilt


__all__ = [
    "NudeReferenceStrictVisualReviewError",
    "OllamaVisualReviewer",
    "VisualReviewerIdentity",
    "build_reference_strict_visual_stage_receipt",
    "run_reference_person_strict_visual_review",
    "validate_reference_person_strict_visual_review",
    "validate_reference_strict_visual_stage_receipt",
]
