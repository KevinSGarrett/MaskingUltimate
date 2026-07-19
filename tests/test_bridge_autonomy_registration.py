from __future__ import annotations

from maskfactory.authority import (
    OperationalInvalidationError,
    evaluate_operational_certificate_at_use,
    verify_operational_invalidation_event,
)
from maskfactory.autonomy import (
    DurableRepairExecutor,
    LiveRepairProposal,
    OperationalRepairError,
    OperationalRepairResult,
)
from maskfactory.bridge import (
    CROSS_PROJECT_QUALIFICATION_EXTERNAL_MAIN_DEPENDENCIES,
    CROSS_PROJECT_QUALIFICATION_POLICY_ID,
    FAILURE_CONTROL_EXTERNAL_MAIN_DEPENDENCIES,
    FAILURE_CONTROL_POLICY_ID,
    FINAL_RELEASE_HANDOFF_EXTERNAL_MAIN_DEPENDENCIES,
    FINAL_RELEASE_HANDOFF_POLICY_ID,
    FIXTURE_MAIN_AUTHORITY_KIND,
    FIXTURE_MAIN_CONSUMER_KIND,
    JOURNAL_POLICY_ID,
    RECOVERY_EXTERNAL_MAIN_DEPENDENCIES,
    RECOVERY_POLICY_ID,
    SYNTHETIC_MAIN_GIT_COMMIT,
    AdoptionReceiptMatrixError,
    BridgeJournalError,
    CapabilityQualificationError,
    ConsumerInvalidationError,
    CrossProjectQualificationError,
    CrosswalkError,
    ExternalAdapterConformanceError,
    FailureControlError,
    FeedbackIntakeError,
    FeedbackIntakeLedger,
    FinalReleaseHandoffError,
    FixtureMainBindingError,
    FixtureMainError,
    IntegrationReleaseError,
    MainConsumerConformanceError,
    ModeAPackageReadError,
    ModeAVerticalSliceError,
    ModeBLocalhostClient,
    ModeBVerticalSliceError,
    MultiPersonModeAVerticalSliceError,
    ReceiptArbitrationConformanceError,
    RecoveryError,
    TransformValidationError,
    UseEligibilityError,
    append_bridge_journal_event,
    assess_zero_ownership_ambiguity,
    build_adoption_receipt_matrix_decision,
    build_consumer_invalidation_decision,
    build_cross_project_qualification_evidence,
    build_external_adapter_conformance_evidence,
    build_failure_control_evidence,
    build_inventory_from_root,
    build_receipt_arbitration_conformance_evidence,
    build_recovery_evidence,
    checkpoint_bridge_journal,
    comparable_scope_identity,
    comparable_scope_sha256,
    compare_inventories,
    evaluate_bridge_use_eligibility,
    evaluate_consumer_requirements_admission,
    evaluate_final_release_handoff,
    evaluate_maskfactory_main_crosswalk,
    evaluate_mode_a_package_read,
    install_clean_release,
    install_integration_pack,
    intake_bridge_feedback,
    load_clean_release_manifest,
    load_crosswalk_definition,
    load_fixture_main_binding,
    load_publication_evidence,
    load_tracker_data,
    materialize_fixture_main,
    normalize_and_arbitrate_receipts,
    observation_from_fixture_main_binding,
    publish_and_validate_against_release_root,
    reconstruct_bridge_journal_state,
    regenerate_profile_status_inputs,
    rollback_clean_release,
    run_cross_project_qualification,
    run_fixture_main_producer_verify,
    run_integration_release_acceptance,
    run_main_consumer_conformance_harness,
    run_mode_a_vertical_slice,
    run_mode_b_vertical_slice,
    run_multi_person_mode_a_vertical_slice,
    seed_cross_instance_rejection,
    seed_wrong_person_rejection,
    simulate_fault_injection,
    simulate_kill_at_boundary,
    validate_adoption_receipt_matrix_decision,
    validate_artifact_consumption_decision,
    validate_bridge_journal_history,
    validate_bridge_journal_reconstruction_evidence,
    validate_bridge_use_eligibility_decision,
    validate_capability_decision,
    validate_clean_release_manifest,
    validate_consumer_invalidation_decision,
    validate_cross_project_qualification_evidence,
    validate_external_adapter_conformance_evidence,
    validate_failure_control_evidence,
    validate_feedback_intake_evidence,
    validate_final_release_handoff_evidence,
    validate_integration_release_evidence,
    validate_main_consumer_conformance_evidence,
    validate_mode_a_package_read_evidence,
    validate_mode_a_vertical_slice_evidence,
    validate_mode_b_vertical_slice_evidence,
    validate_multi_person_mode_a_vertical_slice_evidence,
    validate_receipt_arbitration_conformance_evidence,
    validate_recovery_evidence,
    validate_release_publication,
    validate_transform_chain,
)
from maskfactory.contracts import MaskFactoryAdapter
from maskfactory.external_supervision_producers import (
    ExternalSupervisionProducerError,
    produce_project_contained_evidence,
)
from maskfactory.validation import schema_validator


