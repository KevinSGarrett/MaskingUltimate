"""Create a read-only, privacy-preserving AWS inventory for MaskFactory.

The AWS CLI remains the credential authority.  This tool never reads or emits
credentials and its command allowlist contains only describe/list/get calls.
The private inventory is written outside the repository by default; the
committable evidence contains hashes and aggregate metadata only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0.0"
MAX_S3_ITEMS = 100_000
READ_ONLY_OPERATIONS = frozenset(
    {
        ("sts", "get-caller-identity"),
        ("ec2", "describe-regions"),
        ("ec2", "describe-instances"),
        ("ec2", "describe-volumes"),
        ("ec2", "describe-images"),
        ("ec2", "describe-snapshots"),
        ("s3api", "list-buckets"),
        ("s3api", "get-bucket-location"),
        ("s3api", "list-objects-v2"),
    }
)


class AwsCallError(RuntimeError):
    """A bounded AWS CLI call failed."""

    def __init__(self, operation: str, code: str, message: str) -> None:
        super().__init__(f"{operation}: {code}: {message}")
        self.operation = operation
        self.code = code
        self.message = message


Runner = Callable[[Sequence[str]], dict[str, Any]]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _operation(args: Sequence[str]) -> tuple[str, str]:
    if len(args) < 2:
        raise ValueError("AWS command requires a service and operation")
    operation = (str(args[0]), str(args[1]))
    if operation not in READ_ONLY_OPERATIONS:
        raise ValueError(f"AWS operation is not read-only allowlisted: {' '.join(operation)}")
    return operation


def aws_cli_json(args: Sequence[str]) -> dict[str, Any]:
    """Run one allowlisted AWS CLI call and return its JSON object."""

    service, operation = _operation(args)
    command = ["aws", *args, "--output", "json", "--no-cli-pager"]
    completed = subprocess.run(
        command,
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        env=os.environ.copy(),
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        code = "AWS_CLI_ERROR"
        if "(" in stderr and ")" in stderr:
            code = stderr.split("(", 1)[1].split(")", 1)[0]
        raise AwsCallError(f"{service} {operation}", code, stderr)
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise AwsCallError(f"{service} {operation}", "INVALID_JSON", str(exc)) from exc
    if not isinstance(payload, dict):
        raise AwsCallError(
            f"{service} {operation}", "INVALID_SHAPE", "top-level JSON is not an object"
        )
    return payload


def _call(
    runner: Runner,
    args: Sequence[str],
    calls: list[dict[str, Any]],
    limitations: list[dict[str, str]],
    *,
    scope: str,
) -> dict[str, Any] | None:
    service, operation = _operation(args)
    started = _utc_now()
    try:
        result = runner(args)
    except AwsCallError as exc:
        calls.append(
            {
                "service": service,
                "operation": operation,
                "scope": scope,
                "started_at": started,
                "finished_at": _utc_now(),
                "status": "inaccessible",
                "error_code": exc.code,
            }
        )
        limitations.append(
            {
                "scope": scope,
                "operation": f"{service} {operation}",
                "error_code": exc.code,
            }
        )
        return None
    calls.append(
        {
            "service": service,
            "operation": operation,
            "scope": scope,
            "started_at": started,
            "finished_at": _utc_now(),
            "status": "pass",
        }
    )
    return result


def _tags(raw: Iterable[dict[str, Any]] | None) -> dict[str, str]:
    return {
        str(row.get("Key")): str(row.get("Value", ""))
        for row in raw or []
        if row.get("Key") is not None
    }


def _timestamp_range(values: Iterable[str | None]) -> dict[str, str | None]:
    normalized = sorted(str(value) for value in values if value)
    return {
        "earliest": normalized[0] if normalized else None,
        "latest": normalized[-1] if normalized else None,
    }


def _principal_type(arn: str) -> str:
    resource = arn.rsplit(":", 1)[-1]
    return resource.split("/", 1)[0] if resource else "unknown"


def _private_ec2_region(
    runner: Runner,
    region: str,
    calls: list[dict[str, Any]],
    limitations: list[dict[str, str]],
) -> dict[str, Any]:
    common = ["--region", region]
    instances_doc = _call(
        runner,
        ["ec2", "describe-instances", *common],
        calls,
        limitations,
        scope=f"ec2:{region}:instances",
    )
    volumes_doc = _call(
        runner,
        ["ec2", "describe-volumes", *common],
        calls,
        limitations,
        scope=f"ec2:{region}:volumes",
    )
    images_doc = _call(
        runner,
        ["ec2", "describe-images", "--owners", "self", *common],
        calls,
        limitations,
        scope=f"ec2:{region}:images",
    )
    snapshots_doc = _call(
        runner,
        ["ec2", "describe-snapshots", "--owner-ids", "self", *common],
        calls,
        limitations,
        scope=f"ec2:{region}:snapshots",
    )

    instances: list[dict[str, Any]] = []
    for reservation in (instances_doc or {}).get("Reservations", []):
        for item in reservation.get("Instances", []):
            instances.append(
                {
                    "instance_id": item.get("InstanceId"),
                    "state": (item.get("State") or {}).get("Name"),
                    "instance_type": item.get("InstanceType"),
                    "launch_time": item.get("LaunchTime"),
                    "availability_zone": (item.get("Placement") or {}).get("AvailabilityZone"),
                    "image_id": item.get("ImageId"),
                    "volume_ids": [
                        (mapping.get("Ebs") or {}).get("VolumeId")
                        for mapping in item.get("BlockDeviceMappings", [])
                        if (mapping.get("Ebs") or {}).get("VolumeId")
                    ],
                    "tags": _tags(item.get("Tags")),
                }
            )

    volumes = [
        {
            "volume_id": item.get("VolumeId"),
            "size_gib": item.get("Size"),
            "state": item.get("State"),
            "volume_type": item.get("VolumeType"),
            "create_time": item.get("CreateTime"),
            "availability_zone": item.get("AvailabilityZone"),
            "snapshot_id": item.get("SnapshotId"),
            "encrypted": item.get("Encrypted"),
            "attachments": item.get("Attachments", []),
            "tags": _tags(item.get("Tags")),
        }
        for item in (volumes_doc or {}).get("Volumes", [])
    ]
    images = [
        {
            "image_id": item.get("ImageId"),
            "name": item.get("Name"),
            "state": item.get("State"),
            "creation_date": item.get("CreationDate"),
            "architecture": item.get("Architecture"),
            "root_device_type": item.get("RootDeviceType"),
            "block_device_mappings": item.get("BlockDeviceMappings", []),
            "tags": _tags(item.get("Tags")),
        }
        for item in (images_doc or {}).get("Images", [])
    ]
    snapshots = [
        {
            "snapshot_id": item.get("SnapshotId"),
            "volume_id": item.get("VolumeId"),
            "volume_size_gib": item.get("VolumeSize"),
            "state": item.get("State"),
            "start_time": item.get("StartTime"),
            "encrypted": item.get("Encrypted"),
            "tags": _tags(item.get("Tags")),
        }
        for item in (snapshots_doc or {}).get("Snapshots", [])
    ]
    return {
        "region": region,
        "accessibility": {
            "instances": instances_doc is not None,
            "volumes": volumes_doc is not None,
            "images": images_doc is not None,
            "snapshots": snapshots_doc is not None,
        },
        "instances": instances,
        "volumes": volumes,
        "images": images,
        "snapshots": snapshots,
    }


def _redact_region(region: dict[str, Any]) -> dict[str, Any]:
    instances = region["instances"]
    volumes = region["volumes"]
    images = region["images"]
    snapshots = region["snapshots"]
    return {
        "region": region["region"],
        "accessibility": region["accessibility"],
        "instances": {
            "count": len(instances),
            "states": dict(sorted(Counter(row.get("state") for row in instances).items())),
            "types": dict(sorted(Counter(row.get("instance_type") for row in instances).items())),
            "launch_times": _timestamp_range(row.get("launch_time") for row in instances),
            "id_sha256": sorted(
                _sha256_text(str(row["instance_id"])) for row in instances if row.get("instance_id")
            ),
            "resources": [
                {
                    "id_sha256": _sha256_text(str(row["instance_id"])),
                    "state": row.get("state"),
                    "instance_type": row.get("instance_type"),
                    "launch_time": row.get("launch_time"),
                    "availability_zone": row.get("availability_zone"),
                    "image_id_sha256": (
                        _sha256_text(str(row["image_id"])) if row.get("image_id") else None
                    ),
                    "volume_id_sha256": sorted(
                        _sha256_text(str(volume_id)) for volume_id in row.get("volume_ids", [])
                    ),
                }
                for row in instances
                if row.get("instance_id")
            ],
        },
        "volumes": {
            "count": len(volumes),
            "total_gib": sum(int(row.get("size_gib") or 0) for row in volumes),
            "states": dict(sorted(Counter(row.get("state") for row in volumes).items())),
            "types": dict(sorted(Counter(row.get("volume_type") for row in volumes).items())),
            "create_times": _timestamp_range(row.get("create_time") for row in volumes),
            "id_sha256": sorted(
                _sha256_text(str(row["volume_id"])) for row in volumes if row.get("volume_id")
            ),
            "resources": [
                {
                    "id_sha256": _sha256_text(str(row["volume_id"])),
                    "size_gib": row.get("size_gib"),
                    "state": row.get("state"),
                    "volume_type": row.get("volume_type"),
                    "create_time": row.get("create_time"),
                    "availability_zone": row.get("availability_zone"),
                    "encrypted": row.get("encrypted"),
                    "attached_instance_id_sha256": sorted(
                        _sha256_text(str(attachment["InstanceId"]))
                        for attachment in row.get("attachments", [])
                        if attachment.get("InstanceId")
                    ),
                }
                for row in volumes
                if row.get("volume_id")
            ],
        },
        "images": {
            "count": len(images),
            "states": dict(sorted(Counter(row.get("state") for row in images).items())),
            "creation_dates": _timestamp_range(row.get("creation_date") for row in images),
            "id_sha256": sorted(
                _sha256_text(str(row["image_id"])) for row in images if row.get("image_id")
            ),
            "resources": [
                {
                    "id_sha256": _sha256_text(str(row["image_id"])),
                    "name_sha256": _sha256_text(str(row["name"])) if row.get("name") else None,
                    "state": row.get("state"),
                    "creation_date": row.get("creation_date"),
                    "architecture": row.get("architecture"),
                    "root_device_type": row.get("root_device_type"),
                    "block_device_mapping_count": len(row.get("block_device_mappings", [])),
                }
                for row in images
                if row.get("image_id")
            ],
        },
        "snapshots": {
            "count": len(snapshots),
            "total_volume_gib": sum(int(row.get("volume_size_gib") or 0) for row in snapshots),
            "states": dict(sorted(Counter(row.get("state") for row in snapshots).items())),
            "start_times": _timestamp_range(row.get("start_time") for row in snapshots),
            "id_sha256": sorted(
                _sha256_text(str(row["snapshot_id"])) for row in snapshots if row.get("snapshot_id")
            ),
            "resources": [
                {
                    "id_sha256": _sha256_text(str(row["snapshot_id"])),
                    "volume_id_sha256": (
                        _sha256_text(str(row["volume_id"])) if row.get("volume_id") else None
                    ),
                    "volume_size_gib": row.get("volume_size_gib"),
                    "state": row.get("state"),
                    "start_time": row.get("start_time"),
                    "encrypted": row.get("encrypted"),
                }
                for row in snapshots
                if row.get("snapshot_id")
            ],
        },
    }


def _private_s3(
    runner: Runner,
    calls: list[dict[str, Any]],
    limitations: list[dict[str, str]],
    *,
    requested_buckets: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    buckets_doc = _call(
        runner,
        ["s3api", "list-buckets"],
        calls,
        limitations,
        scope="s3:buckets",
    )
    discovered = {
        str(bucket["Name"]): bucket
        for bucket in (buckets_doc or {}).get("Buckets", [])
        if bucket.get("Name")
    }
    bucket_names = sorted(set(discovered) | set(requested_buckets or ()))
    buckets: list[dict[str, Any]] = []
    for name in bucket_names:
        bucket = discovered.get(name, {})
        if not name:
            continue
        location_doc = _call(
            runner,
            ["s3api", "get-bucket-location", "--bucket", str(name)],
            calls,
            limitations,
            scope=f"s3:{_sha256_text(str(name))}:location",
        )
        objects_doc = _call(
            runner,
            [
                "s3api",
                "list-objects-v2",
                "--bucket",
                str(name),
                "--max-items",
                str(MAX_S3_ITEMS),
            ],
            calls,
            limitations,
            scope=f"s3:{_sha256_text(str(name))}:objects",
        )
        objects = [
            {
                "key": item.get("Key"),
                "size": item.get("Size"),
                "last_modified": item.get("LastModified"),
                "etag": item.get("ETag"),
                "checksum_algorithm": item.get("ChecksumAlgorithm", []),
                "storage_class": item.get("StorageClass"),
            }
            for item in (objects_doc or {}).get("Contents", [])
        ]
        buckets.append(
            {
                "name": name,
                "creation_date": bucket.get("CreationDate"),
                "region": (location_doc or {}).get("LocationConstraint") or "us-east-1",
                "objects": objects,
                "location_accessible": location_doc is not None,
                "objects_accessible": objects_doc is not None,
                "truncated": bool(
                    (objects_doc or {}).get("NextToken") or (objects_doc or {}).get("IsTruncated")
                ),
            }
        )
    return buckets


def _redact_s3_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    objects = bucket["objects"]
    prefix_totals: dict[str, dict[str, int]] = {}
    for item in objects:
        key = str(item.get("key") or "")
        prefix = key.split("/", 1)[0] if "/" in key else "<root>"
        digest = _sha256_text(prefix)
        row = prefix_totals.setdefault(digest, {"objects": 0, "bytes": 0})
        row["objects"] += 1
        row["bytes"] += int(item.get("size") or 0)
    return {
        "bucket_name_sha256": _sha256_text(str(bucket["name"])),
        "creation_date": bucket.get("creation_date"),
        "region": bucket.get("region"),
        "location_accessible": bucket["location_accessible"],
        "objects_accessible": bucket["objects_accessible"],
        "object_count": len(objects),
        "total_bytes": sum(int(item.get("size") or 0) for item in objects),
        "last_modified": _timestamp_range(item.get("last_modified") for item in objects),
        "etag_present_count": sum(bool(item.get("etag")) for item in objects),
        "checksum_metadata_count": sum(bool(item.get("checksum_algorithm")) for item in objects),
        "top_level_prefixes_by_sha256": dict(sorted(prefix_totals.items())),
        "truncated": bucket["truncated"],
    }


def build_inventory(
    runner: Runner = aws_cli_json,
    *,
    requested_regions: Sequence[str] | None = None,
    requested_buckets: Sequence[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(private_inventory, redacted_evidence)``."""

    started_at = _utc_now()
    calls: list[dict[str, Any]] = []
    limitations: list[dict[str, str]] = []
    identity = _call(
        runner,
        ["sts", "get-caller-identity"],
        calls,
        limitations,
        scope="account",
    )
    if identity is None:
        raise AwsCallError("sts get-caller-identity", "AUTHENTICATION_FAILED", "no identity")
    regions_doc = _call(
        runner,
        ["ec2", "describe-regions", "--all-regions"],
        calls,
        limitations,
        scope="regions",
    )
    enabled_regions = sorted(
        row["RegionName"]
        for row in (regions_doc or {}).get("Regions", [])
        if row.get("RegionName") and row.get("OptInStatus") in {"opt-in-not-required", "opted-in"}
    )
    region_listing_accessible = regions_doc is not None
    if requested_regions:
        regions = sorted(set(requested_regions))
        for region in regions:
            if not region_listing_accessible:
                limitations.append(
                    {
                        "scope": f"ec2:{region}",
                        "operation": "region selection",
                        "error_code": "REGION_ENABLEMENT_UNVERIFIED",
                    }
                )
            elif region not in enabled_regions:
                limitations.append(
                    {
                        "scope": f"ec2:{region}",
                        "operation": "region selection",
                        "error_code": "REGION_NOT_ENABLED_OR_UNKNOWN",
                    }
                )
    else:
        regions = enabled_regions

    private_regions = [
        _private_ec2_region(runner, region, calls, limitations) for region in regions
    ]
    private_buckets = _private_s3(
        runner,
        calls,
        limitations,
        requested_buckets=requested_buckets,
    )
    source_path = Path(__file__).resolve()
    account = str(identity.get("Account") or "")
    arn = str(identity.get("Arn") or "")
    private = {
        "schema_version": SCHEMA_VERSION,
        "started_at": started_at,
        "finished_at": _utc_now(),
        "account": account,
        "principal_arn": arn,
        "principal_user_id": identity.get("UserId"),
        "enabled_regions": enabled_regions,
        "inventoried_regions": regions,
        "requested_buckets": sorted(set(requested_buckets or ())),
        "ec2": private_regions,
        "s3": private_buckets,
        "access_limitations": limitations,
        "read_only_calls": calls,
    }
    redacted = {
        "schema_version": SCHEMA_VERSION,
        "recorded_at": _utc_now(),
        "scope": "maskfactory_aws_readonly_inventory",
        "authority": {
            "inventory_only": True,
            "mutating_calls_attempted": False,
            "maskfactory_workload_executed_on_ec2": False,
            "credentials_read_or_emitted": False,
            "allowlisted_operations": [
                " ".join(operation) for operation in sorted(READ_ONLY_OPERATIONS)
            ],
        },
        "identity": {
            "account_sha256": _sha256_text(account),
            "principal_arn_sha256": _sha256_text(arn),
            "principal_type": _principal_type(arn),
        },
        "regions": {
            "listing_accessible": region_listing_accessible,
            "enabled_count": len(enabled_regions),
            "inventoried_count": len(regions),
            "inventoried": regions,
        },
        "ec2": [_redact_region(region) for region in private_regions],
        "s3": [_redact_s3_bucket(bucket) for bucket in private_buckets],
        "access_limitations": limitations,
        "call_evidence": calls,
        "completeness": {
            "all_enabled_regions_inventoried": region_listing_accessible
            and regions == enabled_regions,
            "s3_bucket_listing_accessible": not any(
                row["scope"] == "s3:buckets" for row in limitations
            ),
            "s3_object_listings_truncated": any(bucket["truncated"] for bucket in private_buckets),
            "all_requested_s3_object_listings_accessible": all(
                bucket["objects_accessible"] for bucket in private_buckets
            ),
        },
        "tool": {
            "path": "tools/inventory_aws_readonly.py",
            "sha256": _sha256_file(source_path),
        },
        "private_inventory": {
            "committed": False,
            "sha256": None,
        },
    }
    return private, redacted


