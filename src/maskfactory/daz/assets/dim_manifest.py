"""Privacy-safe, deterministic parser for DAZ Install Manager DSX manifests.

Official contract:
https://docs.daz3d.com/public/software/install_manager/referenceguide/tech_articles/install_manifest/start
https://docs.daz3d.com/public/software/install_manager/referenceguide/tech_articles/package_manifest/start
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from ...validation import ArtifactValidationError, require_valid_document

MAX_MANIFEST_BYTES = 16 * 1024 * 1024
SUPPORTED_ROOT_VERSION = "0.1"
ROOT_TAG = "DAZInstallManifest"
ENTRY_TAGS = ("File", "Application", "Desktop", "AppMenu")
SENSITIVE_SCALARS = frozenset(
    {"UserInstallAccount", "UserInstallPath", "UserProgramDataPath", "UserAppDataPath"}
)
KNOWN_SCALARS = frozenset(
    {
        "GlobalID",
        "MetadataGlobalID",
        "SmartContent",
        "ProductName",
        "ProductStoreIDX",
        "ProductFileGuid",
        "InstallTypes",
        "ProductTags",
        "ArchiveDate",
        "InstallerDate",
        "UserInstallAccount",
        "UserOrderDate",
        "UserInstallDate",
        "InstalledSize",
        "UserInstallPath",
        "UserProgramDataPath",
        "UserAppDataPath",
    }
)
GUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
STORE_ID_PATTERN = re.compile(r"^(?P<sku>[0-9]+)-(?P<download>[0-9]+)$")
EXPECTED_INSTALL_ROOT = os.path.normcase(
    os.path.normpath(r"F:\DAZ\03_content\libraries\MaskFactory_DAZ_Library")
)


class DimManifestError(ValueError):
    """One stable refusal to interpret an unsafe or ambiguous DSX manifest."""

    def __init__(self, reason_code: str, reason: str) -> None:
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(f"{reason_code}: {reason}")


@dataclass(frozen=True)
class DimManifestEntry:
    element: str
    target: str | None
    action: str | None
    value: str
    canonical_value: str
    attributes: Mapping[str, str]
    safe_relative_path: bool
    executes: bool
    elevated: bool


@dataclass(frozen=True)
class DimInstallManifest:
    manifest_name: str
    manifest_sha256: str
    root_version: str
    global_id: str
    metadata_global_id: str | None
    product_name: str
    product_store_id: str | None
    store_sku: str | None
    store_download_id: str | None
    product_file_guid: str | None
    smart_content: bool | None
    install_types: tuple[str, ...]
    product_tags: tuple[str, ...]
    installed_size: int | None
    install_root_state: str
    install_root_fingerprint: str | None
    account_field_present: bool
    entries: tuple[DimManifestEntry, ...]
    unknown_elements: Mapping[str, int]
    warnings: tuple[str, ...]

    @property
    def product_id(self) -> str:
        identity = (
            f"daz_store\0{self.store_sku}" if self.store_sku else f"daz_guid\0{self.global_id}"
        )
        return "prd_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]

    @property
    def package_id(self) -> str:
        archive_identity = self.product_file_guid or self.manifest_sha256
        identity = f"{self.product_id}\0{self.global_id}\0{archive_identity}"
        return "pkg_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]

    def summary(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "package_id": self.package_id,
            "display_name": self.product_name,
            "store_sku": self.store_sku,
            "store_download_id": self.store_download_id,
            "global_id": self.global_id,
            "smart_content": self.smart_content,
            "entry_count": len(self.entries),
            "installed_size": self.installed_size,
            "install_root_state": self.install_root_state,
            "manifest_name": self.manifest_name,
            "manifest_sha256": self.manifest_sha256,
            "warnings": list(self.warnings),
        }


def parse_dim_install_manifest(path: Path) -> DimInstallManifest:
    path = Path(path)
    if path.suffix.casefold() != ".dsx":
        raise DimManifestError("extension_invalid", "DIM install manifest must use .dsx")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise DimManifestError("manifest_unreadable", type(exc).__name__) from exc
    if size <= 0 or size > MAX_MANIFEST_BYTES:
        raise DimManifestError(
            "manifest_size_invalid", f"manifest bytes must be 1..{MAX_MANIFEST_BYTES}"
        )
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DimManifestError("manifest_unreadable", type(exc).__name__) from exc
    upper = raw.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise DimManifestError("xml_declaration_unsafe", "DOCTYPE and ENTITY are prohibited")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise DimManifestError("xml_malformed", str(exc)) from exc
    if root.tag != ROOT_TAG:
        raise DimManifestError("root_invalid", f"expected {ROOT_TAG}, found {root.tag}")
    if set(root.attrib) != {"VERSION"} or root.attrib["VERSION"] != SUPPORTED_ROOT_VERSION:
        raise DimManifestError(
            "version_unsupported", "only closed DIM DSX version 0.1 is supported"
        )

    scalars: dict[str, str] = {}
    entries: list[DimManifestEntry] = []
    unknown: Counter[str] = Counter()
    warnings: set[str] = set()
    sensitive_fields_present: set[str] = set()
    install_path: str | None = None
    for element in root:
        if element.tag in ENTRY_TAGS:
            entries.append(_parse_entry(element))
            continue
        if element.tag not in KNOWN_SCALARS:
            unknown[element.tag] += 1
            warnings.add(f"unknown_element:{element.tag}")
            continue
        if element.tag in scalars:
            raise DimManifestError("duplicate_scalar", f"duplicate {element.tag}")
        if "VALUE" not in element.attrib:
            raise DimManifestError("scalar_value_missing", f"{element.tag} lacks VALUE")
        extra_attributes = sorted(set(element.attrib) - {"VALUE"})
        if extra_attributes:
            warnings.add(f"unexpected_attributes:{element.tag}:{','.join(extra_attributes)}")
        if element.tag in SENSITIVE_SCALARS:
            if element.tag in sensitive_fields_present:
                raise DimManifestError("duplicate_scalar", f"duplicate {element.tag}")
            sensitive_fields_present.add(element.tag)
            if element.tag == "UserInstallPath":
                install_path = element.attrib["VALUE"].strip() or None
            continue
        scalars[element.tag] = element.attrib["VALUE"].strip()

    global_id = scalars.get("GlobalID", "").casefold()
    if not GUID_PATTERN.fullmatch(global_id):
        raise DimManifestError("global_id_invalid", "GlobalID is required and must be a GUID")
    product_name = scalars.get("ProductName", "").strip()
    if not product_name:
        raise DimManifestError("product_name_missing", "ProductName is required")
    metadata_global_id = _optional_guid(scalars.get("MetadataGlobalID"), "MetadataGlobalID")
    product_file_guid = _optional_guid(scalars.get("ProductFileGuid"), "ProductFileGuid")
    product_store_id = scalars.get("ProductStoreIDX") or None
    store_sku: str | None = None
    store_download_id: str | None = None
    if product_store_id:
        matched = STORE_ID_PATTERN.fullmatch(product_store_id)
        if matched:
            store_sku = matched.group("sku")
            store_download_id = matched.group("download")
        else:
            warnings.add("product_store_id_unparsed")
    smart_content = _optional_boolean(scalars.get("SmartContent"), warnings)
    installed_size = _optional_nonnegative_integer(scalars.get("InstalledSize"), warnings)
    install_state, install_fingerprint = _classify_install_root(install_path)
    if install_state != "expected_f":
        warnings.add(f"install_root:{install_state}")
    if any(not entry.safe_relative_path for entry in entries):
        warnings.add("unsafe_entry_path_present")
    if any(entry.executes for entry in entries):
        warnings.add("executable_action_present")
    if any(entry.elevated for entry in entries):
        warnings.add("elevated_action_present")

    return DimInstallManifest(
        manifest_name=path.name,
        manifest_sha256=hashlib.sha256(raw).hexdigest(),
        root_version=root.attrib["VERSION"],
        global_id=global_id,
        metadata_global_id=metadata_global_id,
        product_name=product_name,
        product_store_id=product_store_id,
        store_sku=store_sku,
        store_download_id=store_download_id,
        product_file_guid=product_file_guid,
        smart_content=smart_content,
        install_types=_split_values(scalars.get("InstallTypes")),
        product_tags=_split_values(scalars.get("ProductTags")),
        installed_size=installed_size,
        install_root_state=install_state,
        install_root_fingerprint=install_fingerprint,
        account_field_present="UserInstallAccount" in sensitive_fields_present,
        entries=tuple(entries),
        unknown_elements=dict(sorted(unknown.items())),
        warnings=tuple(sorted(warnings)),
    )


def scan_dim_manifest_archive(source: Path) -> dict[str, Any]:
    source = Path(source)
    if not source.is_dir():
        raise DimManifestError("archive_missing", "DIM Manifest Archive directory is missing")
    manifests: list[DimInstallManifest] = []
    failures: list[dict[str, str]] = []
    candidates = sorted(source.glob("*.dsx"), key=lambda item: (item.name.casefold(), item.name))
    for path in candidates:
        try:
            manifests.append(parse_dim_install_manifest(path))
        except DimManifestError as exc:
            failures.append(
                {
                    "manifest_name": path.name,
                    "reason_code": exc.reason_code,
                    "reason": exc.reason,
                }
            )
    package_ids = [manifest.package_id for manifest in manifests]
    duplicates = sorted(value for value, count in Counter(package_ids).items() if count > 1)
    if duplicates:
        raise DimManifestError(
            "duplicate_package_identity", "duplicate package IDs: " + ", ".join(duplicates)
        )

    entries = tuple(entry for manifest in manifests for entry in manifest.entries)
    source_rows = [
        {"name": manifest.manifest_name, "sha256": manifest.manifest_sha256}
        for manifest in manifests
    ] + [
        {"name": failure["manifest_name"], "failure": failure["reason_code"]}
        for failure in failures
    ]
    source_fingerprint = _canonical_hash(source_rows)
    install_states = Counter(manifest.install_root_state for manifest in manifests)
    element_counts = Counter(entry.element for entry in entries)
    unknown_counts: Counter[str] = Counter()
    for manifest in manifests:
        unknown_counts.update(manifest.unknown_elements)
    products = sorted(
        (manifest.summary() for manifest in manifests),
        key=lambda row: (row["product_id"], row["package_id"]),
    )
    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "snapshot_id": "dim_" + source_fingerprint[:24],
        "source_kind": "daz_install_manager_manifest_archive",
        "source_archive_fingerprint": source_fingerprint,
        "manifest_count": len(candidates),
        "valid_count": len(manifests),
        "invalid_count": len(failures),
        "entry_count": len(entries),
        "entries_by_element": {name: element_counts[name] for name in ENTRY_TAGS},
        "safety": {
            "execute_actions": sum(entry.executes for entry in entries),
            "elevated_actions": sum(entry.elevated for entry in entries),
            "unsafe_paths": sum(not entry.safe_relative_path for entry in entries),
            "account_values_stored": 0,
        },
        "install_root_states": {
            "expected_f": install_states["expected_f"],
            "legacy_non_f": install_states["legacy_non_f"],
            "missing": install_states["missing"],
        },
        "unknown_elements": dict(sorted(unknown_counts.items())),
        "products": products,
        "failures": failures,
    }
    document["canonical_sha256"] = _canonical_hash(document)
    try:
        require_valid_document(document, "daz_dim_manifest_snapshot")
    except ArtifactValidationError as exc:
        raise DimManifestError("snapshot_schema_invalid", str(exc)) from exc
    return document


def publish_dim_snapshot(document: Mapping[str, Any], output_directory: Path) -> dict[str, Any]:
    """Atomically publish one immutable, content-addressed DIM snapshot."""
    try:
        require_valid_document(document, "daz_dim_manifest_snapshot")
    except ArtifactValidationError as exc:
        raise DimManifestError("snapshot_schema_invalid", str(exc)) from exc
    expected_hash = _canonical_hash(
        {key: value for key, value in document.items() if key != "canonical_sha256"}
    )
    if document["canonical_sha256"] != expected_hash:
        raise DimManifestError("snapshot_hash_invalid", "canonical_sha256 does not match document")
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    target = output_directory / f"{document['snapshot_id']}.json"
    encoded = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if target.exists():
        if target.read_bytes() != encoded:
            raise DimManifestError(
                "snapshot_immutable_drift", f"snapshot already differs: {target.name}"
            )
        return {
            "path": str(target),
            "published": False,
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=output_directory)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return {"path": str(target), "published": True, "sha256": hashlib.sha256(encoded).hexdigest()}


def _parse_entry(element: ET.Element) -> DimManifestEntry:
    attributes = {key: value.strip() for key, value in sorted(element.attrib.items())}
    value = attributes.get("VALUE", "")
    action = attributes.get("ACTION")
    action_folded = action.casefold() if action else ""
    executes = action_folded == "execute" or _true(attributes.get("EXECUTEONINSTALL"))
    elevated = _true(attributes.get("EXECUTEELEVATED"))
    canonical = _canonical_member_path(value)
    return DimManifestEntry(
        element=element.tag,
        target=attributes.get("TARGET"),
        action=action,
        value=value,
        canonical_value=canonical,
        attributes=attributes,
        safe_relative_path=_safe_relative_member(value),
        executes=executes,
        elevated=elevated,
    )


def _safe_relative_member(value: str) -> bool:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    return (
        bool(value)
        and bool(path.parts)
        and not path.is_absolute()
        and ":" not in path.parts[0]
        and ".." not in path.parts
    )


def _canonical_member_path(value: str) -> str:
    normalized = "/".join(part for part in value.replace("\\", "/").split("/") if part != "")
    return normalized.casefold()


def _classify_install_root(value: str | None) -> tuple[str, str | None]:
    if not value:
        return "missing", None
    normalized = os.path.normcase(os.path.normpath(value.replace("/", os.sep)))
    fingerprint = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return ("expected_f" if normalized == EXPECTED_INSTALL_ROOT else "legacy_non_f"), fingerprint


def _optional_guid(value: str | None, name: str) -> str | None:
    if not value:
        return None
    normalized = value.casefold()
    if not GUID_PATTERN.fullmatch(normalized):
        raise DimManifestError("guid_invalid", f"{name} is not a GUID")
    uuid.UUID(normalized)
    return normalized


def _optional_boolean(value: str | None, warnings: set[str]) -> bool | None:
    if value is None or value == "":
        return None
    if value.casefold() not in {"true", "false"}:
        warnings.add("smart_content_unparsed")
        return None
    return value.casefold() == "true"


def _optional_nonnegative_integer(value: str | None, warnings: set[str]) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except ValueError:
        warnings.add("installed_size_unparsed")
        return None
    if parsed < 0:
        warnings.add("installed_size_negative")
        return None
    return parsed


def _split_values(value: str | None) -> tuple[str, ...]:
    return tuple(sorted({part.strip() for part in (value or "").split(",") if part.strip()}))


def _true(value: str | None) -> bool:
    return value is not None and value.casefold() == "true"


def _canonical_hash(document: Any) -> str:
    encoded = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "DimInstallManifest",
    "DimManifestEntry",
    "DimManifestError",
    "parse_dim_install_manifest",
    "publish_dim_snapshot",
    "scan_dim_manifest_archive",
]
