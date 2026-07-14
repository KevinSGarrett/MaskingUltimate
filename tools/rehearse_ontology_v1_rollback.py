"""Rehearse exact v1 registry/workflow restoration without activating v2."""

from maskfactory.ontology_v2_rollback import write_v1_rollback_evidence


def main() -> int:
    print(write_v1_rollback_evidence())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