def _default_private_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return base / "MaskFactory" / "private" / f"aws_inventory_{stamp}.json"


def discover_bucket_names(documents: Sequence[Path]) -> tuple[list[str], list[dict[str, str]]]:
    """Extract literal S3 bucket names without returning them in public evidence."""

    buckets: set[str] = set()
    sources: list[dict[str, str]] = []
    pattern = re.compile(r"s3://([A-Za-z0-9][A-Za-z0-9.-]{1,61}[A-Za-z0-9])")
    for document in documents:
        resolved = document.resolve()
        text = resolved.read_text(encoding="utf-8", errors="replace")
        found = set(pattern.findall(text))
        buckets.update(found)
        sources.append(
            {
                "path": document.as_posix(),
                "sha256": _sha256_file(resolved),
                "bucket_reference_count": str(len(found)),
            }
        )
    return sorted(buckets), sources


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--private-output",
        type=Path,
        help="unredacted local output (defaults outside the repository)",
    )
    parser.add_argument("--redacted-output", type=Path, required=True)
    parser.add_argument(
        "--region",
        action="append",
        default=[],
        help="limit EC2 inventory to an enabled region (repeatable)",
    )
    parser.add_argument(
        "--known-source-document",
        action="append",
        default=[],
        type=Path,
        help="extract known s3:// bucket references from a local governed document",
    )
    args = parser.parse_args(argv)
    private_path = (args.private_output or _default_private_path()).resolve()
    redacted_path = args.redacted_output.resolve()
    requested_buckets, bucket_sources = discover_bucket_names(args.known_source_document)
    private, redacted = build_inventory(
        requested_regions=args.region or None,
        requested_buckets=requested_buckets or None,
    )
    redacted["known_bucket_sources"] = bucket_sources
    _write_json(private_path, private)
    redacted["private_inventory"]["sha256"] = _sha256_file(private_path)
    _write_json(redacted_path, redacted)
    print(
        json.dumps(
            {
                "status": "pass",
                "private_output": str(private_path),
                "private_sha256": redacted["private_inventory"]["sha256"],
                "redacted_output": str(redacted_path),
                "regions": redacted["regions"]["inventoried_count"],
                "buckets": len(redacted["s3"]),
                "limitations": len(redacted["access_limitations"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
