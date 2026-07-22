#!/usr/bin/env python3
"""Read-only, sanitized inventory for CAA lifecycle/package reconciliation."""

from __future__ import annotations

import argparse
import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

RUNPOD_REST = "https://rest.runpod.io/v1"

REMOTE_AUDIT = r"""
import hashlib, json, pathlib, sqlite3

workspace = pathlib.Path('/workspace/maskfactory')

def seal(values):
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def database(path):
    result = {'path': path.relative_to(workspace).as_posix(), 'bytes': path.stat().st_size, 'tables': []}
    connection = sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True)
    try:
        names = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        for name in names:
            quoted = '"' + name.replace('"', '""') + '"'
            columns = [row[1] for row in connection.execute(f'PRAGMA table_info({quoted})')]
            count = int(connection.execute(f'SELECT COUNT(*) FROM {quoted}').fetchone()[0])
            table = {'name': name, 'row_count': count, 'columns': columns}
            for field in ('status', 'truth_tier', 'calibrated_status', 'calibrated_truth_tier'):
                if field in columns:
                    field_q = '"' + field + '"'
                    rows = connection.execute(f'SELECT {field_q}, COUNT(*) FROM {quoted} GROUP BY {field_q} ORDER BY {field_q}').fetchall()
                    if len(rows) <= 32:
                        table[f'{field}_counts'] = {str(key): int(value) for key, value in rows}
            result['tables'].append(table)
    finally:
        connection.close()
    result['schema_sha256'] = seal(result['tables'])
    return result

def package_root(path):
    manifests = sorted(path.rglob('manifest.json')) if path.is_dir() else []
    rows = []
    lineage_key_counts = {}
    for manifest in manifests:
        try:
            document = json.loads(manifest.read_text(encoding='utf-8'))
        except Exception as exc:
            rows.append({'path': manifest.relative_to(path).as_posix(), 'error': type(exc).__name__})
            continue
        certification = document.get('certification') if isinstance(document.get('certification'), dict) else {}
        lineage_path = manifest.parent / 'caa_lineage.json'
        lineage = None
        if lineage_path.is_file():
            try:
                lineage = json.loads(lineage_path.read_text(encoding='utf-8'))
                for key in lineage:
                    lineage_key_counts[key] = lineage_key_counts.get(key, 0) + 1
            except Exception:
                lineage = {'_parse_error': True}
        rows.append({
            'path': manifest.relative_to(path).as_posix(),
            'image_id': document.get('image_id'),
            'package_version': document.get('package_version'),
            'truth_tier': document.get('truth_tier'),
            'semantic_bound': bool(certification.get('semantic_alignment_report_sha256')),
            'quorum_bound': bool(certification.get('critic_quorum_sha256')),
            'lineage_present': lineage_path.is_file(),
            'lineage_sha256': hashlib.sha256(lineage_path.read_bytes()).hexdigest() if lineage_path.is_file() else None,
            'lineage_keys': sorted(lineage) if isinstance(lineage, dict) else [],
        })
    return {
        'path': path.relative_to(workspace).as_posix(),
        'exists': path.is_dir(),
        'manifest_count': len(manifests),
        'semantic_bound_count': sum(row.get('semantic_bound', False) for row in rows),
        'quorum_bound_count': sum(row.get('quorum_bound', False) for row in rows),
        'lineage_present_count': sum(row.get('lineage_present', False) for row in rows),
        'lineage_key_counts': dict(sorted(lineage_key_counts.items())),
        'image_id_count': len({row.get('image_id') for row in rows if row.get('image_id')}),
        'inventory_sha256': seal(rows),
    }

def reconciliation():
    database_path = workspace / 'data' / 'maskfactory.sqlite'
    primary_root = workspace / 'data' / 'packages'
    isolated_root = workspace / 'data' / 'packages_caa_iso220'
    connection = sqlite3.connect(f'file:{database_path.as_posix()}?mode=ro', uri=True)
    try:
        image_rows = connection.execute('SELECT image_id, source_sha256, status, package_version FROM images').fetchall()
        truth_rows = connection.execute('SELECT image_id, package_path, truth_tier, certificate_bundle_sha256 FROM package_truth').fetchall()
    finally:
        connection.close()
    image_ids = {str(row[0]) for row in image_rows}
    truth_ids = {str(row[0]) for row in truth_rows}

    def resolve_workspace_path(raw):
        path = pathlib.Path(str(raw))
        return path if path.is_absolute() else workspace / path

    def lineages(root):
        result = {}
        verified_lifecycle = verified_source = verified_winner = 0
        lifecycle_exists = semantic_bound = quorum_bound = both_bound = fully_current = 0
        for path in sorted(root.rglob('caa_lineage.json')) if root.is_dir() else []:
            document = json.loads(path.read_text(encoding='utf-8'))
            image_id = str(document['image_id'])
            result[image_id] = path
            lifecycle = resolve_workspace_path(document['lifecycle_path'])
            source = resolve_workspace_path(document['source_path'])
            winner = resolve_workspace_path(document['winner_mask_path'])
            lifecycle_exists += int(lifecycle.is_file())
            lifecycle_current = lifecycle.is_file() and hashlib.sha256(lifecycle.read_bytes()).hexdigest() == document['lifecycle_sha256']
            source_current = source.is_file() and hashlib.sha256(source.read_bytes()).hexdigest() == document['source_sha256']
            winner_current = winner.is_file() and hashlib.sha256(winner.read_bytes()).hexdigest() == document['winner_mask_sha256']
            verified_lifecycle += int(lifecycle_current)
            verified_source += int(source_current)
            verified_winner += int(winner_current)
            manifests = list(path.parent.rglob('manifest.json'))
            certifications = []
            for manifest in manifests:
                payload = json.loads(manifest.read_text(encoding='utf-8'))
                certifications.append(payload.get('certification') if isinstance(payload.get('certification'), dict) else {})
            has_semantic = any(item.get('semantic_alignment_report_sha256') for item in certifications)
            has_quorum = any(item.get('critic_quorum_sha256') for item in certifications)
            semantic_bound += int(has_semantic)
            quorum_bound += int(has_quorum)
            both_bound += int(has_semantic and has_quorum)
            fully_current += int(lifecycle_current and source_current and winner_current and has_semantic and has_quorum)
        return result, lifecycle_exists, verified_lifecycle, verified_source, verified_winner, semantic_bound, quorum_bound, both_bound, fully_current

    primary, lifecycle_exists, lifecycle_ok, source_ok, winner_ok, semantic_bound, quorum_bound, both_bound, fully_current = lineages(primary_root)
    isolated, isolated_lifecycle_exists, isolated_lifecycle_ok, isolated_source_ok, isolated_winner_ok, isolated_semantic_bound, isolated_quorum_bound, isolated_both_bound, isolated_fully_current = lineages(isolated_root)
    primary_ids = set(primary)
    isolated_ids = set(isolated)
    truth_paths_exist = truth_paths_exist_under_primary = 0
    for _, package_path, _, _ in truth_rows:
        path = resolve_workspace_path(package_path)
        truth_paths_exist += int(path.is_dir())
        truth_paths_exist_under_primary += int((primary_root / str(package_path)).is_dir())
    return {
        'database_image_count': len(image_ids),
        'database_truth_count': len(truth_ids),
        'database_image_id_sha256': seal(sorted(image_ids)),
        'database_truth_id_sha256': seal(sorted(truth_ids)),
        'database_image_truth_exact_match': image_ids == truth_ids,
        'primary_materialized_package_count': len(primary_ids),
        'primary_package_id_sha256': seal(sorted(primary_ids)),
        'primary_matches_database_exactly': primary_ids == image_ids == truth_ids,
        'primary_lifecycle_path_exists_count': lifecycle_exists,
        'primary_lifecycle_hash_verified_count': lifecycle_ok,
        'primary_source_hash_verified_count': source_ok,
        'primary_winner_hash_verified_count': winner_ok,
        'primary_semantic_bound_count': semantic_bound,
        'primary_quorum_bound_count': quorum_bound,
        'primary_complete_semantic_quorum_count': both_bound,
        'primary_current_authority_eligible_count': fully_current,
        'primary_currently_quarantined_count': len(primary_ids) - both_bound,
        'package_truth_path_exists_count': truth_paths_exist,
        'package_truth_path_exists_under_primary_root_count': truth_paths_exist_under_primary,
        'isolated_materialized_package_count': len(isolated_ids),
        'isolated_package_id_sha256': seal(sorted(isolated_ids)),
        'isolated_is_exact_primary_subset': isolated_ids <= primary_ids,
        'isolated_overlap_with_primary_count': len(isolated_ids & primary_ids),
        'isolated_lifecycle_path_exists_count': isolated_lifecycle_exists,
        'isolated_lifecycle_hash_verified_count': isolated_lifecycle_ok,
        'isolated_source_hash_verified_count': isolated_source_ok,
        'isolated_winner_hash_verified_count': isolated_winner_ok,
        'isolated_semantic_bound_count': isolated_semantic_bound,
        'isolated_quorum_bound_count': isolated_quorum_bound,
        'isolated_complete_semantic_quorum_count': isolated_both_bound,
        'isolated_current_authority_eligible_count': isolated_fully_current,
        'isolated_currently_quarantined_count': len(isolated_ids) - isolated_both_bound,
        'lifecycle_only_count': len(image_ids - primary_ids),
        'primary_without_lifecycle_count': len(primary_ids - image_ids),
        'isolated_audit_explanation': 'packages_caa_iso220 is a deterministic 220-package subset of the complete data/packages population',
    }

payload = {
    'schema_version': 'maskfactory.runpod_caa_reconciliation_audit.v1',
    'operation': 'read_only_sanitized_caa_reconciliation',
    'authority_claimed': False,
    'workspace_exists': workspace.is_dir(),
    'databases': [database(path) for path in sorted((workspace / 'data').glob('*.sqlite'))],
    'package_roots': [
        package_root(workspace / 'data' / 'packages'),
        package_root(workspace / 'data' / 'packages_caa_iso220'),
    ],
    'reconciliation': reconciliation(),
}
payload['inventory_sha256'] = seal(payload)
print(json.dumps(payload, sort_keys=True))
"""