def test_shared_schema_registry_includes_bridge_additive_decisions() -> None:
    assert schema_validator("bridge_use_eligibility_decision")
    assert schema_validator("maskfactory_capability_decision")
    assert schema_validator("maskfactory_consumer_requirements_admission")
    assert schema_validator("bridge_adoption_receipt_matrix_decision")
    assert schema_validator("bridge_consumer_invalidation_decision")
    assert schema_validator("bridge_crosswalk")
    assert schema_validator("external_adapter_conformance_evidence")
    assert schema_validator("main_consumer_conformance_evidence")
    assert schema_validator("cross_project_qualification_evidence")
    assert schema_validator("bridge_final_release_handoff_evidence")
    assert schema_validator("mode_b_localhost_client_response")
    assert schema_validator("mode_a_vertical_slice_evidence")
    assert schema_validator("mode_b_vertical_slice_evidence")
    assert schema_validator("multi_person_mode_a_vertical_slice_evidence")
    assert schema_validator("maskfactory_integration_release_evidence")
    assert schema_validator("maskfactory_clean_release_manifest")
    assert schema_validator("operational_invalidation_event")
    assert schema_validator("mode_a_package_read_evidence")
    assert schema_validator("receipt_arbitration_conformance_evidence")
    assert schema_validator("bridge_failure_control_evidence")
    assert schema_validator("bridge_recovery_evidence")
    assert schema_validator("bridge_journal_reconstruction_evidence")
    assert schema_validator("feedback_intake_evidence")
    assert schema_validator("external_supervision_qualification_evidence")
    assert schema_validator("external_supervision_source_hash_manifest")
    assert schema_validator("external_supervision_identity_evidence")
    assert schema_validator("external_supervision_split_dedup_evidence")


