"""Closed operational-authority and training-truth lattice.

Access mode is deliberately orthogonal to authority.  Operational exact-output
authority and training truth are separate, non-comparable namespaces.  This
module evaluates one normalized decision without importing bridge wire models,
so the frozen v1 contracts remain byte-immutable.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

DEFAULT_POLICY_PATH = Path("configs/operational_authority_lattice.yaml")
DEFAULT_SCHEMA_PATH = Path("src/maskfactory/schemas/operational_authority_decision.schema.json")

INPUT_FIELDS = frozenset(
    {
        "actor",
        "action",
        "access_mode",
        "artifact_class",
        "authority_namespace",
        "current_operational_authority_state",
        "requested_operational_authority_state",
        "current_training_truth_tier",
        "requested_training_truth_tier",
        "intended_use",
        "input_role",
        "required_minimum_operational_authority_state",
        "parent_operational_authority_states",
        "exact_output_certificate_valid",
        "training_promotion_evidence_valid",
    }
)


class AuthorityLatticeError(ValueError):
    """A closed-world lattice input, policy, or decision is invalid."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def canonical_sha256(value: Any) -> str:
    """Hash MaskFactory canonical JSON v1 bytes."""

    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _exact_keys(value: Mapping[str, Any], expected: set[str] | frozenset[str], code: str) -> None:
    observed = set(value)
    if observed != set(expected):
        missing = sorted(set(expected) - observed)
        extra = sorted(observed - set(expected))
        raise AuthorityLatticeError(code, f"wrong fields; missing={missing}, extra={extra}")


