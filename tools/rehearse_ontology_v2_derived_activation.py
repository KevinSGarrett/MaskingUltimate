"""Rehearse the v2 ontology/derived pair switch without activating production."""

from maskfactory.ontology_v2_activation import write_v2_authority_rehearsal_evidence


def main() -> int:
    print(write_v2_authority_rehearsal_evidence())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
