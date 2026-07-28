"""STATIC split-dedup strategy receipts for MaskedWarehouse qualification.

Binds Plan/MASKEDWAREHOUSE_SPLIT_DEDUP_STRATEGY.md and proves the algorithm contract
without claiming full-corpus admission or gold authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .external_supervision_dedup import (
    SOURCE_KEYS,
    build_external_split_dedup_evidence,
    find_hamming_pairs,
)
from .external_supervision_evidence import publish_immutable_evidence, seal_payload

ROOT = Path(__file__).resolve().parents[2]
STRATEGY_DOC = ROOT / "Plan" / "MASKEDWAREHOUSE_SPLIT_DEDUP_STRATEGY.md"
DEFAULT_RECEIPT = (
    ROOT / "qa" / "external_supervision" / "shared" / "split_dedup_strategy_receipt.json"
)
PROOF_TIER = "STATIC_PASS"
STRATEGY_ID = "maskedwarehouse_split_dedup_v1_static_deferred_full_corpus"


class SplitDedupStrategyError(ValueError):
    """Split-dedup strategy receipt inputs are invalid or overclaim admission."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reject_admission_claims(document: Mapping[str, Any]) -> None:
    for key in (
        "source_masks_are_gold",
        "gold_authority_granted",
        "holdout_authority_granted",
        "any_source_admitted",
        "admission_ready",
        "full_corpus_materialized",
        "split_dedup_gate_satisfied",
    ):
        if document.get(key) is True:
            raise SplitDedupStrategyError(f"fail-closed: strategy must not claim {key}=true")


def build_split_dedup_strategy_receipt(
    *,
    strategy_doc_path: Path = STRATEGY_DOC,
    project_root: Path = ROOT,
) -> dict[str, Any]:
    """Seal an honest STATIC strategy receipt (not the admission gate)."""

    doc = Path(strategy_doc_path).resolve(strict=True)
    root = Path(project_root).resolve(strict=True)
    try:
        relative = doc.relative_to(root).as_posix()
    except ValueError as exc:
        raise SplitDedupStrategyError("strategy doc must live under project root") from exc
    text = doc.read_text(encoding="utf-8")
    if "never gold" not in text.casefold():
        raise SplitDedupStrategyError("strategy doc must state external masks are never gold")
    if "split_dedup_passed" not in text:
        raise SplitDedupStrategyError("strategy doc must name the admission gate")

    # Tiny algorithm self-check so the receipt binds executable contract, not prose alone.
    pairs = find_hamming_pairs((0, 1, 0xFFFFFFFFFFFFFFFF), threshold=3)
    if pairs != ((0, 1),):
        raise SplitDedupStrategyError("algorithm self-check failed for find_hamming_pairs")

    receipt: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": "external_supervision_split_dedup_strategy_receipt",
        "strategy_id": STRATEGY_ID,
        "proof_tier": PROOF_TIER,
        "gate": "split_dedup_passed",
        "status": "STRATEGY_DEFERRED",
        "source": "all_eligible_external_sources",
        "eligible_sources": list(SOURCE_KEYS),
        "strategy_doc_path": relative,
        "strategy_doc_sha256": _sha256_file(doc),
        "algorithm": {
            "exact_hash": "sha256",
            "perceptual_hash": "dhash64_9x8_bilinear",
            "hamming_threshold": 3,
            "implementation": "src/maskfactory/external_supervision_dedup.py",
            "self_check_pairs": [list(pair) for pair in pairs],
        },
        "full_corpus_materialized": False,
        "split_dedup_gate_satisfied": False,
        "admission_ready": False,
        "any_source_admitted": False,
        "source_masks_are_gold": False,
        "gold_authority_granted": False,
        "holdout_authority_granted": False,
        "deferred_reason": (
            "full ~57k cross-source dHash sealed records not materialized; "
            "disk-preserving STATIC strategy only"
        ),
    }
    _reject_admission_claims(receipt)
    receipt["seal_sha256"] = seal_payload(receipt)
    return receipt


def build_bounded_sample_dedup_probe(
    *,
    manifest_paths: Mapping[str, Path],
    source_roots: Mapping[str, Path],
    hamming_threshold: int = 3,
) -> dict[str, Any]:
    """Run the real dedup builder on a tiny fixture/sample and wrap as STATIC probe.

    The inner evidence may say status=PASS for the sample universe, but the probe
    wrapper refuses admission and full-corpus claims.
    """

    sample = build_external_split_dedup_evidence(
        manifest_paths=manifest_paths,
        source_roots=source_roots,
        hamming_threshold=hamming_threshold,
    )
    probe: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": "external_supervision_split_dedup_sample_probe",
        "proof_tier": PROOF_TIER,
        "strategy_id": STRATEGY_ID,
        "status": "STATIC_SAMPLE_ONLY",
        "source": "all_eligible_external_sources",
        "full_corpus_materialized": False,
        "split_dedup_gate_satisfied": False,
        "admission_ready": False,
        "any_source_admitted": False,
        "source_masks_are_gold": False,
        "sample_record_count": sample["record_count"],
        "sample_split_group_count": sample["split_group_count"],
        "sample_evidence_seal_sha256": sample["seal_sha256"],
        "sample_evidence": sample,
    }
    _reject_admission_claims(probe)
    probe["seal_sha256"] = seal_payload(probe)
    return probe


def publish_split_dedup_strategy_receipt(
    receipt: Mapping[str, Any],
    output_path: Path = DEFAULT_RECEIPT,
) -> str:
    """Publish an immutable strategy receipt (not split_dedup_passed)."""

    if receipt.get("artifact_type") != "external_supervision_split_dedup_strategy_receipt":
        raise SplitDedupStrategyError("wrong artifact_type for strategy receipt")
    if receipt.get("proof_tier") != PROOF_TIER:
        raise SplitDedupStrategyError("strategy receipt proof_tier must be STATIC_PASS")
    _reject_admission_claims(receipt)
    if receipt.get("seal_sha256") != seal_payload(receipt):
        raise SplitDedupStrategyError("strategy receipt seal mismatch")
    return publish_immutable_evidence(receipt, output_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--strategy-doc", type=Path, default=STRATEGY_DOC)
    parser.add_argument("--output", type=Path, default=DEFAULT_RECEIPT)
    args = parser.parse_args(argv)
    receipt = build_split_dedup_strategy_receipt(
        strategy_doc_path=args.strategy_doc,
        project_root=args.project_root,
    )
    file_sha = publish_split_dedup_strategy_receipt(receipt, args.output)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "proof_tier": receipt["proof_tier"],
                "admission_ready": False,
                "output": str(Path(args.output).resolve()),
                "file_sha256": file_sha,
                "seal_sha256": receipt["seal_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PROOF_TIER",
    "STRATEGY_DOC",
    "STRATEGY_ID",
    "SplitDedupStrategyError",
    "build_bounded_sample_dedup_probe",
    "build_split_dedup_strategy_receipt",
    "publish_split_dedup_strategy_receipt",
]
