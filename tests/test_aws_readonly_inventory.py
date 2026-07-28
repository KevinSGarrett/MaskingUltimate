from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from tools.inventory_aws_readonly import (
    AwsCallError,
    _operation,
    build_inventory,
    discover_bucket_names,
    main,
)

ACCOUNT = "123456789012"
ARN = "arn:aws:sts::123456789012:assumed-role/MaskFactoryAudit/session"
BUCKET = "private-maskfactory-model-cache"
INSTANCE = "i-0123456789abcdef0"
VOLUME = "vol-0123456789abcdef0"


def fixture_runner(args: Sequence[str]) -> dict[str, Any]:
    operation = tuple(args[:2])
    if operation == ("sts", "get-caller-identity"):
        return {"Account": ACCOUNT, "Arn": ARN, "UserId": "private-user-id"}
    if operation == ("ec2", "describe-regions"):
        return {
            "Regions": [
                {"RegionName": "us-east-1", "OptInStatus": "opt-in-not-required"},
                {"RegionName": "us-west-2", "OptInStatus": "not-opted-in"},
            ]
        }
    if operation == ("ec2", "describe-instances"):
        return {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": INSTANCE,
                            "State": {"Name": "stopped"},
                            "InstanceType": "g5.2xlarge",
                            "LaunchTime": "2026-07-01T00:00:00Z",
                            "Placement": {"AvailabilityZone": "us-east-1a"},
                            "ImageId": "ami-private",
                            "BlockDeviceMappings": [{"Ebs": {"VolumeId": VOLUME}}],
                            "Tags": [{"Key": "Name", "Value": "private-name"}],
                        }
                    ]
                }
            ]
        }
    if operation == ("ec2", "describe-volumes"):
        return {
            "Volumes": [
                {
                    "VolumeId": VOLUME,
                    "Size": 1024,
                    "State": "in-use",
                    "VolumeType": "gp3",
                    "CreateTime": "2026-07-01T00:00:00Z",
                    "AvailabilityZone": "us-east-1a",
                    "Encrypted": True,
                    "Attachments": [{"InstanceId": INSTANCE}],
                }
            ]
        }
    if operation == ("ec2", "describe-images"):
        return {
            "Images": [
                {
                    "ImageId": "ami-private",
                    "Name": "private-image-name",
                    "State": "available",
                    "CreationDate": "2026-07-01T00:00:00Z",
                }
            ]
        }
    if operation == ("ec2", "describe-snapshots"):
        return {"Snapshots": []}
    if operation == ("s3api", "list-buckets"):
        return {"Buckets": [{"Name": BUCKET, "CreationDate": "2026-07-01T00:00:00Z"}]}
    if operation == ("s3api", "get-bucket-location"):
        return {"LocationConstraint": None}
    if operation == ("s3api", "list-objects-v2"):
        return {
            "Contents": [
                {
                    "Key": "models/example/model.safetensors",
                    "Size": 4096,
                    "LastModified": "2026-07-02T00:00:00Z",
                    "ETag": '"etag"',
                    "StorageClass": "STANDARD",
                }
            ]
        }
    raise AssertionError(args)


def test_inventory_is_read_only_and_redacts_identifiers() -> None:
    private, redacted = build_inventory(fixture_runner)

    assert private["account"] == ACCOUNT
    assert private["s3"][0]["name"] == BUCKET
    assert redacted["authority"]["inventory_only"] is True
    assert redacted["authority"]["mutating_calls_attempted"] is False
    assert redacted["regions"]["inventoried"] == ["us-east-1"]
    assert redacted["ec2"][0]["accessibility"]["snapshots"] is True
    assert redacted["ec2"][0]["instances"]["states"] == {"stopped": 1}
    assert redacted["ec2"][0]["volumes"]["total_gib"] == 1024
    assert redacted["s3"][0]["object_count"] == 1
    assert redacted["s3"][0]["total_bytes"] == 4096
    serialized = json.dumps(redacted)
    for secret_identifier in (ACCOUNT, ARN, BUCKET, INSTANCE, VOLUME, "private-name"):
        assert secret_identifier not in serialized


def test_non_allowlisted_operation_is_refused_before_execution() -> None:
    with pytest.raises(ValueError, match="not read-only allowlisted"):
        _operation(["s3api", "put-object"])


