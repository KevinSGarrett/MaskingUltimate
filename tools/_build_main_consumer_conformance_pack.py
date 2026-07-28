"""One-shot builder for pinned Main-consumer conformance fixture packs."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from maskfactory.validation import canonical_document_sha256

CHECKS = [
    "api_contract",
    "artifact_security",
    "authority_policy",
    "canonicalization",
    "capabilities",
    "contract_tests",
    "media_scope",
    "node_pack",
    "ontology",
    "package_format",
    "release_hash",
    "revocation_freshness",
    "signature",
    "signed_journal",
    "trust_anchor",
    "wire_schemas",
]

WIRE = [
    {"name": "maskfactory_release_snapshot", "version": "1.0.0"},
    {"name": "maskfactory_capability_snapshot", "version": "1.0.0"},
    {"name": "maskfactory_consumer_requirements", "version": "1.0.0"},
    {"name": "mask_acquisition_request", "version": "1.0.0"},
    {"name": "mask_acquisition_receipt", "version": "1.0.0"},
    {"name": "mask_bridge_error", "version": "1.0.0"},
    {"name": "maskfactory_adoption_receipt", "version": "1.0.0"},
    {"name": "mask_authority_invalidation_event", "version": "1.0.0"},
    {"name": "mask_repair_feedback", "version": "1.0.0"},
    {"name": "mask_bridge_event", "version": "1.0.0"},
    {"name": "operational_autonomy_certificate", "version": "1.0.0"},
    {"name": "mask_bridge_semantic_invariant_profile", "version": "1.0.0"},
]

REQUIRED_FIELDS = [
    "schema_version",
    "record_type",
    "adoption_id",
    "decided_at",
    "adoption_scope",
    "evidence_context",
    "fixture_only",
    "production_use_authorized",
    "consumer",
    "release_id",
    "release_payload_sha256",
    "capability_snapshot_id",
    "capability_snapshot_sha256",
    "consumer_requirements_id",
    "consumer_requirements_sha256",
    "qualification_bundle_id",
    "qualification_bundle_sha256",
    "trust_binding",
    "journal_checkpoint",
    "decision",
    "required_capabilities_satisfied",
    "compatibility_checks",
    "capability_decisions",
    "pinned_artifacts",
    "accepted_capabilities",
    "rejected_capabilities",
    "valid_until",
    "use_time_recheck_required",
    "revalidation_triggers",
    "adoption_payload_sha256",
    "signature",
]


def seal(doc: dict, field: str = "shape_sha256") -> dict:
    sealed = dict(doc)
    sealed[field] = ""
    sealed[field] = canonical_document_sha256(sealed, excluded_top_level_fields=(field,))
    return sealed


def write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    root = Path("tests/fixtures/main_consumer_conformance")
    Path("runtime_artifacts/main_consumer_conformance/inbox").mkdir(parents=True, exist_ok=True)

    adopted = seal(
        {
            "schema_version": "1.0.0",
            "record_type": "main_consumer_receipt_shape",
            "shape_id": "main_adoption_receipt_adopted_v1",
            "decision": "adopted",
            "adoption_scope": "production_authority",
            "evidence_context": "runtime_evidence",
            "fixture_only": False,
            "production_use_authorized": True,
            "required_capabilities_satisfied": True,
            "required_top_level_fields": REQUIRED_FIELDS,
            "required_compatibility_checks": CHECKS,
            "capability_decision_rules": {
                "required_must_all_be": "accepted",
                "optional_must_all_be": "accepted",
                "producer_extra_may_be_rejected": True,
            },
            "consumer_project": "Comfy_UI_Main",
            "claim_boundary": {
                "shape_is_not_main_adoption_evidence": True,
                "main_must_supply_signed_runtime_receipt": True,
            },
            "shape_sha256": "",
        }
    )
    rejected = seal(
        {
            "schema_version": "1.0.0",
            "record_type": "main_consumer_receipt_shape",
            "shape_id": "main_adoption_receipt_rejected_v1",
            "decision": "rejected",
            "adoption_scope": "production_authority",
            "evidence_context": "runtime_evidence",
            "fixture_only": False,
            "production_use_authorized": False,
            "required_capabilities_satisfied": False,
            "required_top_level_fields": REQUIRED_FIELDS,
            "required_compatibility_checks": CHECKS,
            "capability_decision_rules": {
                "required_must_include_rejected": True,
                "optional_may_be_rejected": True,
                "accepted_capabilities_must_be_empty_when_required_fail": True,
            },
            "consumer_project": "Comfy_UI_Main",
            "claim_boundary": {
                "shape_is_not_main_adoption_evidence": True,
                "main_must_supply_signed_runtime_receipt": True,
            },
            "shape_sha256": "",
        }
    )
    partial = seal(
        {
            "schema_version": "1.0.0",
            "record_type": "main_consumer_receipt_shape",
            "shape_id": "main_adoption_receipt_partially_adopted_v1",
            "decision": "partially_adopted",
            "adoption_scope": "production_authority",
            "evidence_context": "runtime_evidence",
            "fixture_only": False,
            "production_use_authorized": False,
            "required_capabilities_satisfied": True,
            "required_top_level_fields": REQUIRED_FIELDS,
            "required_compatibility_checks": CHECKS,
            "capability_decision_rules": {
                "required_must_all_be": "accepted",
                "optional_must_include_rejected": True,
            },
            "consumer_project": "Comfy_UI_Main",
            "claim_boundary": {
                "shape_is_not_main_adoption_evidence": True,
                "main_must_supply_signed_runtime_receipt": True,
            },
            "shape_sha256": "",
        }
    )
    accepted_obs = seal(
        {
            "schema_version": "1.0.0",
            "record_type": "main_consumer_adapter_observation_template",
            "template_id": "adapter_observation_accepted_v1",
            "expected_conformance_status": "accepted",
            "observation": {
                "adapter_identity": {
                    "package_name": "comfy-main-maskfactory-adapter",
                    "package_version": "1.0.0",
                    "package_sha256": "1" * 64,
                    "git_commit": "1" * 40,
                    "git_tree": "2" * 40,
                    "repository_clean": True,
                    "install_mode": "wheel",
                },
                "producer_state": {
                    "release_status": "published",
                    "adoption_decision": "adopted",
                    "repository_clean": True,
                },
                "contract_bindings": {
                    "bridge_contract": "maskfactory-comfyui-bridge/1.0",
                    "api_contract": "maskfactory-api/1.0",
                    "package_format": "maskfactory-package/1.0",
                    "ontology_version": "body_parts_v1",
                    "node_pack_version": "1.0.0",
                    "wire_schemas": WIRE,
                    "used_openapi_paths": ["/health", "/models", "/predict", "/refine"],
                },
                "boundary_observations": {
                    "imports": [
                        "maskfactory.contracts",
                        "maskfactory.contracts.maskfactory_adapter",
                        "typing",
                    ],
                    "documented_dependencies": [
                        "maskfactory.contracts",
                        "maskfactory.contracts.maskfactory_adapter",
                    ],
                    "comfyui_node_ids": [],
                    "mutable_path_dependencies": [],
                },
            },
            "claim_boundary": {
                "template_is_not_main_adapter_evidence": True,
                "main_must_supply_observed_package_identity": True,
            },
            "shape_sha256": "",
        }
    )
    rejected_dirty = seal(
        {
            "schema_version": "1.0.0",
            "record_type": "main_consumer_adapter_observation_template",
            "template_id": "adapter_observation_rejected_dirty_worktree_v1",
            "expected_conformance_status": "rejected",
            "expected_rejection_reasons": [
                "adapter_dirty_worktree",
                "adapter_editable_install",
                "producer_dirty_worktree",
                "producer_release_not_adopted",
            ],
            "observation": {
                "adapter_identity": {
                    "package_name": "comfy-main-maskfactory-adapter",
                    "package_version": "0.0.0-dirty",
                    "package_sha256": "a" * 64,
                    "git_commit": "a" * 40,
                    "git_tree": "b" * 40,
                    "repository_clean": False,
                    "install_mode": "editable",
                },
                "producer_state": {
                    "release_status": "draft",
                    "adoption_decision": "revalidation_required",
                    "repository_clean": False,
                },
                "contract_bindings": {
                    "bridge_contract": "maskfactory-comfyui-bridge/1.0",
                    "api_contract": "maskfactory-api/1.0",
                    "package_format": "maskfactory-package/1.0",
                    "ontology_version": "body_parts_v1",
                    "node_pack_version": "1.0.0",
                    "wire_schemas": WIRE,
                    "used_openapi_paths": ["/health", "/models", "/predict", "/refine"],
                },
                "boundary_observations": {
                    "imports": ["maskfactory.contracts.maskfactory_adapter"],
                    "documented_dependencies": ["maskfactory.contracts.maskfactory_adapter"],
                    "comfyui_node_ids": [],
                    "mutable_path_dependencies": [],
                },
            },
            "claim_boundary": {
                "template_is_not_main_adapter_evidence": True,
                "main_must_supply_observed_package_identity": True,
            },
            "shape_sha256": "",
        }
    )
    rejected_internal = seal(
        {
            "schema_version": "1.0.0",
            "record_type": "main_consumer_adapter_observation_template",
            "template_id": "adapter_observation_rejected_internal_dependency_v1",
            "expected_conformance_status": "rejected",
            "expected_rejection_reasons": [
                "adapter_internal_dependency",
                "adapter_node_id_coupling",
                "adapter_mutable_path_dependency",
            ],
            "observation": {
                "adapter_identity": {
                    "package_name": "comfy-main-maskfactory-adapter",
                    "package_version": "1.0.0",
                    "package_sha256": "c" * 64,
                    "git_commit": "c" * 40,
                    "git_tree": "d" * 40,
                    "repository_clean": True,
                    "install_mode": "wheel",
                },
                "producer_state": {
                    "release_status": "published",
                    "adoption_decision": "adopted",
                    "repository_clean": True,
                },
                "contract_bindings": {
                    "bridge_contract": "maskfactory-comfyui-bridge/1.0",
                    "api_contract": "maskfactory-api/1.0",
                    "package_format": "maskfactory-package/1.0",
                    "ontology_version": "body_parts_v1",
                    "node_pack_version": "1.0.0",
                    "wire_schemas": WIRE,
                    "used_openapi_paths": ["/health", "/models", "/predict", "/refine"],
                },
                "boundary_observations": {
                    "imports": [
                        "maskfactory.contracts.maskfactory_adapter",
                        "maskfactory.bridge.mode_a_package_read",
                        "NODE_CLASS_MAPPINGS",
                    ],
                    "documented_dependencies": ["maskfactory.contracts.maskfactory_adapter"],
                    "comfyui_node_ids": ["MaskFactoryPredict"],
                    "mutable_path_dependencies": ["src/maskfactory/bridge"],
                },
            },
            "claim_boundary": {
                "template_is_not_main_adapter_evidence": True,
                "main_must_supply_observed_package_identity": True,
            },
            "shape_sha256": "",
        }
    )
    disagreement = seal(
        {
            "schema_version": "1.0.0",
            "record_type": "main_consumer_requirements_capability_disagreement_vectors",
            "vectors_id": "requirements_capability_disagreement_v1",
            "vectors": [
                {
                    "id": "required_capability_unavailable",
                    "mutation": "drop_required_offer",
                    "expected_status": "rejected",
                    "expected_rejection_contains": ["mask.package.read"],
                    "optional_unmet_remains_distinct": True,
                },
                {
                    "id": "optional_only_unmet_does_not_block_acceptance",
                    "mutation": "drop_optional_offer",
                    "expected_status": "accepted",
                    "expected_optional_unmet": ["mask.live.predict"],
                    "expected_required_all_met": True,
                },
                {
                    "id": "label_coverage_disagreement",
                    "mutation": "shrink_required_labels",
                    "expected_status": "rejected",
                    "expected_rejection_contains": ["__global__.labels", "labels"],
                },
                {
                    "id": "authority_floor_disagreement",
                    "mutation": "lower_authority_states",
                    "expected_status": "rejected",
                    "expected_rejection_contains": ["authority_state"],
                },
                {
                    "id": "version_compatibility_disagreement",
                    "mutation": "wrong_api_contract_version",
                    "expected_status": "rejected",
                    "expected_rejection_contains": ["__global__.versions"],
                },
                {
                    "id": "latency_resource_envelope_disagreement",
                    "mutation": "exceed_latency_budget",
                    "expected_status": "rejected",
                    "expected_rejection_contains": ["__global__.latency_resources"],
                },
                {
                    "id": "ambiguous_duplicate_capability_offers",
                    "mutation": "duplicate_capability_offer",
                    "expected_status": "rejected",
                    "expected_issue_validators": ["capability_ambiguity"],
                },
            ],
            "claim_boundary": {
                "vectors_are_producer_oracles": True,
                "main_must_independently_recompute": True,
            },
            "shape_sha256": "",
        }
    )

    members = {
        "receipt_shapes/adopted_receipt_shape_v1.json": adopted,
        "receipt_shapes/rejected_receipt_shape_v1.json": rejected,
        "receipt_shapes/partially_adopted_receipt_shape_v1.json": partial,
        "adapter_observations/accepted_observation_template_v1.json": accepted_obs,
        "adapter_observations/rejected_dirty_worktree_template_v1.json": rejected_dirty,
        "adapter_observations/rejected_internal_dependency_template_v1.json": rejected_internal,
        "disagreement_vectors/requirements_capability_disagreement_v1.json": disagreement,
    }
    for rel, doc in members.items():
        write_json(root / rel, doc)

    manifest = {
        "schema_version": "1.0.0",
        "record_type": "main_consumer_conformance_pack_manifest",
        "pack_id": "maskfactory-main-consumer-conformance-pack-v1",
        "policy_id": "maskfactory-bridge-main-consumer-conformance-v1",
        "members": sorted(
            [
                {
                    "path": rel,
                    "sha256": canonical_document_sha256(doc),
                    "record_type": doc.get("record_type"),
                }
                for rel, doc in members.items()
            ],
            key=lambda row: row["path"],
        ),
        "claim_boundary": {
            "pack_is_not_main_adoption": True,
            "main_adoption_complete": False,
            "awaiting_main_supplied_artifacts": True,
        },
        "manifest_sha256": "",
    }
    manifest["manifest_sha256"] = canonical_document_sha256(
        manifest, excluded_top_level_fields=("manifest_sha256",)
    )
    write_json(root / "pack_manifest_v1.json", manifest)

    policy_path = Path("configs/bridge_main_consumer_conformance_policy.yaml")
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    policy["policy_sha256"] = canonical_document_sha256(
        policy, excluded_top_level_fields=("policy_sha256",)
    )
    policy_path.write_text(
        yaml.safe_dump(policy, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    golden = {
        "schema_version": "1.0.0",
        "artifact_type": "main_consumer_conformance_golden_vectors",
        "policy_id": policy["policy_id"],
        "policy_sha256": policy["policy_sha256"],
        "pack_manifest_sha256": manifest["manifest_sha256"],
        "vectors": [
            {
                "id": "producer_pack_ready_awaiting_main",
                "main_artifacts_present": False,
                "expected_harness_status": "awaiting_main",
                "expected_main_adoption_complete": False,
                "expected_reasons_contains": ["main_artifact_missing"],
            },
            {
                "id": "adopted_shape_pin",
                "shape_id": adopted["shape_id"],
                "shape_sha256": adopted["shape_sha256"],
                "decision": "adopted",
            },
            {
                "id": "rejected_shape_pin",
                "shape_id": rejected["shape_id"],
                "shape_sha256": rejected["shape_sha256"],
                "decision": "rejected",
            },
            {
                "id": "partial_shape_pin",
                "shape_id": partial["shape_id"],
                "shape_sha256": partial["shape_sha256"],
                "decision": "partially_adopted",
            },
            {
                "id": "accepted_adapter_template_pin",
                "template_id": accepted_obs["template_id"],
                "shape_sha256": accepted_obs["shape_sha256"],
                "expected_conformance_status": "accepted",
            },
            {
                "id": "disagreement_vector_count",
                "expected_vector_count": len(disagreement["vectors"]),
                "vectors_sha256": disagreement["shape_sha256"],
            },
        ],
    }
    write_json(
        Path("qa/governance/bridge/main_consumer_conformance_golden_vectors_v1.json"),
        golden,
    )
    Path("runtime_artifacts/main_consumer_conformance/inbox/.keep").write_text(
        "Drop Main-supplied adoption_receipt.json, adapter_observation.json, and "
        "optional requirements_capability_bundle.json here for fail-closed validation.\n"
        "Absence means awaiting_main; presence never fabricates adoption without shape match.\n",
        encoding="utf-8",
    )
    print(f"policy_sha256={policy['policy_sha256']}")
    print(f"manifest_sha256={manifest['manifest_sha256']}")
    print(f"vector_count={len(disagreement['vectors'])}")


if __name__ == "__main__":
    main()
