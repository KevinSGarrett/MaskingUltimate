"""Admit exact CelebAMask controls through qualification and identity isolation."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from maskfactory.external_supervision_evidence import (
    seal_payload,
    verify_qualification_evidence_bundle,
)

from .celebamask_control_candidates import verify_celebamask_control_candidates
from .celebamask_control_panels import verify_celebamask_control_panel_report
from .celebamask_control_semantic_review import (
    verify_celebamask_control_semantic_review,
)
from .critic_catalog import canonical_sha256

SCHEMA_VERSION = "maskfactory.celebamask_control_admission.v1"
PARTITIONS = ("calibration", "qualification_holdout")
DEFECT_BY_REASON = {
    "protected_region_leakage": "protected_region",
    "material_overfill_or_wrong_scale": "boundary",
    "material_underfill": "missing_area",
}


class CelebAMaskControlAdmissionError(ValueError):
    """An exact control is unqualified, leaked, incomplete, or authority-upgraded."""


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_hq_mapping(path: Path) -> dict[int, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].split() != ["idx", "orig_idx", "orig_file"]:
        raise CelebAMaskControlAdmissionError("CelebA-HQ mapping header is invalid")
    result: dict[int, str] = {}
    for line in lines[1:]:
        values = line.split()
        if len(values) != 3:
            raise CelebAMaskControlAdmissionError("CelebA-HQ mapping row is invalid")
        hq_index, _original_index, original_file = values
        index = int(hq_index)
        if index in result or not original_file.endswith(".jpg"):
            raise CelebAMaskControlAdmissionError("CelebA-HQ mapping identity is invalid")
        result[index] = original_file
    return result


def _parse_identities(path: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        values = line.split()
        if len(values) != 2:
            raise CelebAMaskControlAdmissionError("CelebA identity row is invalid")
        filename, raw_identity = values
        identity = int(raw_identity)
        if filename in result or identity < 1:
            raise CelebAMaskControlAdmissionError("CelebA identity is invalid")
        result[filename] = identity
    if len(result) != 202_599:
        raise CelebAMaskControlAdmissionError("CelebA identity metadata is incomplete")
    return result


def _dedup_by_path(document: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    if (
        document.get("artifact_type") != "external_supervision_split_dedup_evidence"
        or document.get("source") != "all_eligible_external_sources"
        or document.get("status") != "PASS"
        or document.get("seal_sha256") != seal_payload(document)
    ):
        raise CelebAMaskControlAdmissionError("split/dedup evidence is invalid")
    result: dict[str, Mapping[str, Any]] = {}
    for record in document.get("records", []):
        if record.get("source") != "celebamask_hq":
            continue
        relative = record.get("relative_path")
        if not isinstance(relative, str) or relative in result:
            raise CelebAMaskControlAdmissionError("CelebAMask split record is invalid")
        result[relative] = record
    return result


def _assign_partitions(records: list[dict[str, Any]]) -> None:
    """Assign connected identity/split components while balancing control strata."""

    parent = list(range(len(records)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    identity_first: dict[int, int] = {}
    group_first: dict[str, int] = {}
    for index, record in enumerate(records):
        union(index, identity_first.setdefault(record["identity_id"], index))
        union(index, group_first.setdefault(record["split_group_id"], index))
    components: dict[int, list[int]] = defaultdict(list)
    for index in range(len(records)):
        components[find(index)].append(index)
    ordered = sorted(
        components.values(),
        key=lambda members: (
            -len(members),
            canonical_sha256(sorted(records[index]["sample_id"] for index in members)),
        ),
    )
    counts = {partition: Counter() for partition in PARTITIONS}
    for members in ordered:
        features = Counter(
            (records[index]["expected_outcome"], records[index]["canonical_label"])
            for index in members
        )

        def score(partition: str) -> int:
            other = PARTITIONS[1 - PARTITIONS.index(partition)]
            keys = set(counts[partition]) | set(counts[other]) | set(features)
            return sum(
                abs(counts[partition][key] + features[key] - counts[other][key]) for key in keys
            )

        scores = {partition: score(partition) for partition in PARTITIONS}
        if scores[PARTITIONS[0]] == scores[PARTITIONS[1]]:
            component_hash = canonical_sha256(
                sorted(records[index]["sample_id"] for index in members)
            )
            selected = PARTITIONS[int(component_hash[0], 16) % 2]
        else:
            selected = min(PARTITIONS, key=lambda partition: scores[partition])
        counts[selected].update(features)
        for index in members:
            records[index]["partition"] = selected


def build_celebamask_control_admission(
    *,
    candidates: Mapping[str, Any],
    panel_report: Mapping[str, Any],
    panel_root: Path,
    semantic_review: Mapping[str, Any],
    qualification_bundle: Mapping[str, Any],
    split_dedup_evidence: Mapping[str, Any],
    hq_mapping_path: Path,
    identity_path: Path,
    project_root: Path,
) -> dict[str, Any]:
    """Join exact reviews to source qualification, dedup groups, and identities."""

    verify_celebamask_control_candidates(candidates)
    verify_celebamask_control_panel_report(panel_report, panel_root)
    verify_celebamask_control_semantic_review(semantic_review, panel_report)
    verification = verify_qualification_evidence_bundle(
        qualification_bundle,
        source="celebamask_hq",
        project_root=project_root,
    )
    if not verification.passed or verification.bundle_sha256 is None:
        raise CelebAMaskControlAdmissionError("external qualification bundle failed")
    dedup = _dedup_by_path(split_dedup_evidence)
    mapping = _parse_hq_mapping(hq_mapping_path)
    identities = _parse_identities(identity_path)
    candidate_by_id = {record["sample_id"]: record for record in candidates["selected"]}
    panel_by_id = {record["sample_id"]: record for record in panel_report["records"]}

    admitted: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for review in semantic_review["records"]:
        sample_id = review["sample_id"]
        candidate = candidate_by_id.get(sample_id)
        panel = panel_by_id.get(sample_id)
        if candidate is None or panel is None:
            raise CelebAMaskControlAdmissionError("review target is missing")
        relative = candidate["source_relative_path"]
        split = dedup.get(relative)
        if split is None or split.get("source_sha256") != candidate["source_sha256"]:
            raise CelebAMaskControlAdmissionError(f"split binding failed:{sample_id}")
        try:
            hq_index = int(Path(relative).stem)
            original_file = mapping[hq_index]
            identity_id = identities[original_file]
        except (KeyError, ValueError) as exc:
            raise CelebAMaskControlAdmissionError(f"identity binding failed:{sample_id}") from exc
        base = {
            "sample_id": sample_id,
            "source_image_id": candidate["source_image_id"],
            "canonical_label": candidate["canonical_label"],
            "source_relative_path": relative,
            "source_sha256": candidate["source_sha256"],
            "mask_relative_path": candidate["mask_relative_path"],
            "mask_sha256": candidate["mask_sha256"],
            "panel_set_sha256": panel["panel_set_sha256"],
            "panel_sha256s": panel["panel_sha256s"],
            "panel_files": panel["panel_files"],
            "split_group_id": split["split_group_id"],
            "celeba_original_file": original_file,
            "identity_id": identity_id,
            "semantic_review_verdict": review["verdict"],
            "semantic_review_reason": review["reason_code"],
        }
        if review["verdict"] == "abstain":
            excluded.append(
                {
                    **base,
                    "disposition": "excluded_ambiguous_alignment",
                    "critic_corpus_control_eligible": False,
                }
            )
            continue
        if review["verdict"] == "pass":
            expected_outcome, defect_type = "valid_mask", None
        else:
            defect_type = DEFECT_BY_REASON.get(review["reason_code"])
            if defect_type is None:
                raise CelebAMaskControlAdmissionError(f"unclassified negative control:{sample_id}")
            expected_outcome = "known_defect"
        admitted.append(
            {
                **base,
                "expected_outcome": expected_outcome,
                "defect_type": defect_type,
                "critic_corpus_control_eligible": True,
                "critic_role_authority": False,
                "gold_or_production_authority": False,
            }
        )
    _assign_partitions(admitted)
    for partition in PARTITIONS:
        outcomes = {
            record["expected_outcome"] for record in admitted if record["partition"] == partition
        }
        if outcomes != {"valid_mask", "known_defect"}:
            raise CelebAMaskControlAdmissionError(
                f"partition lacks positive or negative controls:{partition}"
            )
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "celebamask_exact_critic_control_admission",
        "input_bindings": {
            "candidate_set_sha256": candidates["self_sha256"],
            "panel_report_sha256": panel_report["self_sha256"],
            "semantic_review_sha256": semantic_review["self_sha256"],
            "qualification_bundle_sha256": verification.bundle_sha256,
            "split_dedup_seal_sha256": split_dedup_evidence["seal_sha256"],
            "hq_mapping_sha256": _sha256_file(hq_mapping_path),
            "identity_metadata_sha256": _sha256_file(identity_path),
            "identity_metadata_md5": hashlib.md5(  # noqa: S324 - upstream identity
                identity_path.read_bytes(), usedforsecurity=False
            ).hexdigest(),
        },
        "partition_policy": {
            "names": list(PARTITIONS),
            "algorithm": "connected_identity_split_group_balanced_v1",
            "identity_disjoint": True,
            "split_group_disjoint": True,
        },
        "admitted_count": len(admitted),
        "admitted_by_outcome": dict(
            sorted(Counter(record["expected_outcome"] for record in admitted).items())
        ),
        "admitted_by_partition": dict(
            sorted(Counter(record["partition"] for record in admitted).items())
        ),
        "excluded_count": len(excluded),
        "records": admitted,
        "excluded_records": excluded,
        "critic_corpus_controls_frozen": True,
        "critic_role_authority_granted": False,
        "gold_or_production_authority_granted": False,
        "claim_limits": [
            "frozen real-image critic controls only",
            "external masks remain non-gold",
            "controls do not qualify any visual model",
            "no certificate or production authority",
        ],
        "next_required_stage": (
            "merge these controls into the frozen real critic corpus and fill "
            "remaining label, defect, domain, and risk strata"
        ),
    }
    document["self_sha256"] = canonical_sha256(document)
    verify_celebamask_control_admission(document)
    return document


def verify_celebamask_control_admission(document: Mapping[str, Any]) -> None:
    """Verify partition isolation, dispositions, and non-authority claims."""

    payload = {key: value for key, value in document.items() if key != "self_sha256"}
    if document.get("self_sha256") != canonical_sha256(payload):
        raise CelebAMaskControlAdmissionError("admission self hash mismatch")
    if (
        document.get("schema_version") != SCHEMA_VERSION
        or document.get("critic_corpus_controls_frozen") is not True
        or document.get("critic_role_authority_granted") is not False
        or document.get("gold_or_production_authority_granted") is not False
    ):
        raise CelebAMaskControlAdmissionError("admission contract or authority drifted")
    records = document.get("records")
    excluded = document.get("excluded_records")
    if not isinstance(records, list) or not isinstance(excluded, list):
        raise CelebAMaskControlAdmissionError("admission records are invalid")
    if document.get("admitted_count") != len(records) or document.get("excluded_count") != len(
        excluded
    ):
        raise CelebAMaskControlAdmissionError("admission counts drifted")
    identity_partitions: dict[int, str] = {}
    group_partitions: dict[str, str] = {}
    for record in records:
        partition = record.get("partition")
        if partition not in PARTITIONS:
            raise CelebAMaskControlAdmissionError("record partition is invalid")
        identity = record.get("identity_id")
        group = record.get("split_group_id")
        if (
            identity_partitions.setdefault(identity, partition) != partition
            or group_partitions.setdefault(group, partition) != partition
        ):
            raise CelebAMaskControlAdmissionError("identity or split group leaked")
        if (
            record.get("critic_corpus_control_eligible") is not True
            or record.get("critic_role_authority") is not False
            or record.get("gold_or_production_authority") is not False
        ):
            raise CelebAMaskControlAdmissionError("record authority drifted")
        outcome = record.get("expected_outcome")
        defect = record.get("defect_type")
        if (outcome == "valid_mask" and defect is not None) or (
            outcome == "known_defect" and defect not in set(DEFECT_BY_REASON.values())
        ):
            raise CelebAMaskControlAdmissionError("control outcome is invalid")
    if any(record.get("critic_corpus_control_eligible") is not False for record in excluded):
        raise CelebAMaskControlAdmissionError("excluded control became eligible")


__all__ = [
    "CelebAMaskControlAdmissionError",
    "build_celebamask_control_admission",
    "verify_celebamask_control_admission",
]
