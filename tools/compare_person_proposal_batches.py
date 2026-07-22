"""Compare complete GroundingDINO and YOLO person-proposal shard outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image

from maskfactory.nude_corpus_intake import canonical_sha256, sha256_file, validate_shard
from maskfactory.nude_person_catalog import compare_person_proposal_catalogs


def _artifact_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_output(path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("provider output is not an object")
    sealed = dict(document)
    output_sha256 = sealed.pop("output_sha256", None)
    if output_sha256 != canonical_sha256(sealed):
        raise ValueError("provider output seal mismatch")
    if (
        document.get("authority") != "proposal_boxes_only"
        or document.get("may_write_final_masks") is not False
        or not isinstance(document.get("records"), list)
        or document.get("record_count") != len(document["records"])
    ):
        raise ValueError("provider output authority invalid")
    schema = document.get("schema_version")
    if schema == "maskfactory.groundingdino_batch.v1":
        identity = {
            "provider_id": "groundingdino_person",
            "family_id": "groundingdino",
            "revision": f"{document.get('source_revision')}:{document.get('checkpoint_sha256')}",
        }
    elif schema == "maskfactory.yolo11_person_batch.v1":
        if (
            document.get("provider") != "yolo11m_person"
            or document.get("provider_family") != "yolo"
        ):
            raise ValueError("YOLO provider identity invalid")
        identity = {
            "provider_id": "yolo11m_person",
            "family_id": "yolo",
            "revision": str(document.get("checkpoint_sha256")),
        }
    else:
        raise ValueError("unsupported person provider output schema")
    if not all(isinstance(value, str) and value for value in identity.values()):
        raise ValueError("provider revision invalid")
    return document, identity


def compare_batches(
    *,
    shard_path: Path,
    groundingdino_path: Path,
    yolo_path: Path,
    platform: str,
    iou_min: float = 0.50,
) -> dict[str, Any]:
    shard = validate_shard(
        shard_path,
        expected_lane="reference_and_tournament_input",
        platform=platform,
    )
    outputs = []
    for path in (groundingdino_path, yolo_path):
        document, identity = _load_output(path)
        outputs.append((path, document, identity))
    if len({identity["family_id"] for _, _, identity in outputs}) != 2:
        raise ValueError("independent provider families required")

    expected_ids = shard["ordered_sample_ids"]
    expected_by_id = {sample["sample_id"]: sample for sample in shard["samples"]}
    provider_maps = []
    for path, document, identity in outputs:
        records = document["records"]
        if [record.get("sample_id") for record in records] != expected_ids:
            raise ValueError("provider output shard order mismatch")
        provider_maps.append(
            (
                path,
                document,
                identity,
                {record["sample_id"]: record for record in records},
            )
        )

    comparisons = []
    for sample_id in expected_ids:
        sample = expected_by_id[sample_id]
        source_sha256 = sample.get("source_sha256")
        source_path = Path(str(sample.get("source_path_readonly") or ""))
        if not source_path.is_file() or sha256_file(source_path) != source_sha256:
            raise ValueError(f"comparison source hash mismatch:{sample_id}")
        with Image.open(source_path) as image:
            image_size = list(image.size)
        provider_records = []
        for path, document, identity, records in provider_maps:
            record = records[sample_id]
            if record.get("source_sha256") != source_sha256:
                raise ValueError(f"provider source mismatch:{sample_id}")
            reported_size = record.get("image_size")
            if reported_size is not None and reported_size != image_size:
                raise ValueError(f"provider image size mismatch:{sample_id}")
            provider_records.append(
                {
                    **identity,
                    "artifact_sha256": _artifact_sha256(path),
                    "source_sha256": source_sha256,
                    "proposals": record.get("proposals"),
                }
            )
        comparisons.append(
            compare_person_proposal_catalogs(
                sample_id=sample_id,
                source_sha256=source_sha256,
                image_size=image_size,
                provider_records=provider_records,
                iou_min=iou_min,
            )
        )

    statuses = Counter(comparison["status"] for comparison in comparisons)
    reasons = Counter(
        reason for comparison in comparisons for reason in comparison.get("reasons", [])
    )
    body: dict[str, Any] = {
        "schema_version": "maskfactory.nude_person_catalog_batch.v1",
        "shard_self_sha256": shard["self_sha256"],
        "batch_lane": shard["batch_lane"],
        "platform": shard["platform"],
        "record_count": len(comparisons),
        "provider_artifacts": [
            {
                **identity,
                "path": str(path),
                "artifact_sha256": _artifact_sha256(path),
                "output_sha256": document["output_sha256"],
            }
            for path, document, identity, _ in provider_maps
        ],
        "status_counts": dict(sorted(statuses.items())),
        "reason_counts": dict(sorted(reasons.items())),
        "records": comparisons,
        "authority": "person_catalog_comparison_only",
        "production_mask_authority": False,
        "operational_certificate_issued": False,
    }
    return {**body, "self_sha256": canonical_sha256(body)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nude-shard", type=Path, required=True)
    parser.add_argument("--groundingdino-output", type=Path, required=True)
    parser.add_argument("--yolo-output", type=Path, required=True)
    parser.add_argument("--platform", choices=("local", "runpod"), required=True)
    parser.add_argument("--iou-min", type=float, default=0.50)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = compare_batches(
        shard_path=args.nude_shard,
        groundingdino_path=args.groundingdino_output,
        yolo_path=args.yolo_output,
        platform=args.platform,
        iou_min=args.iou_min,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: report[key]
                for key in ("record_count", "status_counts", "reason_counts", "self_sha256")
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