class CaaAuditError(RuntimeError):
    """The sanitized read-only audit could not complete."""


def load_env_value(path: Path, key: str) -> str:
    for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        for delimiter in ("=", ":"):
            prefix = f"{key}{delimiter}"
            if line.startswith(prefix):
                value = line[len(prefix) :].strip().strip('"').strip("'")
                if value:
                    return value
    raise CaaAuditError(f"{key} not found")


def runpod_get(path: str, api_key: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{RUNPOD_REST}/{path.lstrip('/')}",
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise CaaAuditError(f"RunPod GET failed with HTTP {exc.code}") from exc
    if not isinstance(payload, dict):
        raise CaaAuditError("RunPod GET returned a non-object")
    return payload


def remote_audit(host: str, port: int) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "ConnectTimeout=15",
            "-p",
            str(port),
            f"root@{host}",
            "bash",
            "-s",
        ],
        input=f"python3 - <<'PY'\n{REMOTE_AUDIT}\nPY\n",
        capture_output=True,
        check=False,
        timeout=120,
        text=True,
    )
    if completed.returncode != 0:
        raise CaaAuditError(
            f"RunPod SSH audit failed with exit {completed.returncode}: "
            f"{completed.stderr.strip()[:300]}"
        )
    payload = json.loads(completed.stdout.splitlines()[-1])
    if not isinstance(payload, dict):
        raise CaaAuditError("RunPod SSH audit returned a non-object")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--pod-id", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    key = load_env_value(args.env_file, "RUNPOD_API_KEY")
    pod = runpod_get(f"pods/{args.pod_id}", key)
    if pod.get("desiredStatus") != "RUNNING":
        raise CaaAuditError("RunPod pod is not running")
    mappings = pod.get("portMappings") or {}
    host = str(pod.get("publicIp") or "")
    port = int(mappings.get("22") or 0)
    if not host or not port:
        raise CaaAuditError("RunPod SSH endpoint is unavailable")
    result = remote_audit(host, port)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