def _require_member(value: Any, allowed: Sequence[str] | set[str], field: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise AuthorityLatticeError(f"unknown_{field}", f"unsupported {field}: {value!r}")
    return value


def _optional_member(value: Any, allowed: Sequence[str] | set[str], field: str) -> str | None:
    if value is None:
        return None
    return _require_member(value, allowed, field)


def load_authority_lattice_policy(
    path: Path = DEFAULT_POLICY_PATH,
) -> dict[str, Any]:
    """Load and independently validate the closed, self-hashed lattice policy."""

    try:
        document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise AuthorityLatticeError("policy_unreadable", str(exc)) from exc
    if not isinstance(document, Mapping):
        raise AuthorityLatticeError("policy_not_mapping", "policy root must be a mapping")
    _validate_policy_document(document)
    return dict(document)


def _validate_policy_document(document: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "policy_id",
        "policy_version",
        "canonicalization",
        "access_modes",
        "actors",
        "actions",
        "input_roles",
        "operational_authority",
        "training_truth",
        "intended_uses",
        "policy_sha256",
    }
    _exact_keys(document, expected, "policy_fields")
    if document["schema_version"] != "1.0.0" or document["policy_version"] != "1.0.0":
        raise AuthorityLatticeError("policy_version", "only lattice policy 1.0.0 is supported")
    if document["policy_id"] != "maskfactory-operational-authority-lattice":
        raise AuthorityLatticeError("policy_id", "unsupported authority-lattice policy")
    if document["canonicalization"] != {
        "algorithm": "maskfactory-canonical-json-v1",
        "excluded_top_level_fields": ["policy_sha256"],
    }:
        raise AuthorityLatticeError("policy_canonicalization", "canonicalization contract drifted")
    unsigned = {key: value for key, value in document.items() if key != "policy_sha256"}
    if document["policy_sha256"] != canonical_sha256(unsigned):
        raise AuthorityLatticeError("policy_hash_mismatch", "policy_sha256 does not match bytes")
    _validate_policy_semantics(document)


def _validate_policy_semantics(policy: Mapping[str, Any]) -> None:
    for field in ("access_modes", "actors", "actions", "input_roles"):
        values = policy[field]
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(value, str) for value in values)
            or len(values) != len(set(values))
        ):
            raise AuthorityLatticeError("policy_closed_set", f"{field} must be a unique list")
    operational = policy["operational_authority"]
    if not isinstance(operational, Mapping):
        raise AuthorityLatticeError("operational_policy", "operational policy must be a mapping")
    _exact_keys(
        operational,
        {"states", "artifact_classes", "producer_actor", "consumer_actor"},
        "operational_policy_fields",
    )
    states = operational["states"]
    if states != {
        "invalid": 0,
        "hypothesis": 1,
        "draft": 2,
        "qa_passed_noncertified": 3,
        "certified": 4,
    }:
        raise AuthorityLatticeError(
            "operational_rank", "operational rank must be the frozen sequence"
        )
    classes = operational["artifact_classes"]
    if not isinstance(classes, Mapping) or not classes:
        raise AuthorityLatticeError(
            "artifact_classes", "artifact classes must be a non-empty mapping"
        )
    for name, entry in classes.items():
        if not isinstance(entry, Mapping):
            raise AuthorityLatticeError("artifact_class_policy", f"invalid class {name}")
        _exact_keys(
            entry,
            {
                "namespace",
                "allowed_states",
                "default_state",
                "descendant",
                "certificate_required_for_certified",
            },
            "artifact_class_policy_fields",
        )
        if entry["namespace"] != "operational_output":
            raise AuthorityLatticeError("artifact_namespace", f"invalid operational class {name}")
        allowed = entry["allowed_states"]
        if not isinstance(allowed, list) or not allowed or not set(allowed) <= set(states):
            raise AuthorityLatticeError("artifact_allowed_states", f"invalid states for {name}")
        if entry["default_state"] not in allowed:
            raise AuthorityLatticeError("artifact_default_state", f"invalid default for {name}")
        if not isinstance(entry["descendant"], bool) or not isinstance(
            entry["certificate_required_for_certified"], bool
        ):
            raise AuthorityLatticeError("artifact_flags", f"invalid flags for {name}")
    if (
        operational["producer_actor"] not in policy["actors"]
        or operational["consumer_actor"] not in policy["actors"]
    ):
        raise AuthorityLatticeError("operational_actors", "producer/consumer actor is not closed")
    training = policy["training_truth"]
    if not isinstance(training, Mapping):
        raise AuthorityLatticeError("training_policy", "training policy must be a mapping")
    _exact_keys(training, {"tiers", "operationally_comparable"}, "training_policy_fields")
    if training["operationally_comparable"] is not False:
        raise AuthorityLatticeError(
            "namespace_comparability", "training truth cannot have an operational rank"
        )
    if not isinstance(training["tiers"], Mapping) or not training["tiers"]:
        raise AuthorityLatticeError("training_tiers", "training tiers must be a non-empty mapping")
    for name, entry in training["tiers"].items():
        if not isinstance(entry, Mapping):
            raise AuthorityLatticeError("training_tier", f"invalid training tier {name}")
        _exact_keys(
            entry,
            {"artifact_class", "assigners", "training_eligible", "holdout_eligible"},
            "training_tier_fields",
        )
        if entry["artifact_class"] != name:
            raise AuthorityLatticeError("training_tier_class", f"tier/class mismatch: {name}")
        if not entry["assigners"] or not set(entry["assigners"]) <= set(policy["actors"]):
            raise AuthorityLatticeError("training_assigners", f"invalid assigners for {name}")
        if not isinstance(entry["training_eligible"], bool) or not isinstance(
            entry["holdout_eligible"], bool
        ):
            raise AuthorityLatticeError("training_flags", f"invalid flags for {name}")
    uses = policy["intended_uses"]
    if not isinstance(uses, Mapping) or not uses:
        raise AuthorityLatticeError("intended_uses", "intended uses must be a non-empty mapping")
    for name, entry in uses.items():
        if not isinstance(entry, Mapping):
            raise AuthorityLatticeError("intended_use", f"invalid intended use {name}")
        _exact_keys(
            entry,
            {"namespace", "minimum_operational_authority_state", "allowed_training_truth_tiers"},
            "intended_use_fields",
        )
        if entry["namespace"] == "operational_output":
            if entry["minimum_operational_authority_state"] not in states:
                raise AuthorityLatticeError("use_floor", f"invalid operational use: {name}")
            if entry["allowed_training_truth_tiers"] != []:
                raise AuthorityLatticeError("use_namespace", f"mixed use namespace: {name}")
        elif entry["namespace"] == "training_truth":
            if entry["minimum_operational_authority_state"] is not None:
                raise AuthorityLatticeError(
                    "use_namespace", f"training use has operational floor: {name}"
                )
            if not set(entry["allowed_training_truth_tiers"]) <= set(training["tiers"]):
                raise AuthorityLatticeError("use_training_tiers", f"invalid training use: {name}")
        else:
            raise AuthorityLatticeError("use_namespace", f"unknown namespace for {name}")


