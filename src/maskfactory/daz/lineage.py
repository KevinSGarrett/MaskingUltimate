"""Transactional DAZ ingestion, descendant queries, and revocation propagation."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..synthetic_manifest import require_valid_synthetic_manifest
from .control import DazControlError, DazErrorCode
from .package_qc import validate_adapted_package_qc_report
from .s00_adapter import validate_s00_adapter_report

AUTHORITY_FIELDS = {
    "recipe": "recipe_sha256",
    "asset_registry": "asset_registry_snapshot_sha256",
    "operating_profile": "operating_profile_snapshot_sha256",
    "registry": "registry_snapshot_sha256",
    "runtime": "runtime_snapshot_sha256",
    "script_bundle": "script_bundle_sha256",
    "renderer": "renderer_snapshot_sha256",
    "asset_snapshot": "asset_snapshot_sha256",
    "mapping": "mapping_set_sha256",
    "pass_profile": "pass_profile_sha256",
}
DOWNSTREAM_TYPES = frozenset({"dataset_snapshot", "training_run", "model"})
PARENT_TYPES_BY_CHILD = {
    "dataset_snapshot": frozenset({"package"}),
    "training_run": frozenset({"dataset_snapshot"}),
    "model": frozenset({"training_run"}),
}
USABLE_STATES = frozenset({"active", "ingested"})


def ingest_adapted_scene(
    database: Path,
    adapted_root: Path,
    adapter_report: Mapping[str, Any],
    qa_report: Mapping[str, Any],
    *,
    timestamp: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Transactionally register a QA-approved adapted scene and all authority edges."""

    validate_s00_adapter_report(adapter_report)
    validate_adapted_package_qc_report(qa_report)
    if (
        qa_report["adapter_report_id"] != adapter_report["report_id"]
        or qa_report["adapter_report_sha256"] != adapter_report["report_sha256"]
        or qa_report["summary"]["passed"] is not True
        or qa_report["summary"]["freeze_eligible"] is not True
    ):
        raise _error("ingest requires an exact passing adapted-package QA report", adapter_report)
    root = Path(adapted_root).resolve(strict=True)
    manifests = []
    for row in adapter_report["packages"]:
        package = root / row["relative_root"]
        manifest_path = package / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        require_valid_synthetic_manifest(manifest)
        if (
            manifest["package_id"] != row["maskfactory_package_id"]
            or manifest["package_sha256"] != row["manifest_sha256"]
            or _tree_digest(package) != row["output_tree_sha256"]
        ):
            raise _error("adapted package changed after QA", adapter_report)
        manifests.append(manifest)
    manifest_set_sha = _sha(
        [
            {"package_id": row["package_id"], "package_sha256": row["package_sha256"]}
            for row in manifests
        ]
    )
    created_at = timestamp or _utc_now()
    ingest_seed = {
        "adapter_report_sha256": adapter_report["report_sha256"],
        "qa_report_sha256": qa_report["report_sha256"],
        "manifest_set_sha256": manifest_set_sha,
    }
    ingest_id = f"dazi_{_sha(ingest_seed)[:24]}"
    connection = _connect(database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        _require_control_authorities(connection, adapter_report)
        existing_ingest = connection.execute(
            "SELECT payload_json FROM ingest_records WHERE ingest_id=?", (ingest_id,)
        ).fetchone()
        if existing_ingest is not None:
            unusable = connection.execute(
                "SELECT COUNT(*) FROM lineage_entities WHERE ((entity_type='scene' AND entity_id=?) OR (entity_type='package' AND entity_id IN (SELECT package_id FROM package_exports WHERE scene_id=?))) AND state NOT IN ('active','ingested')",
                (adapter_report["scene_id"], adapter_report["scene_id"]),
            ).fetchone()[0]
            if unusable:
                raise _error("ingest record or package has been revoked", adapter_report)
            connection.rollback() if dry_run else connection.commit()
            return json.loads(existing_ingest[0])
        lineage = manifests[0]["synthetic_lineage"]
        authority_refs = []
        for entity_type, field in AUTHORITY_FIELDS.items():
            value = lineage[field]
            entity_id = f"{entity_type}_{value[:24]}"
            _ensure_entity(
                connection, entity_type, entity_id, value, "active", {"sha256": value}, created_at
            )
            authority_refs.append((entity_type, entity_id, value))
        certificate_id = manifests[0]["mask_authority"]["certificate_id"]
        certificate_sha = manifests[0]["mask_authority"]["certificate_sha256"]
        _ensure_entity(
            connection,
            "certificate",
            certificate_id,
            certificate_sha,
            "active",
            {"scope": "scene_and_packages"},
            created_at,
        )
        ontology_id = manifests[0]["ontology"]["name"]
        ontology_sha = manifests[0]["ontology"]["snapshot_sha256"]
        _ensure_entity(
            connection,
            "ontology",
            ontology_id,
            ontology_sha,
            "active",
            manifests[0]["ontology"],
            created_at,
        )
        authority_refs.append(("ontology", ontology_id, ontology_sha))
        scene_id = adapter_report["scene_id"]
        _ensure_entity(
            connection,
            "scene",
            scene_id,
            adapter_report["report_sha256"],
            "ingested",
            {
                "adapter_report_id": adapter_report["report_id"],
                "qa_report_id": qa_report["report_id"],
                "image_id": adapter_report["image_id"],
                "scene_family_id": adapter_report["scene_family_id"],
            },
            created_at,
        )
        for parent_type, parent_id, parent_sha in authority_refs:
            _ensure_edge(
                connection,
                parent_type,
                parent_id,
                "certificate",
                certificate_id,
                "binds_certificate",
                parent_sha,
                created_at,
            )
        _ensure_edge(
            connection,
            "certificate",
            certificate_id,
            "scene",
            scene_id,
            "accepts_scene",
            certificate_sha,
            created_at,
        )
        package_ids = []
        for manifest in manifests:
            package_id = manifest["package_id"]
            package_ids.append(package_id)
            _ensure_entity(
                connection,
                "package",
                package_id,
                manifest["package_sha256"],
                "ingested",
                manifest,
                created_at,
            )
            _ensure_edge(
                connection,
                "scene",
                scene_id,
                "package",
                package_id,
                "exports",
                adapter_report["report_sha256"],
                created_at,
            )
            _insert_exact(
                connection,
                "package_exports",
                "package_id",
                package_id,
                (package_id, scene_id, "ingested", _json(manifest)),
            )
        record = {
            "ingest_id": ingest_id,
            "scene_id": scene_id,
            "adapter_report_id": adapter_report["report_id"],
            "qa_report_id": qa_report["report_id"],
            "manifest_set_sha256": manifest_set_sha,
            "package_ids": package_ids,
            "created_at": created_at,
        }
        _insert_exact(
            connection,
            "ingest_records",
            "ingest_id",
            ingest_id,
            (
                ingest_id,
                scene_id,
                adapter_report["report_id"],
                qa_report["report_id"],
                manifest_set_sha,
                created_at,
                _json(record),
            ),
        )
        _append_event(
            connection,
            f"evt_{ingest_id[5:]}",
            created_at,
            "package.ingested",
            "scene",
            scene_id,
            record,
        )
        connection.rollback() if dry_run else connection.commit()
        return record
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def register_downstream_artifact(
    database: Path,
    entity_type: str,
    entity_id: str,
    content_sha256: str,
    parents: Iterable[tuple[str, str]],
    payload: Mapping[str, Any],
    *,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Register an immutable downstream snapshot/run/model only from usable parents."""

    if entity_type not in DOWNSTREAM_TYPES or not _is_sha(content_sha256):
        raise _error("downstream artifact identity is invalid")
    supplied_parents = tuple(parents)
    parent_refs = tuple(sorted(set(supplied_parents)))
    if not parent_refs:
        raise _error("downstream artifact requires at least one parent")
    if len(parent_refs) != len(supplied_parents):
        raise _error("downstream artifact contains duplicate parents")
    if any(parent_type not in PARENT_TYPES_BY_CHILD[entity_type] for parent_type, _ in parent_refs):
        raise _error(f"invalid lineage edge for {entity_type}")
    created_at = timestamp or _utc_now()
    connection = _connect(database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        for parent_type, parent_id in parent_refs:
            row = connection.execute(
                "SELECT content_sha256,state FROM lineage_entities WHERE entity_type=? AND entity_id=?",
                (parent_type, parent_id),
            ).fetchone()
            if row is None or row[1] not in USABLE_STATES:
                raise _error(f"parent is missing or revoked: {parent_type}:{parent_id}")
        entity_payload = {
            "artifact": dict(payload),
            "parents": [
                {"entity_type": parent_type, "entity_id": parent_id}
                for parent_type, parent_id in parent_refs
            ],
        }
        _ensure_entity(
            connection, entity_type, entity_id, content_sha256, "active", entity_payload, created_at
        )
        for parent_type, parent_id in parent_refs:
            parent_sha = connection.execute(
                "SELECT content_sha256 FROM lineage_entities WHERE entity_type=? AND entity_id=?",
                (parent_type, parent_id),
            ).fetchone()[0]
            _ensure_edge(
                connection,
                parent_type,
                parent_id,
                entity_type,
                entity_id,
                "derives",
                parent_sha,
                created_at,
            )
            if entity_type == "dataset_snapshot" and parent_type == "package":
                connection.execute(
                    "INSERT OR IGNORE INTO dataset_membership(dataset_id,package_id,split) VALUES (?,?,?)",
                    (entity_id, parent_id, "train"),
                )
        connection.commit()
        return {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "content_sha256": content_sha256,
            "parents": [{"entity_type": a, "entity_id": b} for a, b in parent_refs],
            "state": "active",
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def query_descendants(database: Path, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
    """Return every unique transitive descendant in deterministic depth/type/ID order."""

    connection = _connect(database, readonly=True)
    try:
        root = connection.execute(
            "SELECT 1 FROM lineage_entities WHERE entity_type=? AND entity_id=?",
            (entity_type, entity_id),
        ).fetchone()
        if root is None:
            raise _error(f"lineage root is missing: {entity_type}:{entity_id}")
        rows = connection.execute(
            """
            WITH RECURSIVE descendants(entity_type,entity_id,depth) AS (
              SELECT child_type,child_id,1 FROM lineage_edges WHERE parent_type=? AND parent_id=?
              UNION
              SELECT e.child_type,e.child_id,d.depth+1
              FROM lineage_edges e JOIN descendants d
                ON e.parent_type=d.entity_type AND e.parent_id=d.entity_id
            )
            SELECT d.entity_type,d.entity_id,MIN(d.depth),le.content_sha256,le.state
            FROM descendants d JOIN lineage_entities le USING(entity_type,entity_id)
            GROUP BY d.entity_type,d.entity_id,le.content_sha256,le.state
            ORDER BY MIN(d.depth),d.entity_type,d.entity_id
            """,
            (entity_type, entity_id),
        ).fetchall()
        return [
            {
                "entity_type": row[0],
                "entity_id": row[1],
                "depth": row[2],
                "content_sha256": row[3],
                "state": row[4],
            }
            for row in rows
        ]
    finally:
        connection.close()


def revoke_lineage(
    database: Path,
    root_type: str,
    root_id: str,
    root_sha256: str,
    reason_code: str,
    evidence_sha256: str,
    *,
    timestamp: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Revoke one exact authority and transactionally mark all descendants unusable."""

    if not _is_sha(root_sha256) or not _is_sha(evidence_sha256) or not reason_code:
        raise _error("revocation contract is invalid")
    created_at = timestamp or _utc_now()
    seed = {
        "root_type": root_type,
        "root_id": root_id,
        "root_sha256": root_sha256,
        "reason_code": reason_code,
        "evidence_sha256": evidence_sha256,
    }
    revocation_id = f"dazr_{_sha(seed)[:24]}"
    connection = _connect(database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        root = connection.execute(
            "SELECT content_sha256,state FROM lineage_entities WHERE entity_type=? AND entity_id=?",
            (root_type, root_id),
        ).fetchone()
        if root is None or root[0] != root_sha256:
            raise _error("revocation root is missing or hash-rebound")
        existing = connection.execute(
            "SELECT payload_json FROM revocations WHERE revocation_id=?", (revocation_id,)
        ).fetchone()
        if existing is not None:
            connection.rollback()
            return json.loads(existing[0])
        descendants = _query_descendants_connection(connection, root_type, root_id)
        affected = [(root_type, root_id, 0, root_sha256, root[1]), *descendants]
        impacts = []
        for entity_type, entity_id, _depth, _sha256, prior in affected:
            new_state, action = _revoked_state(entity_type)
            impacts.append(
                {
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "prior_state": prior,
                    "new_state": new_state,
                    "action": action,
                }
            )
        payload = {
            "revocation_id": revocation_id,
            **seed,
            "created_at": created_at,
            "impacts": impacts,
        }
        connection.execute(
            "INSERT INTO revocations VALUES (?,?,?,?,?,?,?,?)",
            (
                revocation_id,
                root_type,
                root_id,
                root_sha256,
                reason_code,
                evidence_sha256,
                created_at,
                _json(payload),
            ),
        )
        for impact in impacts:
            entity_type = impact["entity_type"]
            entity_id = impact["entity_id"]
            connection.execute(
                "UPDATE lineage_entities SET state=?,updated_at=? WHERE entity_type=? AND entity_id=?",
                (impact["new_state"], created_at, entity_type, entity_id),
            )
            if entity_type == "package":
                connection.execute(
                    "UPDATE package_exports SET state='revoked' WHERE package_id=?", (entity_id,)
                )
            elif entity_type == "certificate":
                connection.execute(
                    "UPDATE scene_certificates SET status='revoked' WHERE certificate_id=?",
                    (entity_id,),
                )
            elif entity_type == "scene":
                connection.execute(
                    "UPDATE scene_recipes SET state='revoked' WHERE scene_id=?", (entity_id,)
                )
            connection.execute(
                "INSERT INTO revocation_impacts VALUES (?,?,?,?,?,?)",
                (
                    revocation_id,
                    entity_type,
                    entity_id,
                    impact["prior_state"],
                    impact["new_state"],
                    impact["action"],
                ),
            )
        _append_event(
            connection,
            f"evt_{revocation_id[5:]}",
            created_at,
            "lineage.revoked",
            root_type,
            root_id,
            payload,
        )
        connection.rollback() if dry_run else connection.commit()
        return payload
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _query_descendants_connection(connection, entity_type, entity_id):
    return connection.execute(
        """
        WITH RECURSIVE descendants(entity_type,entity_id,depth) AS (
          SELECT child_type,child_id,1 FROM lineage_edges WHERE parent_type=? AND parent_id=?
          UNION
          SELECT e.child_type,e.child_id,d.depth+1 FROM lineage_edges e JOIN descendants d
            ON e.parent_type=d.entity_type AND e.parent_id=d.entity_id
        )
        SELECT d.entity_type,d.entity_id,MIN(d.depth),le.content_sha256,le.state
        FROM descendants d JOIN lineage_entities le USING(entity_type,entity_id)
        GROUP BY d.entity_type,d.entity_id,le.content_sha256,le.state
        ORDER BY MIN(d.depth),d.entity_type,d.entity_id
        """,
        (entity_type, entity_id),
    ).fetchall()


def _require_control_authorities(connection, adapter):
    scene = connection.execute(
        "SELECT state FROM scene_recipes WHERE scene_id=?", (adapter["scene_id"],)
    ).fetchone()
    certificate = connection.execute(
        "SELECT status FROM scene_certificates WHERE certificate_id=? AND scene_id=?",
        (adapter["certificate_id"], adapter["scene_id"]),
    ).fetchone()
    if scene is None or certificate is None or certificate[0] != "accepted":
        raise _error("control database lacks accepted scene/certificate authority", adapter)


def _ensure_entity(connection, entity_type, entity_id, content_sha, state, payload, timestamp):
    if not _is_sha(content_sha):
        raise _error(f"invalid entity hash: {entity_type}:{entity_id}")
    existing = connection.execute(
        "SELECT content_sha256,state,payload_json FROM lineage_entities WHERE entity_type=? AND entity_id=?",
        (entity_type, entity_id),
    ).fetchone()
    encoded = _json(payload)
    if existing is None:
        connection.execute(
            "INSERT INTO lineage_entities VALUES (?,?,?,?,?,?,?)",
            (entity_type, entity_id, content_sha, state, encoded, timestamp, timestamp),
        )
    elif existing != (content_sha, state, encoded):
        raise _error(f"lineage entity conflict: {entity_type}:{entity_id}")


def _ensure_edge(
    connection, parent_type, parent_id, child_type, child_id, relation, evidence, timestamp
):
    existing = connection.execute(
        "SELECT evidence_sha256 FROM lineage_edges WHERE parent_type=? AND parent_id=? AND child_type=? AND child_id=? AND relation=?",
        (parent_type, parent_id, child_type, child_id, relation),
    ).fetchone()
    if existing is None:
        connection.execute(
            "INSERT INTO lineage_edges VALUES (?,?,?,?,?,?,?)",
            (parent_type, parent_id, child_type, child_id, relation, evidence, timestamp),
        )
    elif existing[0] != evidence:
        raise _error(
            f"lineage edge evidence conflict: {parent_type}:{parent_id}->{child_type}:{child_id}"
        )


def _insert_exact(connection, table, key_name, key, values):
    existing = connection.execute(f"SELECT * FROM {table} WHERE {key_name}=?", (key,)).fetchone()
    if existing is None:
        placeholders = ",".join("?" for _ in values)
        connection.execute(f"INSERT INTO {table} VALUES ({placeholders})", values)
    elif tuple(existing) != tuple(values):
        raise _error(f"immutable {table} conflict: {key}")


def _append_event(connection, event_id, timestamp, event_type, entity_type, entity_id, data):
    existing = connection.execute(
        "SELECT data_json FROM events WHERE event_id=?", (event_id,)
    ).fetchone()
    encoded = _json(data)
    if existing is None:
        connection.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?,?)",
            (event_id, timestamp, event_type, entity_type, entity_id, None, None, encoded),
        )
    elif existing[0] != encoded:
        raise _error(f"immutable event conflict: {event_id}")


def _revoked_state(entity_type):
    if entity_type == "dataset_snapshot":
        return "excluded", "exclude_from_future_snapshots"
    if entity_type in {"training_run", "model"}:
        return "affected", "mark_affected_no_new_use"
    return "revoked", "prevent_new_use"


def _connect(path: Path, readonly: bool = False) -> sqlite3.Connection:
    database = Path(path)
    target = f"file:{database}?mode=ro" if readonly else str(database)
    connection = sqlite3.connect(target, uri=readonly, timeout=10)
    connection.execute("PRAGMA foreign_keys=ON")
    if readonly:
        connection.execute("PRAGMA query_only=ON")
    return connection


def _tree_digest(root: Path) -> str:
    records = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": path.stat().st_size,
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]
    return _sha(records)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _is_sha(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _error(reason: str, document: Mapping[str, Any] | None = None) -> DazControlError:
    entity_ids = (str(document.get("scene_id")),) if document and document.get("scene_id") else ()
    return DazControlError(DazErrorCode.STATE_DATABASE_INVALID, reason, entity_ids=entity_ids)
