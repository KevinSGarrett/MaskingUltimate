"""Deterministic LV-MHP source-image and per-person annotation identity evidence."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .external_supervision_evidence import publish_immutable_evidence, seal_payload

ANNOTATION_PATTERN = re.compile(r"^(?P<image>\d+)_(?P<count>\d+)_(?P<instance>\d+)\.png$")


class ExternalIdentityError(ValueError):
    """LV-MHP identity metadata is incomplete, ambiguous, or inconsistent."""


def build_lv_mhp_identity_evidence(source_root: Path) -> dict[str, Any]:
    """Prove every image has one complete, unambiguous per-person annotation set."""

    root = Path(source_root).resolve(strict=True)
    content = root / "LV-MHP-v1" if (root / "LV-MHP-v1").is_dir() else root
    images_root = content / "images"
    annotations_root = content / "annotations"
    if not images_root.is_dir() or not annotations_root.is_dir():
        raise ExternalIdentityError("LV-MHP images/annotations directories are missing")

    images: dict[str, Path] = {}
    for path in images_root.iterdir():
        if path.is_symlink() or not path.is_file() or path.suffix.casefold() != ".jpg":
            raise ExternalIdentityError(f"unexpected image entry: {path.name}")
        if path.stem in images:
            raise ExternalIdentityError(f"duplicate image identity: {path.stem}")
        images[path.stem] = path

    annotations: dict[str, list[tuple[int, int, str]]] = {}
    for path in annotations_root.iterdir():
        if path.is_symlink() or not path.is_file():
            raise ExternalIdentityError(f"unexpected annotation entry: {path.name}")
        match = ANNOTATION_PATTERN.fullmatch(path.name)
        if match is None:
            raise ExternalIdentityError(f"malformed annotation identity: {path.name}")
        image_id = match.group("image")
        annotations.setdefault(image_id, []).append(
            (int(match.group("count")), int(match.group("instance")), path.name)
        )

    if set(images) != set(annotations):
        missing_annotations = sorted(set(images) - set(annotations))
        missing_images = sorted(set(annotations) - set(images))
        raise ExternalIdentityError(
            "image/annotation identity sets differ: "
            f"missing_annotations={missing_annotations[:5]} "
            f"missing_images={missing_images[:5]}"
        )

    records: list[dict[str, Any]] = []
    distribution: Counter[int] = Counter()
    annotation_count = 0
    for image_id in sorted(images, key=lambda value: value.encode("ascii")):
        entries = annotations[image_id]
        declared = {entry[0] for entry in entries}
        if len(declared) != 1:
            raise ExternalIdentityError(f"conflicting person counts for image {image_id}")
        person_count = next(iter(declared))
        instances = sorted(entry[1] for entry in entries)
        if person_count < 1 or instances != list(range(1, person_count + 1)):
            raise ExternalIdentityError(
                f"incomplete person identity sequence for image {image_id}: "
                f"declared={person_count} instances={instances}"
            )
        if len({entry[2].casefold() for entry in entries}) != len(entries):
            raise ExternalIdentityError(f"duplicate annotation identity for image {image_id}")
        distribution[person_count] += 1
        annotation_count += len(entries)
        records.append(
            {
                "image_id": image_id,
                "image_path": f"images/{images[image_id].name}",
                "person_count": person_count,
                "instance_ids": instances,
                "annotation_paths": [
                    f"annotations/{entry[2]}" for entry in sorted(entries, key=lambda item: item[1])
                ],
            }
        )

    evidence: dict[str, Any] = {
        "schema_version": "1.0.0",
        "artifact_type": "external_supervision_identity_evidence",
        "source": "lv_mhp_v1",
        "gate": "instance_identity_validated",
        "status": "PASS",
        "identity_rule": "annotation_<image>_<declared_person_count>_<one_based_instance>.png",
        "image_count": len(records),
        "annotation_count": annotation_count,
        "person_count_distribution": {str(key): distribution[key] for key in sorted(distribution)},
        "records": records,
    }
    evidence["seal_sha256"] = seal_payload(evidence)
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    evidence = build_lv_mhp_identity_evidence(args.source_root)
    file_sha256 = publish_immutable_evidence(evidence, args.output)
    print(
        json.dumps(
            {
                "status": "PASS",
                "source": "lv_mhp_v1",
                "image_count": evidence["image_count"],
                "annotation_count": evidence["annotation_count"],
                "evidence_path": str(args.output.resolve()),
                "evidence_file_sha256": file_sha256,
                "evidence_seal_sha256": evidence["seal_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ExternalIdentityError", "build_lv_mhp_identity_evidence"]
