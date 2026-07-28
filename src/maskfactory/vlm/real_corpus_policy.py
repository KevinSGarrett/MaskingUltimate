"""Fail-closed real-source bindings for semantic visual-critic calibration."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from .calibration_corpus import validate_calibration_corpus_files
from .critic_catalog import canonical_sha256

SHA256 = re.compile(r"^[a-f0-9]{64}$")
ALLOWED_AUTHORITIES = frozenset(
    {"external_labeled_reference", "human_anchor_gold", "autonomous_certified_gold"}
)
BINDING_KEYS = frozenset(
    {
        "schema_version",
        "artifact_type",
        "corpus_id",
        "corpus_sha256",
        "reference_library",
        "cases",
        "bindings_sha256",
    }
)
CASE_KEYS = frozenset(
    {
        "case_id",
        "source_family",
        "source_root_id",
        "source_relative_path",
        "source_file_sha256",
        "source_panel_sha256",
        "annotation_relative_paths",
        "annotation_file_sha256s",
        "base_mask_pixel_sha256",
        "source_authority",
        "qualification_scope",
        "upstream_split",
        "real_source_pixels",
        "synthetic",
        "production_draft",
        "qualification_evidence_sha256",
    }
)
REFERENCE_KEYS = frozenset(
    {
        "root_id",
        "inventory_relative_path",
        "inventory_sha256",
        "role",
        "truth_authority",
    }
)


class RealCorpusPolicyError(ValueError):
    """Semantic calibration attempted without exact governed real-source evidence."""


def bindings_sha256(document: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {key: value for key, value in document.items() if key != "bindings_sha256"}
    )


def load_real_corpus_policy(path: Path | str) -> dict[str, Any]:
    try:
        document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RealCorpusPolicyError(f"real corpus policy load failed: {exc}") from exc
    if not isinstance(document, Mapping) or document.get("schema_version") != "1.0.0":
        raise RealCorpusPolicyError("real corpus policy schema is unsupported")
    semantic = document.get("semantic_role_qualification")
    if not isinstance(semantic, Mapping):
        raise RealCorpusPolicyError("semantic role policy is missing")
    required_true = (
        "require_real_source_pixels",
        "require_case_source_bindings",
        "require_reference_library_binding",
    )
    if any(semantic.get(key) is not True for key in required_true):
        raise RealCorpusPolicyError("real semantic source requirement was weakened")
    required_false = (
        "allow_synthetic_positive_controls",
        "allow_draft_package_positive_controls",
        "allow_in_review_package_positive_controls",
        "allow_rejected_positive_controls",
    )
    if any(semantic.get(key) is not False for key in required_false):
        raise RealCorpusPolicyError("invalid semantic positive-control class was enabled")
    if set(semantic.get("allowed_source_authorities") or ()) != ALLOWED_AUTHORITIES:
        raise RealCorpusPolicyError("real semantic source authority set drifted")
    roots = document.get("roots")
    if not isinstance(roots, Mapping) or set(roots) != {"maskedwarehouse", "reference_library"}:
        raise RealCorpusPolicyError("required real corpus roots are incomplete")
    return dict(document)


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise RealCorpusPolicyError(f"{field} must be a SHA-256")
    return value


def _safe_relative(value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise RealCorpusPolicyError(f"{field} is empty")
    normalized = value.replace("\\", "/")
    path = Path(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise RealCorpusPolicyError(f"{field} is unsafe")
    return path


def _resolve_root(
    policy: Mapping[str, Any], root_id: str, overrides: Mapping[str, Path] | None
) -> Path:
    if overrides and root_id in overrides:
        candidates: Sequence[Any] = (overrides[root_id],)
    else:
        roots = policy.get("roots")
        entry = roots.get(root_id) if isinstance(roots, Mapping) else None
        candidates = entry.get("candidates", ()) if isinstance(entry, Mapping) else ()
    for raw in candidates:
        path = Path(raw)
        if path.is_dir():
            return path.resolve()
    raise RealCorpusPolicyError(f"required real corpus root is unavailable: {root_id}")


def _bound_file(root: Path, relative: Any, expected_sha: Any, field: str) -> Path:
    path = (root / _safe_relative(relative, field)).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise RealCorpusPolicyError(f"{field} escapes its declared root") from exc
    if not path.is_file() or path.is_symlink():
        raise RealCorpusPolicyError(f"{field} is missing or not a regular file")
    expected = _sha(expected_sha, field + ".sha256")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise RealCorpusPolicyError(f"{field} hash drifted")
    return path


def validate_real_source_bindings(
    *,
    corpus: Mapping[str, Any],
    corpus_root: Path,
    bindings: Mapping[str, Any],
    policy: Mapping[str, Any],
    root_overrides: Mapping[str, Path] | None = None,
) -> None:
    """Require every semantic case to resolve to real, non-draft, hash-bound inputs."""

    validate_calibration_corpus_files(corpus, corpus_root)
    if set(bindings) != BINDING_KEYS:
        raise RealCorpusPolicyError("real-source binding fields are incomplete or unknown")
    if bindings.get("schema_version") != "1.0.0" or bindings.get("artifact_type") != (
        "visual_critic_real_source_bindings"
    ):
        raise RealCorpusPolicyError("real-source binding schema or artifact type is invalid")
    if bindings.get("corpus_id") != corpus.get("corpus_id") or bindings.get(
        "corpus_sha256"
    ) != corpus.get("corpus_sha256"):
        raise RealCorpusPolicyError("real-source bindings target a different corpus")
    if bindings.get("bindings_sha256") != bindings_sha256(bindings):
        raise RealCorpusPolicyError("real-source binding seal drifted")

    reference = bindings.get("reference_library")
    if not isinstance(reference, Mapping) or set(reference) != REFERENCE_KEYS:
        raise RealCorpusPolicyError("reference-library binding is incomplete")
    if (
        reference.get("root_id") != "reference_library"
        or reference.get("role") != "real_reference_retrieval_benchmark"
        or reference.get("truth_authority") != "none"
    ):
        raise RealCorpusPolicyError("reference-library role or authority drifted")
    reference_root = _resolve_root(policy, "reference_library", root_overrides)
    _bound_file(
        reference_root,
        reference.get("inventory_relative_path"),
        reference.get("inventory_sha256"),
        "reference_library.inventory",
    )

    raw_cases = bindings.get("cases")
    if not isinstance(raw_cases, Sequence) or isinstance(raw_cases, (str, bytes)):
        raise RealCorpusPolicyError("real-source case bindings are missing")
    by_id: dict[str, Mapping[str, Any]] = {}
    for value in raw_cases:
        if not isinstance(value, Mapping) or set(value) != CASE_KEYS:
            raise RealCorpusPolicyError("real-source case fields are incomplete or unknown")
        case_id = value.get("case_id")
        if not isinstance(case_id, str) or not case_id or case_id in by_id:
            raise RealCorpusPolicyError("real-source case IDs are empty or duplicated")
        by_id[case_id] = value
    expected_ids = {str(case["case_id"]) for case in corpus["cases"]}
    if set(by_id) != expected_ids:
        raise RealCorpusPolicyError("real-source bindings do not cover every corpus case")

    maskedwarehouse_root = _resolve_root(policy, "maskedwarehouse", root_overrides)
    for case in corpus["cases"]:
        case_id = str(case["case_id"])
        binding = by_id[case_id]
        if (
            binding.get("source_family") != "maskedwarehouse"
            or binding.get("source_root_id") != "maskedwarehouse"
            or binding.get("source_authority") not in ALLOWED_AUTHORITIES
            or binding.get("qualification_scope") != "semantic_visual_critic_calibration"
            or binding.get("real_source_pixels") is not True
            or binding.get("synthetic") is not False
            or binding.get("production_draft") is not False
        ):
            raise RealCorpusPolicyError(f"{case_id} is not an eligible real semantic control")
        expected_split = "train" if case["partition"] == "calibration" else "test"
        if binding.get("upstream_split") != expected_split:
            raise RealCorpusPolicyError(f"{case_id} crosses its governed upstream split")
        _sha(binding.get("qualification_evidence_sha256"), f"{case_id}.qualification")
        _sha(binding.get("base_mask_pixel_sha256"), f"{case_id}.base_mask")
        source_path = _bound_file(
            maskedwarehouse_root,
            binding.get("source_relative_path"),
            binding.get("source_file_sha256"),
            f"{case_id}.source_file",
        )
        panel_sha = _sha(binding.get("source_panel_sha256"), f"{case_id}.source_panel")
        contract_source = case["target_contract"]["source"]
        contract_panel_sha = (
            contract_source["encoded_sha256"]
            if case["target_contract"]["schema_version"] == "2.0.0"
            else contract_source["sha256"]
        )
        if panel_sha != contract_panel_sha:
            raise RealCorpusPolicyError(f"{case_id} source panel is not bound to the real source")
        annotation_paths = binding.get("annotation_relative_paths")
        annotation_shas = binding.get("annotation_file_sha256s")
        if (
            not isinstance(annotation_paths, Sequence)
            or isinstance(annotation_paths, (str, bytes))
            or not annotation_paths
            or not isinstance(annotation_shas, Sequence)
            or isinstance(annotation_shas, (str, bytes))
            or len(annotation_paths) != len(annotation_shas)
        ):
            raise RealCorpusPolicyError(f"{case_id} annotation bindings are incomplete")
        for index, (relative, sha256) in enumerate(zip(annotation_paths, annotation_shas)):
            _bound_file(
                maskedwarehouse_root,
                relative,
                sha256,
                f"{case_id}.annotation[{index}]",
            )
        if source_path.suffix.casefold() not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise RealCorpusPolicyError(f"{case_id} source is not a supported real image")


def load_bindings(path: Path | str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RealCorpusPolicyError(f"real-source bindings load failed: {exc}") from exc
    if not isinstance(value, Mapping):
        raise RealCorpusPolicyError("real-source bindings must be an object")
    return dict(value)


__all__ = [
    "RealCorpusPolicyError",
    "bindings_sha256",
    "load_bindings",
    "load_real_corpus_policy",
    "validate_real_source_bindings",
]