def test_access_limitations_are_typed_and_do_not_leak_messages() -> None:
    def denied_runner(args: Sequence[str]) -> dict[str, Any]:
        if tuple(args[:2]) == ("ec2", "describe-images"):
            raise AwsCallError(
                "ec2 describe-images", "UnauthorizedOperation", "private resource detail"
            )
        return fixture_runner(args)

    private, redacted = build_inventory(denied_runner)

    assert private["access_limitations"][0]["error_code"] == "UnauthorizedOperation"
    assert redacted["access_limitations"][0]["error_code"] == "UnauthorizedOperation"
    assert "private resource detail" not in json.dumps(redacted)
    assert any(
        row["operation"] == "describe-images" and row["status"] == "inaccessible"
        for row in redacted["call_evidence"]
    )


def test_main_writes_private_and_redacted_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "tools.inventory_aws_readonly.aws_cli_json",
        fixture_runner,
    )
    private_path = tmp_path / "private.json"
    redacted_path = tmp_path / "redacted.json"

    assert (
        main(
            [
                "--private-output",
                str(private_path),
                "--redacted-output",
                str(redacted_path),
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "pass"
    assert private_path.is_file()
    assert redacted_path.is_file()
    assert json.loads(redacted_path.read_text(encoding="utf-8"))["private_inventory"]["sha256"]


def test_explicit_region_is_probed_when_region_listing_is_denied() -> None:
    def denied_regions(args: Sequence[str]) -> dict[str, Any]:
        if tuple(args[:2]) == ("ec2", "describe-regions"):
            raise AwsCallError("ec2 describe-regions", "UnauthorizedOperation", "private detail")
        return fixture_runner(args)

    private, redacted = build_inventory(
        denied_regions,
        requested_regions=["us-east-1"],
    )

    assert private["inventoried_regions"] == ["us-east-1"]
    assert redacted["regions"]["listing_accessible"] is False
    assert redacted["regions"]["inventoried"] == ["us-east-1"]
    assert redacted["completeness"]["all_enabled_regions_inventoried"] is False
    assert any(
        row["error_code"] == "REGION_ENABLEMENT_UNVERIFIED"
        for row in redacted["access_limitations"]
    )


def test_known_bucket_is_probed_when_bucket_listing_is_denied() -> None:
    def denied_buckets(args: Sequence[str]) -> dict[str, Any]:
        if tuple(args[:2]) == ("s3api", "list-buckets"):
            raise AwsCallError("s3api list-buckets", "AccessDenied", "private detail")
        return fixture_runner(args)

    private, redacted = build_inventory(
        denied_buckets,
        requested_buckets=[BUCKET],
    )

    assert private["s3"][0]["name"] == BUCKET
    assert redacted["s3"][0]["object_count"] == 1
    assert redacted["s3"][0]["objects_accessible"] is True
    assert BUCKET not in json.dumps(redacted)


def test_missing_known_bucket_is_not_reported_as_observed_empty() -> None:
    def missing_bucket(args: Sequence[str]) -> dict[str, Any]:
        if tuple(args[:2]) == ("s3api", "list-buckets"):
            raise AwsCallError("s3api list-buckets", "AccessDenied", "private detail")
        if tuple(args[:2]) in {
            ("s3api", "get-bucket-location"),
            ("s3api", "list-objects-v2"),
        }:
            raise AwsCallError("s3api inventory", "NoSuchBucket", "private detail")
        return fixture_runner(args)

    _, redacted = build_inventory(
        missing_bucket,
        requested_buckets=[BUCKET],
    )

    assert redacted["s3"][0]["object_count"] == 0
    assert redacted["s3"][0]["objects_accessible"] is False
    assert redacted["completeness"]["all_requested_s3_object_listings_accessible"] is False


def test_known_bucket_discovery_records_only_document_hash(tmp_path: Path) -> None:
    document = tmp_path / "ops.md"
    document.write_text(f"governed source: s3://{BUCKET}/models/\n", encoding="utf-8")

    buckets, sources = discover_bucket_names([document])

    assert buckets == [BUCKET]
    assert sources[0]["bucket_reference_count"] == "1"
    assert BUCKET not in json.dumps(sources)
