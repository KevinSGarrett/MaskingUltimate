"""Cross-project bridge contracts that are additive to frozen wire schemas."""

from .adoption_receipt_matrix import (
    AdoptionReceiptMatrixError,
    build_adoption_receipt_matrix_decision,
    validate_adoption_receipt_matrix_decision,
)
from .artifact_binding import (
    ArtifactConsumptionError,
    build_artifact_consumption_decision,
    validate_artifact_consumption_decision,
)
from .capability_snapshot import (
    CapabilityQualificationError,
    build_capability_decision,
    restore_route_champion_from_rollback,
    validate_capability_decision,
)
from .clean_release_packaging import (
    install_clean_release,
    load_clean_release_manifest,
    rollback_clean_release,
    validate_clean_release_manifest,
)
from .consumer_invalidation import (
    ConsumerInvalidationError,
    build_consumer_invalidation_decision,
    validate_consumer_invalidation_decision,
)
from .consumer_requirements import evaluate_consumer_requirements_admission
from .cross_project_qualification import (
    EXTERNAL_MAIN_DEPENDENCIES as CROSS_PROJECT_QUALIFICATION_EXTERNAL_MAIN_DEPENDENCIES,
)
from .cross_project_qualification import (
    POLICY_ID as CROSS_PROJECT_QUALIFICATION_POLICY_ID,
)
from .cross_project_qualification import (
    CrossProjectQualificationError,
    build_cross_project_qualification_evidence,
    run_cross_project_qualification,
    validate_cross_project_qualification_evidence,
)
from .crosswalk import (
    CrosswalkError,
    evaluate_maskfactory_main_crosswalk,
    load_crosswalk_definition,
)
from .error_matrix import (
    FAILURE_DOMAINS,
    MATRIX_ID,
    build_bridge_error_decision,
    validate_bridge_error_decision,
)
from .external_adapter_conformance import (
    ExternalAdapterConformanceError,
    build_external_adapter_conformance_evidence,
    validate_external_adapter_conformance_evidence,
)
from .failure_control import (
    EXTERNAL_MAIN_DEPENDENCIES as FAILURE_CONTROL_EXTERNAL_MAIN_DEPENDENCIES,
)
from .failure_control import (
    POLICY_ID as FAILURE_CONTROL_POLICY_ID,
)
from .failure_control import (
    FailureControlError,
    build_failure_control_evidence,
    simulate_fault_injection,
    validate_failure_control_evidence,
)
from .feedback_intake import (
    FeedbackIntakeError,
    FeedbackIntakeLedger,
    intake_bridge_feedback,
    validate_feedback_intake_evidence,
)
from .final_release_handoff import (
    EXTERNAL_MAIN_DEPENDENCIES as FINAL_RELEASE_HANDOFF_EXTERNAL_MAIN_DEPENDENCIES,
)
from .final_release_handoff import (
    POLICY_ID as FINAL_RELEASE_HANDOFF_POLICY_ID,
)
from .final_release_handoff import (
    FinalReleaseHandoffError,
    evaluate_final_release_handoff,
    load_tracker_data,
    regenerate_profile_status_inputs,
    validate_final_release_handoff_evidence,
)
from .identity import (
    assignment_evidence_sha256,
    build_bridge_identity_decision,
    canonical_identity_record,
    validate_bridge_identity_decision,
    validate_bridge_identity_set,
)
from .integration_release import (
    IntegrationReleaseError,
    build_inventory_from_root,
    compare_inventories,
    install_integration_pack,
    publish_and_validate_against_release_root,
    run_integration_release_acceptance,
    validate_integration_release_evidence,
)
from .journal import (
    ALLOWED_TRANSITIONS,
    EXTERNAL_MAIN_DEPENDENCIES,
    JOURNAL_STATES,
    BridgeJournalError,
    append_bridge_journal_event,
    checkpoint_bridge_journal,
    reconstruct_bridge_journal_state,
    validate_bridge_journal_history,
    validate_bridge_journal_reconstruction_evidence,
)
from .journal import (
    POLICY_ID as JOURNAL_POLICY_ID,
)
from .main_consumer_conformance import (
    MainConsumerConformanceError,
    evaluate_disagreement_vectors,
    load_adapter_observation_template,
    load_disagreement_vectors,
    load_fixture_pack,
    load_golden_vectors,
    load_receipt_shape,
    run_main_consumer_conformance_harness,
    validate_main_consumer_conformance_evidence,
)
from .mode_a_package_read import (
    ModeAPackageReadError,
    evaluate_mode_a_package_read,
    validate_mode_a_package_read_evidence,
)
from .mode_a_vertical_slice import (
    ModeAVerticalSliceError,
    build_fixture_adapter_observation,
    build_fixture_adopted_package,
    build_intended_inpaint_workflow,
    build_producer_handoff_journal,
    prove_raw_status_escalation_is_rejected,
    reject_fabricated_downstream_receipt,
    run_mode_a_vertical_slice,
    validate_mode_a_vertical_slice_evidence,
)
from .mode_b_localhost_client import ModeBLocalhostClient
from .mode_b_vertical_slice import (
    ModeBVerticalSliceError,
    build_fixture_mode_b_transport,
    evaluate_refinement_authority_ceiling,
    prove_service_down_behavior,
    reject_draft_self_promotion,
    run_mode_b_draft_actions,
    run_mode_b_vertical_slice,
    submit_exact_prediction_certification_transaction,
    validate_mode_b_vertical_slice_evidence,
)
from .multi_person_mode_a_vertical_slice import (
    MultiPersonModeAVerticalSliceError,
    assess_zero_ownership_ambiguity,
    build_overlapping_contact_duo_fixture,
    evaluate_duo_mode_a_reads,
    evaluate_duo_multi_person_gate,
    run_multi_person_mode_a_vertical_slice,
    seed_cross_instance_rejection,
    seed_wrong_person_rejection,
    validate_multi_person_mode_a_vertical_slice_evidence,
)
from .receipt_arbitration_conformance import (
    ReceiptArbitrationConformanceError,
    build_receipt_arbitration_conformance_evidence,
    comparable_scope_identity,
    comparable_scope_sha256,
    normalize_and_arbitrate_receipts,
    validate_receipt_arbitration_conformance_evidence,
)
from .recovery import (
    EXTERNAL_MAIN_DEPENDENCIES as RECOVERY_EXTERNAL_MAIN_DEPENDENCIES,
)
from .recovery import (
    POLICY_ID as RECOVERY_POLICY_ID,
)
from .recovery import (
    RecoveryError,
    build_recovery_evidence,
    simulate_kill_at_boundary,
    validate_recovery_evidence,
)
from .release_publication import load_publication_evidence, validate_release_publication
from .runtime_client_types import (
    CLIENT_ACTIONS,
    CLIENT_ERROR_CODES,
    ClientError,
    TransportRequest,
    TransportResponse,
)
from .transforms import (
    TransformValidationError,
    build_roundtrip_evidence,
    execute_box,
    execute_point,
    invert_transform_chain,
    remap_side_label,
    validate_protected_regions,
    validate_transform_chain,
)
from .use_eligibility import (
    UseEligibilityError,
    derive_main_compatibility_alias,
    evaluate_bridge_use_eligibility,
    validate_bridge_use_eligibility_decision,
    validate_bridge_use_eligibility_observation,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "AdoptionReceiptMatrixError",
    "ArtifactConsumptionError",
    "BridgeJournalError",
    "CLIENT_ACTIONS",
    "CLIENT_ERROR_CODES",
    "CROSS_PROJECT_QUALIFICATION_EXTERNAL_MAIN_DEPENDENCIES",
    "CROSS_PROJECT_QUALIFICATION_POLICY_ID",
    "CapabilityQualificationError",
    "ClientError",
    "ConsumerInvalidationError",
    "CrossProjectQualificationError",
    "CrosswalkError",
    "ExternalAdapterConformanceError",
    "EXTERNAL_MAIN_DEPENDENCIES",
    "FAILURE_CONTROL_EXTERNAL_MAIN_DEPENDENCIES",
    "FAILURE_CONTROL_POLICY_ID",
    "FAILURE_DOMAINS",
    "FINAL_RELEASE_HANDOFF_EXTERNAL_MAIN_DEPENDENCIES",
    "FINAL_RELEASE_HANDOFF_POLICY_ID",
    "FailureControlError",
    "FeedbackIntakeError",
    "FeedbackIntakeLedger",
    "FinalReleaseHandoffError",
    "IntegrationReleaseError",
    "JOURNAL_POLICY_ID",
    "JOURNAL_STATES",
    "MATRIX_ID",
    "MainConsumerConformanceError",
    "ModeAPackageReadError",
    "ModeAVerticalSliceError",
    "ModeBLocalhostClient",
    "ModeBVerticalSliceError",
    "MultiPersonModeAVerticalSliceError",
    "RECOVERY_EXTERNAL_MAIN_DEPENDENCIES",
    "RECOVERY_POLICY_ID",
    "ReceiptArbitrationConformanceError",
    "RecoveryError",
    "TransformValidationError",
    "TransportRequest",
    "TransportResponse",
    "UseEligibilityError",
    "append_bridge_journal_event",
    "assess_zero_ownership_ambiguity",
    "assignment_evidence_sha256",
    "build_adoption_receipt_matrix_decision",
    "build_cross_project_qualification_evidence",
    "build_overlapping_contact_duo_fixture",
    "build_artifact_consumption_decision",
    "build_bridge_error_decision",
    "build_external_adapter_conformance_evidence",
    "build_bridge_identity_decision",
    "build_capability_decision",
    "restore_route_champion_from_rollback",
    "build_consumer_invalidation_decision",
    "build_failure_control_evidence",
    "evaluate_final_release_handoff",
    "build_fixture_adapter_observation",
    "build_fixture_adopted_package",
    "build_fixture_mode_b_transport",
    "build_intended_inpaint_workflow",
    "build_producer_handoff_journal",
    "build_receipt_arbitration_conformance_evidence",
    "build_inventory_from_root",
    "build_recovery_evidence",
    "build_roundtrip_evidence",
    "canonical_identity_record",
    "checkpoint_bridge_journal",
    "comparable_scope_identity",
    "comparable_scope_sha256",
    "compare_inventories",
    "derive_main_compatibility_alias",
    "evaluate_bridge_use_eligibility",
    "evaluate_consumer_requirements_admission",
    "evaluate_disagreement_vectors",
    "evaluate_maskfactory_main_crosswalk",
    "evaluate_duo_mode_a_reads",
    "evaluate_duo_multi_person_gate",
    "evaluate_mode_a_package_read",
    "evaluate_refinement_authority_ceiling",
    "execute_box",
    "execute_point",
    "install_clean_release",
    "install_integration_pack",
    "intake_bridge_feedback",
    "invert_transform_chain",
    "load_adapter_observation_template",
    "load_clean_release_manifest",
    "load_crosswalk_definition",
    "load_disagreement_vectors",
    "load_fixture_pack",
    "load_golden_vectors",
    "load_publication_evidence",
    "load_receipt_shape",
    "load_tracker_data",
    "normalize_and_arbitrate_receipts",
    "regenerate_profile_status_inputs",
    "prove_raw_status_escalation_is_rejected",
    "prove_service_down_behavior",
    "publish_and_validate_against_release_root",
    "reconstruct_bridge_journal_state",
    "reject_draft_self_promotion",
    "reject_fabricated_downstream_receipt",
    "remap_side_label",
    "rollback_clean_release",
    "run_cross_project_qualification",
    "run_integration_release_acceptance",
    "run_main_consumer_conformance_harness",
    "run_mode_a_vertical_slice",
    "run_mode_b_draft_actions",
    "run_mode_b_vertical_slice",
    "run_multi_person_mode_a_vertical_slice",
    "seed_cross_instance_rejection",
    "seed_wrong_person_rejection",
    "simulate_fault_injection",
    "simulate_kill_at_boundary",
    "submit_exact_prediction_certification_transaction",
    "validate_adoption_receipt_matrix_decision",
    "validate_artifact_consumption_decision",
    "validate_bridge_error_decision",
    "validate_bridge_identity_decision",
    "validate_bridge_identity_set",
    "validate_bridge_journal_history",
    "validate_bridge_journal_reconstruction_evidence",
    "validate_bridge_use_eligibility_decision",
    "validate_bridge_use_eligibility_observation",
    "validate_external_adapter_conformance_evidence",
    "validate_capability_decision",
    "validate_consumer_invalidation_decision",
    "validate_clean_release_manifest",
    "validate_cross_project_qualification_evidence",
    "validate_failure_control_evidence",
    "validate_feedback_intake_evidence",
    "validate_final_release_handoff_evidence",
    "validate_integration_release_evidence",
    "validate_main_consumer_conformance_evidence",
    "validate_mode_a_package_read_evidence",
    "validate_mode_a_vertical_slice_evidence",
    "validate_mode_b_vertical_slice_evidence",
    "validate_multi_person_mode_a_vertical_slice_evidence",
    "validate_protected_regions",
    "validate_receipt_arbitration_conformance_evidence",
    "validate_recovery_evidence",
    "validate_release_publication",
    "validate_transform_chain",
]
