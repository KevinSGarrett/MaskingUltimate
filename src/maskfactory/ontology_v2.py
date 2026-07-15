"""Inactive, append-only body-parts-v2 ontology generation and alias authority.

Nothing in this module changes the active v1 runtime ontology.  It builds the
reviewable v2 artifacts required by doc 18 so their exact contract can be
tested before activation.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from .ontology_generator import build_ontology

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROPOSAL = ROOT / "Plan" / "OntologyV2" / "ontology_v2_additions.yaml"
DEFAULT_ONTOLOGY_V2 = ROOT / "configs" / "ontology_v2.yaml"
DEFAULT_DERIVED_V2 = ROOT / "configs" / "derived_v2.yaml"
DEFAULT_VIZ_V1 = ROOT / "configs" / "viz.yaml"
DEFAULT_VIZ_V2 = ROOT / "configs" / "viz_v2.yaml"

_REQUIRED_LABEL_FIELDS = {
    "id",
    "name",
    "mask_type",
    "map",
    "side",
    "swap_partner",
    "parent_union",
    "expected_area_pct_range",
    "max_components",
    "boundary_rule",
}
_V2_BOUNDARY_RULES = {
    "areola_ring_excludes_nipple": {
        "rule": "visible areolar ring only; same-side nipple pixels are carved out"
    },
    "visible_nipple_carveout": {
        "rule": "visible nipple surface only; carved out of same-side areola and breast"
    },
    "external_vulva_visible_only": {
        "rule": "visible external vulvar surface only; never infer an internal canal"
    },
    "visible_shaft_excludes_glans": {
        "rule": "visible shaft or foreskin surface only; visible glans pixels are carved out"
    },
    "visible_glans_only": {"rule": "visible glans surface only; never infer covered extent"},
    "visible_scrotal_midline": {
        "rule": "split visible external scrotal surface at a defensible character-side midline"
    },
}


class OntologyV2Error(ValueError):
    """Raised when the approved v2 delta is incomplete or unsafe."""


@dataclass(frozen=True)
class AliasResolution:
    """Canonical value plus provenance for a user-supplied v2 selector."""

    requested: str
    canonical: str
    was_alias: bool
    kind: str
    warning: str | None

    def provenance(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "canonical": self.canonical,
            "was_alias": self.was_alias,
            "kind": self.kind,
            "warning": self.warning,
        }


def load_v2_proposal(path: Path | str = DEFAULT_PROPOSAL) -> dict[str, Any]:
    source = Path(path)
    try:
        document = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise OntologyV2Error(f"cannot load ontology-v2 proposal {source}: {exc}") from exc
    if not isinstance(document, dict):
        raise OntologyV2Error("ontology-v2 proposal root must be an object")
    _validate_proposal(document)
    return document


def _validate_proposal(document: Mapping[str, Any]) -> None:
    exact = {
        "status": "approved_design_not_active",
        "base_ontology": "body_parts_v1",
        "target_ontology": "body_parts_v2",
        "id_policy": "append_only",
        "part_id_range": [0, 64],
        "num_part_classes_including_background": 65,
        "ignore_index": 255,
    }
    for key, expected in exact.items():
        if document.get(key) != expected:
            raise OntologyV2Error(f"ontology-v2 {key} must equal {expected!r}")

    base = build_ontology()
    base_parts = [label for label in base["labels"] if label["map"] == "part"]
    base_names = {label["name"] for label in base["labels"]}
    if [(label["id"], label["name"]) for label in base_parts] != [
        (index, name) for index, name in enumerate([label["name"] for label in base_parts])
    ] or [label["id"] for label in base_parts] != list(range(56)):
        raise OntologyV2Error("active v1 PART mapping is not contiguous 0..55")

    additions = document.get("labels")
    if not isinstance(additions, list) or len(additions) != 9:
        raise OntologyV2Error("ontology-v2 must contain exactly nine appended labels")
    if any(not isinstance(label, dict) for label in additions):
        raise OntologyV2Error("every ontology-v2 label must be an object")
    if any(not _REQUIRED_LABEL_FIELDS <= set(label) for label in additions):
        raise OntologyV2Error("ontology-v2 label is missing a required field")
    if [label["id"] for label in additions] != list(range(56, 65)):
        raise OntologyV2Error("ontology-v2 label IDs must be contiguous 56..64")
    names = [label["name"] for label in additions]
    if len(names) != len(set(names)) or set(names) & base_names:
        raise OntologyV2Error("ontology-v2 names must be unique and append-only")
    by_name = {label["name"]: label for label in additions}
    for label in additions:
        if label["mask_type"] != "atomic_exclusive" or label["map"] != "part":
            raise OntologyV2Error("every ontology-v2 label must be an atomic PART label")
        if label["boundary_rule"] not in _V2_BOUNDARY_RULES:
            raise OntologyV2Error(f"unknown ontology-v2 boundary rule: {label['boundary_rule']}")
        partner = label["swap_partner"]
        if partner is not None and (
            partner not in by_name or by_name[partner]["swap_partner"] != label["name"]
        ):
            raise OntologyV2Error(f"non-reciprocal ontology-v2 swap: {label['name']}")

    formulas = document.get("derived_formulas")
    aliases = document.get("aliases")
    if not isinstance(formulas, dict) or not formulas:
        raise OntologyV2Error("ontology-v2 derived_formulas must be non-empty")
    if not isinstance(aliases, dict) or not aliases:
        raise OntologyV2Error("ontology-v2 aliases must be non-empty")
    canonical = set(names) | set(formulas)
    for alias, record in aliases.items():
        if (
            alias in canonical
            or not isinstance(record, dict)
            or record.get("canonical") not in canonical
        ):
            raise OntologyV2Error(f"invalid ontology-v2 alias: {alias!r}")

    if document.get("visibility_states_added") != [
        "occluded_by_clothing",
        "not_applicable",
        "unreviewed_for_v2",
    ]:
        raise OntologyV2Error("ontology-v2 visibility-state delta is not exact")
    governance = document.get("governance")
    if not isinstance(governance, dict) or governance.get("confirmed_adult_required") is not True:
        raise OntologyV2Error("ontology-v2 must require confirmed-adult governance")
    for false_gate in (
        "hidden_anatomy_may_be_visible_gold",
        "clothing_contour_is_anatomy_evidence",
        "projected_amodal_is_training_or_gold_authority",
        "unreviewed_is_negative",
    ):
        if governance.get(false_gate) is not False:
            raise OntologyV2Error(f"unsafe ontology-v2 governance gate: {false_gate}")


def _part_label(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": raw["id"],
        "name": raw["name"],
        "mask_type": raw["mask_type"],
        "map": raw["map"],
        "side": raw["side"],
        "parent_union": raw["parent_union"],
        "enabled": True,
        "expected_area_pct_range": list(raw["expected_area_pct_range"]),
        "max_components": raw["max_components"],
        "exclusivity_group": "part_map",
        "swap_partner": raw["swap_partner"],
        "visibility_default": "unreviewed_for_v2",
        "boundary_rule": raw["boundary_rule"],
    }


def _derived_label(name: str, formula: str) -> dict[str, Any]:
    side = (
        "left" if name.startswith("left_") else "right" if name.startswith("right_") else "center"
    )
    partner = (
        "right_" + name.removeprefix("left_")
        if name.startswith("left_")
        else "left_" + name.removeprefix("right_") if name.startswith("right_") else None
    )
    return {
        "id": None,
        "name": name,
        "mask_type": "derived_union",
        "map": "none",
        "side": side,
        "parent_union": None,
        "enabled": True,
        "expected_area_pct_range": None,
        "max_components": None,
        "exclusivity_group": None,
        "swap_partner": partner,
        "visibility_default": "n/a",
        "boundary_rule": "script_formula",
        "formula": formula,
    }


def build_ontology_v2(path: Path | str = DEFAULT_PROPOSAL) -> dict[str, Any]:
    proposal = load_v2_proposal(path)
    document = deepcopy(build_ontology())
    labels = document["labels"]
    part_end = next(index for index, label in enumerate(labels) if label["map"] != "part")
    labels[part_end:part_end] = [_part_label(label) for label in proposal["labels"]]
    labels.extend(
        _derived_label(name, formula) for name, formula in proposal["derived_formulas"].items()
    )
    document.update(
        {
            "config_version": "2.0.0",
            "mask_ontology_version": "body_parts_v2",
            "base_ontology_version": "body_parts_v1",
            "activation_status": "approved_design_not_active",
            "ignore_index": 255,
            "visibility_states": [
                *document["visibility_states"],
                *proposal["visibility_states_added"],
            ],
            "visibility_state_aliases": {"fully_occluded": "occluded"},
            "aliases": deepcopy(proposal["aliases"]),
            "governance": deepcopy(proposal["governance"]),
        }
    )
    document["boundary_rules"] = {
        **document["boundary_rules"],
        **deepcopy(_V2_BOUNDARY_RULES),
    }
    return document


def build_derived_v2(path: Path | str = DEFAULT_PROPOSAL) -> dict[str, Any]:
    proposal = load_v2_proposal(path)
    base = build_ontology()
    formulas = {
        label["name"]: label["formula"]
        for label in base["labels"]
        if label["mask_type"] == "derived_union"
    }
    formulas.update(proposal["derived_formulas"])
    formulas["full_body_parts_visible"] = "part_ids:1-49 | part_ids:54-55 | part_ids:56-64"
    formulas["visible_body_skin"] = (
        "((part_ids:1-49 | part_ids:54-55 | part_ids:56-64) & material:skin) - part:hair"
    )
    return {
        "config_version": "2.0.0",
        "mask_ontology_version": "body_parts_v2",
        "activation_status": "approved_design_not_active",
        "formulas": formulas,
    }


def build_viz_v2(path: Path | str = DEFAULT_PROPOSAL) -> dict[str, Any]:
    ontology = build_ontology_v2(path)
    try:
        base = yaml.safe_load(DEFAULT_VIZ_V1.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise OntologyV2Error(f"cannot load v1 visualization authority: {exc}") from exc
    if not isinstance(base, dict) or not isinstance(base.get("label_colors"), dict):
        raise OntologyV2Error("v1 visualization authority is invalid")
    colors = dict(base["label_colors"])
    used = set(colors.values())
    # Fixed append-only palette: stable and deliberately separated in hue/lightness.
    candidates = iter(
        (
            "#7A1FA2",
            "#00897B",
            "#E65100",
            "#3949AB",
            "#C2185B",
            "#2E7D32",
            "#AD1457",
            "#00695C",
            "#5D4037",
            "#1565C0",
            "#9E9D24",
            "#6A1B9A",
            "#EF6C00",
            "#00838F",
            "#283593",
            "#558B2F",
            "#D84315",
            "#4527A0",
            "#0277BD",
            "#827717",
            "#4E342E",
        )
    )
    for label in ontology["labels"]:
        if label["name"] in colors:
            continue
        color = next(candidates)
        if color in used:
            raise OntologyV2Error(f"duplicate v2 visualization color: {color}")
        colors[label["name"]] = color
        used.add(color)
    result = deepcopy(base)
    result["config_version"] = "2.0.0"
    result["mask_ontology_version"] = "body_parts_v2"
    result["activation_status"] = "approved_design_not_active"
    result["label_colors"] = colors
    return result


def resolve_v2_alias(value: str, path: Path | str = DEFAULT_PROPOSAL) -> AliasResolution:
    if not isinstance(value, str) or not value.strip():
        raise OntologyV2Error("ontology-v2 selector must be a non-empty string")
    requested = value.strip()
    proposal = load_v2_proposal(path)
    aliases = proposal["aliases"]
    if requested in aliases:
        record = aliases[requested]
        return AliasResolution(
            requested=requested,
            canonical=record["canonical"],
            was_alias=True,
            kind=record.get("kind", "atomic"),
            warning=record.get("warning"),
        )
    canonical_atomics = {label["name"] for label in proposal["labels"]}
    canonical_derived = set(proposal["derived_formulas"])
    if requested in canonical_atomics | canonical_derived:
        return AliasResolution(
            requested=requested,
            canonical=requested,
            was_alias=False,
            kind="derived_union" if requested in canonical_derived else "atomic",
            warning=None,
        )
    raise OntologyV2Error(f"unknown ontology-v2 selector: {requested!r}")


def _render(document: Mapping[str, Any]) -> str:
    return yaml.safe_dump(dict(document), sort_keys=False, allow_unicode=True, width=100)


def render_ontology_v2(path: Path | str = DEFAULT_PROPOSAL) -> str:
    return _render(build_ontology_v2(path))


def render_derived_v2(path: Path | str = DEFAULT_PROPOSAL) -> str:
    return _render(build_derived_v2(path))


def render_viz_v2(path: Path | str = DEFAULT_PROPOSAL) -> str:
    return _render(build_viz_v2(path))


def generate_v2_artifacts(
    *,
    proposal_path: Path | str = DEFAULT_PROPOSAL,
    ontology_path: Path | str = DEFAULT_ONTOLOGY_V2,
    derived_path: Path | str = DEFAULT_DERIVED_V2,
    viz_path: Path | str = DEFAULT_VIZ_V2,
) -> tuple[Path, Path, Path]:
    outputs = (
        (Path(ontology_path), render_ontology_v2(proposal_path)),
        (Path(derived_path), render_derived_v2(proposal_path)),
        (Path(viz_path), render_viz_v2(proposal_path)),
    )
    for output, text in outputs:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    return tuple(output for output, _ in outputs)  # type: ignore[return-value]


def v2_artifacts_are_current(
    *,
    proposal_path: Path | str = DEFAULT_PROPOSAL,
    ontology_path: Path | str = DEFAULT_ONTOLOGY_V2,
    derived_path: Path | str = DEFAULT_DERIVED_V2,
    viz_path: Path | str = DEFAULT_VIZ_V2,
) -> bool:
    expected = (
        (Path(ontology_path), render_ontology_v2(proposal_path)),
        (Path(derived_path), render_derived_v2(proposal_path)),
        (Path(viz_path), render_viz_v2(proposal_path)),
    )
    return all(
        path.is_file() and path.read_text(encoding="utf-8") == text for path, text in expected
    )
