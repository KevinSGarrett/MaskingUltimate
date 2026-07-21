"""Exact-scope abstention policy for multi-person autonomous certification."""

from __future__ import annotations

from dataclasses import dataclass

from .multi_person_risk import MULTI_PERSON_BUCKETS


@dataclass(frozen=True)
class MultiPersonCertificationScopeResult:
    instance_context: str
    risk_bucket: str
    pipeline_fingerprint: str
    blockers: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.blockers


def evaluate_multi_person_certification_scope(
    *,
    instance_context: str,
    risk_bucket: str,
    assigned_risk_bucket: str,
    pipeline_fingerprint: str,
    evidence_pipeline_fingerprint: str,
    pooling_status: str,
    out_of_distribution: bool,
    distribution_drift: bool,
    critic_disagreement: bool,
    identity_ambiguous: bool,
) -> MultiPersonCertificationScopeResult:
    """Abstain whenever scope, currency, exchangeability, or identity is uncertain."""
    if instance_context not in {"duo", "small_group"}:
        raise ValueError("multi-person certification context must be duo or small_group")
    if risk_bucket not in MULTI_PERSON_BUCKETS:
        raise ValueError(f"unregistered multi-person risk bucket: {risk_bucket}")
    if not pipeline_fingerprint or not evidence_pipeline_fingerprint:
        raise ValueError("multi-person certification fingerprint is empty")
    if pooling_status not in {"exchangeable", "sparse", "nonexchangeable"}:
        raise ValueError("multi-person pooling status is invalid")
    for name, value in (
        ("out_of_distribution", out_of_distribution),
        ("distribution_drift", distribution_drift),
        ("critic_disagreement", critic_disagreement),
        ("identity_ambiguous", identity_ambiguous),
    ):
        if not isinstance(value, bool):
            raise ValueError(f"multi-person scope signal {name} must be boolean")

    blockers = []
    if assigned_risk_bucket != risk_bucket:
        blockers.append("risk_bucket_scope_mismatch")
    if evidence_pipeline_fingerprint != pipeline_fingerprint:
        blockers.append("pipeline_fingerprint_drift")
    if pooling_status != "exchangeable":
        blockers.append(f"pooling_{pooling_status}")
    if out_of_distribution:
        blockers.append("out_of_distribution")
    if distribution_drift:
        blockers.append("distribution_drift")
    if critic_disagreement:
        blockers.append("critic_disagreement")
    if identity_ambiguous:
        blockers.append("identity_ambiguity")
    return MultiPersonCertificationScopeResult(
        instance_context,
        risk_bucket,
        pipeline_fingerprint,
        tuple(blockers),
    )


__all__ = [
    "MultiPersonCertificationScopeResult",
    "evaluate_multi_person_certification_scope",
]