def test_bridge_package_exports_additive_contracts() -> None:
    assert evaluate_bridge_use_eligibility
    assert validate_bridge_use_eligibility_decision
    assert validate_capability_decision
    assert evaluate_consumer_requirements_admission
    assert evaluate_maskfactory_main_crosswalk
    assert load_crosswalk_definition
    assert validate_clean_release_manifest
    assert load_clean_release_manifest
    assert install_clean_release
    assert rollback_clean_release
    assert validate_release_publication
    assert load_publication_evidence
    assert validate_transform_chain
    assert validate_artifact_consumption_decision
    assert build_adoption_receipt_matrix_decision
    assert validate_adoption_receipt_matrix_decision
    assert build_external_adapter_conformance_evidence
    assert validate_external_adapter_conformance_evidence
    assert run_main_consumer_conformance_harness
    assert validate_main_consumer_conformance_evidence
    assert MainConsumerConformanceError
    assert CrossProjectQualificationError
    assert build_cross_project_qualification_evidence
    assert run_cross_project_qualification
    assert validate_cross_project_qualification_evidence
    assert CROSS_PROJECT_QUALIFICATION_POLICY_ID
    assert CROSS_PROJECT_QUALIFICATION_EXTERNAL_MAIN_DEPENDENCIES
    assert FinalReleaseHandoffError
    assert evaluate_final_release_handoff
    assert validate_final_release_handoff_evidence
    assert load_tracker_data
    assert regenerate_profile_status_inputs
    assert FINAL_RELEASE_HANDOFF_POLICY_ID
    assert FINAL_RELEASE_HANDOFF_EXTERNAL_MAIN_DEPENDENCIES
    assert evaluate_mode_a_package_read
    assert validate_mode_a_package_read_evidence
    assert ModeAPackageReadError
    assert ModeAVerticalSliceError
    assert run_mode_a_vertical_slice
    assert validate_mode_a_vertical_slice_evidence
    assert IntegrationReleaseError
    assert run_integration_release_acceptance
    assert validate_integration_release_evidence
    assert install_integration_pack
    assert publish_and_validate_against_release_root
    assert build_inventory_from_root
    assert compare_inventories
    assert MultiPersonModeAVerticalSliceError
    assert run_multi_person_mode_a_vertical_slice
    assert validate_multi_person_mode_a_vertical_slice_evidence
    assert seed_wrong_person_rejection
    assert seed_cross_instance_rejection
    assert assess_zero_ownership_ambiguity
    assert build_receipt_arbitration_conformance_evidence
    assert validate_receipt_arbitration_conformance_evidence
    assert normalize_and_arbitrate_receipts
    assert comparable_scope_identity
    assert comparable_scope_sha256
    assert ReceiptArbitrationConformanceError
    assert build_failure_control_evidence
    assert validate_failure_control_evidence
    assert simulate_fault_injection
    assert FailureControlError
    assert FAILURE_CONTROL_POLICY_ID
    assert FAILURE_CONTROL_EXTERNAL_MAIN_DEPENDENCIES
    assert ModeBLocalhostClient
    assert ModeBVerticalSliceError
    assert run_mode_b_vertical_slice
    assert validate_mode_b_vertical_slice_evidence
    assert ConsumerInvalidationError
    assert build_consumer_invalidation_decision
    assert validate_consumer_invalidation_decision
    assert RecoveryError
    assert build_recovery_evidence
    assert validate_recovery_evidence
    assert simulate_kill_at_boundary
    assert RECOVERY_POLICY_ID
    assert RECOVERY_EXTERNAL_MAIN_DEPENDENCIES
    assert append_bridge_journal_event
    assert checkpoint_bridge_journal
    assert validate_bridge_journal_history
    assert reconstruct_bridge_journal_state
    assert validate_bridge_journal_reconstruction_evidence
    assert JOURNAL_POLICY_ID
    assert verify_operational_invalidation_event
    assert evaluate_operational_certificate_at_use
    assert MaskFactoryAdapter
    assert AdoptionReceiptMatrixError
    assert BridgeJournalError
    assert CapabilityQualificationError
    assert CrosswalkError
    assert ExternalAdapterConformanceError
    assert FeedbackIntakeError
    assert FeedbackIntakeLedger
    assert intake_bridge_feedback
    assert validate_feedback_intake_evidence
    assert OperationalInvalidationError
    assert TransformValidationError
    assert UseEligibilityError
    assert FIXTURE_MAIN_AUTHORITY_KIND
    assert FIXTURE_MAIN_CONSUMER_KIND
    assert SYNTHETIC_MAIN_GIT_COMMIT
    assert materialize_fixture_main
    assert run_fixture_main_producer_verify
    assert load_fixture_main_binding
    assert observation_from_fixture_main_binding
    assert FixtureMainError
    assert FixtureMainBindingError


def test_external_supervision_producers_package_surface() -> None:
    assert ExternalSupervisionProducerError
    assert produce_project_contained_evidence


def test_autonomy_package_exports_operational_repair_contracts() -> None:
    assert DurableRepairExecutor
    assert LiveRepairProposal
    assert OperationalRepairError
    assert OperationalRepairResult
