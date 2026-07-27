import copy

import pytest

from maskfactory.validation import (
    ArtifactValidationError,
    require_valid_document,
    require_valid_manifest,
    schema_validator,
    validate_manifest,
)
from test_manifest_schema import valid_manifest


def test_schema_loader_is_named_cached_and_refuses_unknown_schema() -> None:
    assert schema_validator("manifest") is schema_validator("manifest")
    with pytest.raises(KeyError, match="unknown schema"):
        schema_validator("made_up")


def test_manifest_invariants_accept_complete_visible_and_explicit_nonvisible_labels() -> None:
    manifest = valid_manifest()
    require_valid_manifest(
        manifest,
        enabled_labels={"left_forearm", "left_breast_projected_region", "left_toes"},
    )


def test_every_enabled_label_must_appear_in_parts() -> None:
    issues = validate_manifest(valid_manifest(), enabled_labels={"left_forearm", "right_forearm"})
    invariant = next(issue for issue in issues if issue.validator == "enabled_labels_complete")
    assert invariant.pointer == "/parts"
    assert "right_forearm" in invariant.message


def test_nonvisible_atomic_mask_file_must_be_null() -> None:
    manifest = valid_manifest()
    manifest["parts"]["left_toes"]["mask_file"] = "masks/left_toes.png"
    issues = validate_manifest(manifest, enabled_labels=manifest["parts"])
    invariant = next(
        issue for issue in issues if issue.validator == "nonvisible_atomic_has_no_mask"
    )
    assert invariant.pointer == "/parts/left_toes/mask_file"


def test_gold_status_requires_qa_pass_and_completed_review() -> None:
    manifest = valid_manifest()
    manifest["qa"]["qa_overall"] = "needs_human"
    manifest["review"]["reviewer"] = None
    issues = validate_manifest(manifest, enabled_labels=manifest["parts"])
    assert {(issue.pointer, issue.validator) for issue in issues} >= {
        ("/qa/qa_overall", "gold_requires_qa_pass"),
        ("/review", "gold_requires_review"),
    }


def test_require_valid_manifest_raises_all_pointer_addressed_findings() -> None:
    manifest = valid_manifest()
    manifest["parts"]["left_toes"]["mask_file"] = "../outside.png"
    with pytest.raises(ArtifactValidationError) as caught:
        require_valid_manifest(manifest, enabled_labels={*manifest["parts"], "right_toes"})
    pointers = {issue.pointer for issue in caught.value.issues}
    assert pointers == {"/parts", "/parts/left_toes/mask_file"}
    assert "/parts/left_toes/mask_file" in str(caught.value)


def test_generic_validator_raises_json_pointer_for_schema_failure() -> None:
    invalid = copy.deepcopy(valid_manifest())
    invalid["source"]["source_width"] = 0
    with pytest.raises(ArtifactValidationError) as caught:
        require_valid_document(invalid, "manifest")
    assert caught.value.issues[0].pointer == "/source/source_width"
