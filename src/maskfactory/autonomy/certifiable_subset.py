"""VISUAL_QA_PASS_BOUNDED certifiable-subset input-selection gate.

The visual-QA climb seals a certifiable subset of *external ground-truth* panels
that reached ``VISUAL_QA_PASS_BOUNDED`` under live agent pixel review
(``qa/live_verification/visual_qa_certifiable_subset_climb_*.json``). This module
lets the tournament and the autonomous-gold admission driver *restrict their
input selection* to candidates whose source/mask/panel identity is backed by
that certified subset.

Honesty boundaries (fail-closed):
  * The certifiable subset is external ground truth; it is NEVER MaskFactory gold
    and NEVER a warehouse-admission claim. This gate only filters inputs.
  * The gate NEVER forces, promotes, or force-registers a champion. It can only
    remove (veto/drop) candidates whose identity is not in the certified subset.
  * The gate is additive and default-off; callers must explicitly opt in.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

VISUAL_QA_PASS_BOUNDED = "VISUAL_QA_PASS_BOUNDED"
CERTIFIABLE_SUBSET_ARTIFACT_TYPE = "visual_qa_certifiable_subset_climb"
CERTIFIABLE_SUBSET_GATE_SCHEMA = "1.0.0"
CERTIFIABLE_SUBSET_GATE_ID = "maskfactory-visual-qa-pass-bounded-certifiable-subset-input-gate-v1"
OUTSIDE_SUBSET_VETO = "outside_visual_qa_pass_bounded_subset"

_MATCH_KEY_TO_KIND = {
    "source_sha256": "source",
    "mask_sha256": "mask",
    "panel_sha256": "panel",
}


class CertifiableSubsetError(RuntimeError):
    """The certifiable-subset evidence or gate config cannot support selection."""


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


@dataclass(frozen=True)
class CertifiableSubsetMembership:
    """Immutable VISUAL_QA_PASS_BOUNDED membership over external GT identities."""

    after_tier: str
    verdict: str
    named_panel_count: int
    source_sha256s: frozenset[str]
    mask_sha256s: frozenset[str]
    panel_sha256s: frozenset[str]
    source_masks_are_gold: bool
    gold_claimed: bool
    warehouse_admission_claimed: bool
    self_sha256: str

    @property
    def is_visual_qa_pass_bounded(self) -> bool:
        return self.after_tier == VISUAL_QA_PASS_BOUNDED and self.verdict == "PASS"

    def contains(self, sha256: str, *, kind: str = "source") -> bool:
        if kind == "source":
            return sha256 in self.source_sha256s
        if kind == "mask":
            return sha256 in self.mask_sha256s
        if kind == "panel":
            return sha256 in self.panel_sha256s
        raise CertifiableSubsetError(f"unknown membership match kind: {kind!r}")

    def identities(self, kind: str = "source") -> frozenset[str]:
        return {
            "source": self.source_sha256s,
            "mask": self.mask_sha256s,
            "panel": self.panel_sha256s,
        }[kind]


@dataclass(frozen=True)
class CertifiableSubsetSelection:
    """Result of restricting candidate inputs to the certifiable subset."""

    retained: tuple[str, ...]
    dropped: tuple[str, ...]
    reasons: Mapping[str, str]
    match_kind: str
    membership_sha256: str

    @property
    def any_retained(self) -> bool:
        return bool(self.retained)


def load_certifiable_subset(path: str | Path) -> CertifiableSubsetMembership:
    """Load and seal-verify a VISUAL_QA_PASS_BOUNDED certifiable-subset artifact.

    Fails closed unless the artifact self-seal matches, the external subset
    reached ``VISUAL_QA_PASS_BOUNDED`` under an agent PASS verdict, every named
    panel passed pixel review with matching dimensions, and no gold / warehouse
    admission is claimed for the external labels.
    """
    resolved = Path(path)
    try:
        document = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CertifiableSubsetError(f"certifiable subset artifact unreadable: {exc}") from exc
    if not isinstance(document, dict):
        raise CertifiableSubsetError("certifiable subset artifact is not a mapping")
    if document.get("artifact_type") != CERTIFIABLE_SUBSET_ARTIFACT_TYPE:
        raise CertifiableSubsetError("certifiable subset artifact_type is invalid")

    claimed_seal = document.get("self_sha256")
    if not _is_sha256(claimed_seal):
        raise CertifiableSubsetError("certifiable subset self_sha256 is missing or malformed")
    sealed = {key: value for key, value in document.items() if key != "self_sha256"}
    body = json.dumps(sealed, indent=2, ensure_ascii=False) + "\n"
    if hashlib.sha256(body.encode("utf-8")).hexdigest() != claimed_seal:
        raise CertifiableSubsetError("certifiable subset self-seal mismatch")

    section = document.get("certifiable_subset_external_ground_truth")
    if not isinstance(section, dict):
        raise CertifiableSubsetError("certifiable subset section is missing")
    after_tier = section.get("after_tier")
    verdict = section.get("agent_pixel_review_verdict")
    if after_tier != VISUAL_QA_PASS_BOUNDED:
        raise CertifiableSubsetError("certifiable subset did not reach VISUAL_QA_PASS_BOUNDED")
    if verdict != "PASS":
        raise CertifiableSubsetError("certifiable subset agent pixel-review verdict is not PASS")
    # Honesty: external labels are never gold and grant no warehouse admission.
    if section.get("source_masks_are_gold") is not False:
        raise CertifiableSubsetError("certifiable subset must declare source_masks_are_gold=false")
    if section.get("gold_claimed") is not False:
        raise CertifiableSubsetError("certifiable subset must not claim gold")
    if section.get("warehouse_admission_claimed") is not False:
        raise CertifiableSubsetError("certifiable subset must not claim warehouse admission")

    panels = section.get("named_panels")
    if not isinstance(panels, list) or not panels:
        raise CertifiableSubsetError("certifiable subset has no named panels")
    sources: set[str] = set()
    masks: set[str] = set()
    panel_hashes: set[str] = set()
    for panel in panels:
        if not isinstance(panel, dict):
            raise CertifiableSubsetError("certifiable subset panel is not a mapping")
        if panel.get("agent_pixel_review") != "PASS":
            raise CertifiableSubsetError("certifiable subset panel did not pass pixel review")
        if panel.get("dimension_match") is not True:
            raise CertifiableSubsetError("certifiable subset panel dimensions do not match")
        for field, bucket in (
            ("source_sha256", sources),
            ("mask_sha256", masks),
            ("panel_sha256", panel_hashes),
        ):
            value = panel.get(field)
            if not _is_sha256(value):
                raise CertifiableSubsetError(f"certifiable subset panel {field} is malformed")
            bucket.add(value)

    declared_count = section.get("named_panel_count")
    if declared_count != len(panels):
        raise CertifiableSubsetError("certifiable subset named_panel_count mismatch")

    return CertifiableSubsetMembership(
        after_tier=after_tier,
        verdict=verdict,
        named_panel_count=len(panels),
        source_sha256s=frozenset(sources),
        mask_sha256s=frozenset(masks),
        panel_sha256s=frozenset(panel_hashes),
        source_masks_are_gold=False,
        gold_claimed=False,
        warehouse_admission_claimed=False,
        self_sha256=claimed_seal,
    )


def load_certifiable_subset_gate_config(
    path: str | Path = Path("configs/autonomy_certifiable_subset_gate.yaml"),
) -> dict[str, Any]:
    """Load and validate the default-off certifiable-subset input-gate config."""
    try:
        document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise CertifiableSubsetError(f"certifiable subset gate config unreadable: {exc}") from exc
    if not isinstance(document, dict) or set(document) != {
        "schema_version",
        "gate_id",
        "enabled",
        "evidence_path",
        "require_tier",
        "match_key",
        "apply_to",
        "claim_boundary",
    }:
        raise CertifiableSubsetError("certifiable subset gate config has the wrong contract")
    if document["schema_version"] != CERTIFIABLE_SUBSET_GATE_SCHEMA:
        raise CertifiableSubsetError("certifiable subset gate config schema is invalid")
    if document["gate_id"] != CERTIFIABLE_SUBSET_GATE_ID:
        raise CertifiableSubsetError("certifiable subset gate config id is invalid")
    if not isinstance(document["enabled"], bool):
        raise CertifiableSubsetError("certifiable subset gate enabled flag must be boolean")
    if document["require_tier"] != VISUAL_QA_PASS_BOUNDED:
        raise CertifiableSubsetError(
            "certifiable subset gate require_tier must be the bounded tier"
        )
    if document["match_key"] not in _MATCH_KEY_TO_KIND:
        raise CertifiableSubsetError("certifiable subset gate match_key is invalid")
    apply_to = document["apply_to"]
    if (
        not isinstance(apply_to, dict)
        or set(apply_to) != {"tournament", "autonomous_gold"}
        or any(not isinstance(value, bool) for value in apply_to.values())
    ):
        raise CertifiableSubsetError("certifiable subset gate apply_to is invalid")
    boundary = document["claim_boundary"]
    required_boundary = {
        "restricts_inputs_only": True,
        "never_force_registers_champion": True,
        "never_marks_external_labels_gold": True,
        "default_off": True,
    }
    if not isinstance(boundary, dict) or any(
        boundary.get(flag) is not expected for flag, expected in required_boundary.items()
    ):
        raise CertifiableSubsetError("certifiable subset gate claim_boundary is not honest")
    if not isinstance(document["evidence_path"], str) or not document["evidence_path"].strip():
        raise CertifiableSubsetError("certifiable subset gate evidence_path is empty")
    return document


def match_kind_for(match_key: str) -> str:
    try:
        return _MATCH_KEY_TO_KIND[match_key]
    except KeyError as exc:
        raise CertifiableSubsetError(f"unknown match_key: {match_key!r}") from exc


def select_certifiable_subset_inputs(
    items: Iterable[Mapping[str, Any]],
    *,
    membership: CertifiableSubsetMembership,
    match_kind: str = "source",
    id_field: str = "candidate_id",
    key_field: str = "source_sha256",
) -> CertifiableSubsetSelection:
    """Restrict candidate inputs to the certifiable subset (never reorders/promotes).

    Retains only items whose ``key_field`` identity is a member of the subset;
    every other item is dropped with a fail-closed reason. A missing/malformed
    identity is dropped (never silently retained).
    """
    if not membership.is_visual_qa_pass_bounded:
        raise CertifiableSubsetError("membership is not at VISUAL_QA_PASS_BOUNDED")
    if not membership.identities(match_kind):
        raise CertifiableSubsetError("certifiable subset membership is empty; refusing to select")
    retained: list[str] = []
    dropped: list[str] = []
    reasons: dict[str, str] = {}
    seen: set[str] = set()
    for item in items:
        identifier = item.get(id_field)
        if not isinstance(identifier, str) or not identifier:
            raise CertifiableSubsetError(f"input is missing a string {id_field}")
        if identifier in seen:
            raise CertifiableSubsetError(f"duplicate input id: {identifier}")
        seen.add(identifier)
        key = item.get(key_field)
        if not _is_sha256(key):
            dropped.append(identifier)
            reasons[identifier] = f"missing_or_malformed_{key_field}"
            continue
        if membership.contains(key, kind=match_kind):
            retained.append(identifier)
        else:
            dropped.append(identifier)
            reasons[identifier] = OUTSIDE_SUBSET_VETO
    return CertifiableSubsetSelection(
        retained=tuple(retained),
        dropped=tuple(dropped),
        reasons=reasons,
        match_kind=match_kind,
        membership_sha256=membership.self_sha256,
    )


def certifiable_subset_candidate_vetoes(
    candidate_source_index: Mapping[str, str],
    membership: CertifiableSubsetMembership,
    *,
    match_kind: str = "source",
) -> dict[str, tuple[str, ...]]:
    """Map candidate_id -> veto tuple for candidates outside the certified subset.

    Candidates whose identity is unknown or not in the subset receive the
    ``outside_visual_qa_pass_bounded_subset`` veto (fail-closed). Candidates in
    the subset receive an empty tuple. This only removes candidates; it never
    ranks, promotes, or force-registers a champion.
    """
    if not membership.is_visual_qa_pass_bounded:
        raise CertifiableSubsetError("membership is not at VISUAL_QA_PASS_BOUNDED")
    if not membership.identities(match_kind):
        raise CertifiableSubsetError("certifiable subset membership is empty; refusing to gate")
    vetoes: dict[str, tuple[str, ...]] = {}
    for candidate_id, identity in candidate_source_index.items():
        if _is_sha256(identity) and membership.contains(identity, kind=match_kind):
            vetoes[candidate_id] = ()
        else:
            vetoes[candidate_id] = (OUTSIDE_SUBSET_VETO,)
    return vetoes


__all__ = [
    "CERTIFIABLE_SUBSET_ARTIFACT_TYPE",
    "CERTIFIABLE_SUBSET_GATE_ID",
    "CERTIFIABLE_SUBSET_GATE_SCHEMA",
    "CertifiableSubsetError",
    "CertifiableSubsetMembership",
    "CertifiableSubsetSelection",
    "OUTSIDE_SUBSET_VETO",
    "VISUAL_QA_PASS_BOUNDED",
    "certifiable_subset_candidate_vetoes",
    "load_certifiable_subset",
    "load_certifiable_subset_gate_config",
    "match_kind_for",
    "select_certifiable_subset_inputs",
]