def _normalize_inputs(inputs: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(inputs, Mapping):
        raise AuthorityLatticeError("inputs_not_mapping", "inputs must be a mapping")
    _exact_keys(inputs, INPUT_FIELDS, "input_fields")
    operational = policy["operational_authority"]
    training = policy["training_truth"]
    normalized = {
        "actor": _require_member(inputs["actor"], policy["actors"], "actor"),
        "action": _require_member(inputs["action"], policy["actions"], "action"),
        "access_mode": _require_member(
            inputs["access_mode"], policy["access_modes"], "access_mode"
        ),
        "artifact_class": inputs["artifact_class"],
        "authority_namespace": _require_member(
            inputs["authority_namespace"], {"operational_output", "training_truth"}, "namespace"
        ),
        "current_operational_authority_state": _optional_member(
            inputs["current_operational_authority_state"],
            operational["states"],
            "operational_authority_state",
        ),
        "requested_operational_authority_state": _optional_member(
            inputs["requested_operational_authority_state"],
            operational["states"],
            "operational_authority_state",
        ),
        "current_training_truth_tier": _optional_member(
            inputs["current_training_truth_tier"], training["tiers"], "training_truth_tier"
        ),
        "requested_training_truth_tier": _optional_member(
            inputs["requested_training_truth_tier"], training["tiers"], "training_truth_tier"
        ),
        "intended_use": _require_member(
            inputs["intended_use"], policy["intended_uses"], "intended_use"
        ),
        "input_role": _require_member(inputs["input_role"], policy["input_roles"], "input_role"),
        "required_minimum_operational_authority_state": _optional_member(
            inputs["required_minimum_operational_authority_state"],
            operational["states"],
            "operational_authority_state",
        ),
        "parent_operational_authority_states": inputs["parent_operational_authority_states"],
        "exact_output_certificate_valid": inputs["exact_output_certificate_valid"],
        "training_promotion_evidence_valid": inputs["training_promotion_evidence_valid"],
    }
    if not isinstance(normalized["artifact_class"], str):
        raise AuthorityLatticeError("unknown_artifact_class", "artifact class must be a string")
    if not isinstance(normalized["parent_operational_authority_states"], list):
        raise AuthorityLatticeError("parent_states_type", "parent states must be a list")
    normalized["parent_operational_authority_states"] = [
        _require_member(value, operational["states"], "operational_authority_state")
        for value in normalized["parent_operational_authority_states"]
    ]
    for field in ("exact_output_certificate_valid", "training_promotion_evidence_valid"):
        if not isinstance(normalized[field], bool):
            raise AuthorityLatticeError("boolean_field", f"{field} must be boolean")
    return normalized


def evaluate_authority_lattice(
    inputs: Mapping[str, Any],
    *,
    decision_id: str,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate one total, deterministic, fail-closed authority decision."""

    active = dict(policy) if policy is not None else load_authority_lattice_policy()
    _validate_policy_document(active)
    if not isinstance(decision_id, str) or not decision_id or len(decision_id) > 128:
        raise AuthorityLatticeError("decision_id", "decision_id must be 1..128 characters")
    normalized = _normalize_inputs(inputs, active)
    reasons: list[str] = []
    result = _evaluate_normalized(normalized, active, reasons)
    core = {
        "schema_version": "1.0.0",
        "record_type": "operational_authority_decision",
        "decision_id": decision_id,
        "policy": {
            "policy_id": active["policy_id"],
            "policy_version": active["policy_version"],
            "policy_sha256": active["policy_sha256"],
        },
        "inputs": normalized,
        "result": result,
    }
    decision = {**core, "decision_sha256": canonical_sha256(core)}
    validate_authority_decision(decision, policy=active)
    return decision


def _evaluate_normalized(
    inputs: Mapping[str, Any], policy: Mapping[str, Any], reasons: list[str]
) -> dict[str, Any]:
    namespace = inputs["authority_namespace"]
    actor = inputs["actor"]
    action = inputs["action"]
    use = policy["intended_uses"][inputs["intended_use"]]
    may_mutate = False
    may_use = True
    comparison = "not_applicable"
    effective_operational = inputs["current_operational_authority_state"]
    effective_training = inputs["current_training_truth_tier"]

    if use["namespace"] != namespace:
        reasons.append("use_namespace_mismatch")
        may_use = False

    if namespace == "operational_output":
        classes = policy["operational_authority"]["artifact_classes"]
        artifact_class = inputs["artifact_class"]
        if artifact_class not in classes:
            raise AuthorityLatticeError(
                "unknown_artifact_class", f"unsupported operational class: {artifact_class!r}"
            )
        class_policy = classes[artifact_class]
        if (
            inputs["current_training_truth_tier"] is not None
            or inputs["requested_training_truth_tier"] is not None
        ):
            reasons.append("operational_training_namespace_confusion")
        current = inputs["current_operational_authority_state"]
        requested = inputs["requested_operational_authority_state"]
        if current is None or requested is None:
            reasons.append("operational_state_missing")
        else:
            if current not in class_policy["allowed_states"] and action in {
                "evaluate_use",
                "reject",
            }:
                reasons.append("artifact_class_current_authority_invalid")
            if requested not in class_policy["allowed_states"]:
                reasons.append("artifact_class_authority_exceeded")
        ranks = policy["operational_authority"]["states"]
        if action == "grant_operational_authority":
            if actor != policy["operational_authority"]["producer_actor"]:
                reasons.append("actor_cannot_grant_operational_authority")
            elif (
                current is not None and requested is not None and ranks[requested] < ranks[current]
            ):
                reasons.append("grant_cannot_lower_authority")
            else:
                may_mutate = True
        elif action == "revoke_operational_authority":
            if actor != policy["operational_authority"]["producer_actor"]:
                reasons.append("actor_cannot_revoke_operational_authority")
            elif current is None or requested is None or ranks[requested] >= ranks[current]:
                reasons.append("revocation_must_lower_authority")
            else:
                may_mutate = True
        elif action in {"evaluate_use", "reject"}:
            if requested != current:
                reasons.append("non_mutating_action_changed_authority")
            if action == "reject":
                may_use = False
                reasons.append("consumer_rejected")
        elif action == "derive":
            if not class_policy["descendant"]:
                reasons.append("artifact_class_not_descendant")
            if not inputs["parent_operational_authority_states"]:
                reasons.append("descendant_parent_missing")
            if requested != current:
                if actor != policy["operational_authority"]["producer_actor"]:
                    reasons.append("actor_cannot_grant_operational_authority")
                else:
                    may_mutate = True
        else:
            reasons.append("action_wrong_namespace")

        if requested == "certified" and (
            class_policy["certificate_required_for_certified"]
            and not inputs["exact_output_certificate_valid"]
        ):
            reasons.append("exact_output_certificate_required")
        if class_policy["descendant"]:
            parents = inputs["parent_operational_authority_states"]
            if not parents:
                reasons.append("descendant_parent_missing")
            elif requested is not None and ranks[requested] > min(
                ranks[parent] for parent in parents
            ):
                reasons.append("descendant_authority_above_weakest_parent")
        elif inputs["parent_operational_authority_states"]:
            reasons.append("non_descendant_has_parents")

        if inputs["access_mode"] == "mode_b_live_predict" and requested not in {
            "hypothesis",
            "draft",
            "certified",
        }:
            reasons.append("mode_b_predict_authority_invalid")
        if inputs["access_mode"] == "mode_b_live_refine" and not class_policy["descendant"]:
            reasons.append("mode_b_refine_requires_descendant")
        if inputs["access_mode"] == "none" and inputs["intended_use"] != "training":
            reasons.append("operational_access_mode_missing")

        required = inputs["required_minimum_operational_authority_state"]
        declared_floor = use["minimum_operational_authority_state"]
        effective_floor = max(
            (value for value in (required, declared_floor) if value is not None),
            key=lambda value: ranks[value],
            default=None,
        )
        if effective_floor is not None and requested is not None:
            comparison = (
                "meets_floor" if ranks[requested] >= ranks[effective_floor] else "below_floor"
            )
            if comparison == "below_floor":
                reasons.append("operational_authority_below_required_floor")
        if inputs["input_role"] in {"target", "protected"} and required is None:
            reasons.append("input_role_authority_floor_missing")
        if reasons:
            may_mutate = False
            may_use = False
            effective_operational = current
        elif may_mutate or action == "derive":
            effective_operational = requested
        effective_training = None
    else:
        tiers = policy["training_truth"]["tiers"]
        artifact_class = inputs["artifact_class"]
        if artifact_class not in tiers:
            raise AuthorityLatticeError(
                "unknown_artifact_class", f"unsupported training class: {artifact_class!r}"
            )
        if (
            inputs["current_operational_authority_state"] is not None
            or inputs["requested_operational_authority_state"] is not None
        ):
            reasons.append("training_operational_namespace_confusion")
        if inputs["required_minimum_operational_authority_state"] is not None:
            reasons.append("training_truth_not_operationally_comparable")
        if inputs["parent_operational_authority_states"]:
            reasons.append("training_truth_has_operational_parents")
        if inputs["access_mode"] != "none":
            reasons.append("training_truth_cannot_gain_authority_from_access_mode")
        current_tier = inputs["current_training_truth_tier"]
        requested_tier = inputs["requested_training_truth_tier"]
        if current_tier is None or requested_tier is None:
            reasons.append("training_truth_tier_missing")
        if requested_tier != artifact_class:
            reasons.append("training_tier_artifact_class_mismatch")
        if action == "assign_training_truth":
            assigners = tiers[artifact_class]["assigners"]
            if actor not in assigners:
                reasons.append("actor_cannot_assign_training_truth")
            elif not inputs["training_promotion_evidence_valid"]:
                reasons.append("training_promotion_evidence_required")
            else:
                may_mutate = True
        elif action == "revoke_training_truth":
            if actor != "maskfactory_training_governance":
                reasons.append("actor_cannot_revoke_training_truth")
            elif requested_tier != "machine_candidate":
                reasons.append("training_revocation_must_become_candidate")
            else:
                may_mutate = True
        elif action in {"evaluate_use", "reject"}:
            if requested_tier != current_tier:
                reasons.append("non_mutating_action_changed_training_truth")
            if action == "reject":
                may_use = False
                reasons.append("consumer_rejected")
        else:
            reasons.append("action_wrong_namespace")
        if requested_tier not in use["allowed_training_truth_tiers"]:
            reasons.append("training_truth_tier_not_eligible_for_use")
        if inputs["exact_output_certificate_valid"]:
            reasons.append("operational_certificate_cannot_create_training_truth")
        if inputs["input_role"] != "standalone":
            reasons.append("training_truth_cannot_be_operational_input_role")
        if reasons:
            may_mutate = False
            may_use = False
            effective_training = current_tier
        elif may_mutate:
            effective_training = requested_tier
        effective_operational = None

    unique_reasons = sorted(set(reasons))
    return {
        "status": "allow" if not unique_reasons and may_use else "reject",
        "may_use": bool(not unique_reasons and may_use),
        "may_mutate_authority": bool(not unique_reasons and may_mutate),
        "effective_operational_authority_state": effective_operational,
        "effective_training_truth_tier": effective_training,
        "operational_floor_comparison": comparison,
        "reasons": unique_reasons,
    }


def validate_authority_decision(
    document: Mapping[str, Any],
    *,
    policy: Mapping[str, Any] | None = None,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
) -> None:
    """Validate schema, policy binding, semantics, and canonical decision hash."""

    try:
        schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuthorityLatticeError("decision_schema_unreadable", str(exc)) from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document), key=lambda error: list(error.path)
    )
    if errors:
        error = errors[0]
        pointer = "/" + "/".join(str(part) for part in error.path)
        raise AuthorityLatticeError("decision_schema", f"{pointer}: {error.message}")
    active = dict(policy) if policy is not None else load_authority_lattice_policy()
    if document["policy"] != {
        "policy_id": active["policy_id"],
        "policy_version": active["policy_version"],
        "policy_sha256": active["policy_sha256"],
    }:
        raise AuthorityLatticeError("decision_policy_binding", "decision policy binding drifted")
    unsigned = {key: value for key, value in document.items() if key != "decision_sha256"}
    if document["decision_sha256"] != canonical_sha256(unsigned):
        raise AuthorityLatticeError("decision_hash_mismatch", "decision_sha256 does not match")
    # Recompute only the semantic result to avoid recursive validation.
    normalized = _normalize_inputs(document["inputs"], active)
    reasons: list[str] = []
    recomputed = _evaluate_normalized(normalized, active, reasons)
    if document["inputs"] != normalized or document["result"] != recomputed:
        raise AuthorityLatticeError(
            "decision_semantic_mismatch", "decision result does not recompute"
        )


__all__ = [
    "AuthorityLatticeError",
    "DEFAULT_POLICY_PATH",
    "DEFAULT_SCHEMA_PATH",
    "canonical_sha256",
    "evaluate_authority_lattice",
    "load_authority_lattice_policy",
    "validate_authority_decision",
]
