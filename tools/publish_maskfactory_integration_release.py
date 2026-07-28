"""Publish or validate a MaskFactory integration-release acceptance record."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maskfactory.bridge.integration_release import (
    build_inventory_from_root,
    run_integration_release_acceptance,
    validate_integration_release_evidence,
)
from maskfactory.bridge.release_publication import load_publication_evidence
from maskfactory.validation import load_canonical_json


def _load_json(path: Path) -> dict:
    document = load_canonical_json(path.read_bytes())
    if not isinstance(document, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return document


def _load_inventories(release_root: Path, manifest: dict) -> dict[str, list[dict]]:
    mapping = manifest.get("inventory_roots") or {
        "nodes": "nodes",
        "workflows": "workflows",
        "schemas": "schemas",
        "api_openapi": "openapi",
        "policies": "policies",
    }
    inventories: dict[str, list[dict]] = {}
    for name, relative in mapping.items():
        root = release_root / relative
        inventories[name] = build_inventory_from_root(root) if root.is_dir() else []
        # Rewrite paths to include inventory root prefix for install parity.
        inventories[name] = [
            {
                **row,
                "relative_path": f"{relative.rstrip('/')}/{row['relative_path']}",
            }
            for row in inventories[name]
        ]
    return inventories


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--install-target", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--publication-evidence", type=Path, required=True)
    parser.add_argument("--capability-decision", type=Path, required=True)
    parser.add_argument("--recovery-evidence", type=Path, required=True)
    parser.add_argument("--inventory-manifest", type=Path, required=False)
    parser.add_argument("--evidence-id", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--git-tree", required=True)
    parser.add_argument("--repository-clean", action="store_true")
    parser.add_argument("--perform-rollback", action="store_true")
    parser.add_argument("--publication-issues-empty", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify-only", type=Path, required=False)
    args = parser.parse_args()

    if args.verify_only is not None:
        issues = validate_integration_release_evidence(_load_json(args.verify_only))
        if issues:
            print(json.dumps(list(issues), indent=2))
            return 1
        print("VALID: integration release evidence")
        return 0

    publication = load_publication_evidence(args.publication_evidence)
    capability = _load_json(args.capability_decision)
    recovery = _load_json(args.recovery_evidence)
    inventory_manifest = _load_json(args.inventory_manifest) if args.inventory_manifest else {}
    inventories = _load_inventories(args.release_root, inventory_manifest)
    evidence = run_integration_release_acceptance(
        release_id=args.release_id,
        release_root=args.release_root,
        runtime_root=args.runtime_root,
        install_target=args.install_target,
        source_inventories=inventories,
        manifest_path=args.manifest,
        publication_evidence=publication,
        publication_issues=() if args.publication_issues_empty else None,
        capability_decision=capability,
        recovery_evidence=recovery,
        repository_clean=bool(args.repository_clean),
        git_commit=args.git_commit,
        git_tree=args.git_tree,
        evidence_id=args.evidence_id,
        perform_rollback=bool(args.perform_rollback),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    issues = validate_integration_release_evidence(evidence)
    print(json.dumps({"status": evidence["status"], "issues": list(issues)}, indent=2))
    return 0 if evidence["status"] in {"accepted", "rolled_back"} and not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
