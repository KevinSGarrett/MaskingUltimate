"""Deterministic script-only derived-mask generation from authority maps."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .io.png_strict import read_mask, write_binary_mask
from .ontology import Ontology, get_ontology

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "configs" / "derived.yaml"


class DeriveError(ValueError):
    """A declarative derivation cannot be parsed or evaluated."""


def derive_package(
    package_root: Path,
    *,
    config_path: Path = DEFAULT_CONFIG,
    ontology: Ontology | None = None,
) -> tuple[Path, ...]:
    package_root = Path(package_root)
    masks, formulas, input_hashes = compute_derivations(
        package_root, config_path=config_path, ontology=ontology
    )
    first_mask = next(iter(masks.values()))
    temporary = package_root / f".masks_derived.tmp-{uuid.uuid4().hex}"
    temporary.mkdir(parents=True, exist_ok=False)
    records: dict[str, Any] = {}
    outputs: list[Path] = []
    try:
        for name, formula in formulas.items():
            mask = masks[name]
            target = temporary / f"{name}.png"
            write_binary_mask(target, mask, source_size=(first_mask.shape[1], first_mask.shape[0]))
            records[name] = {
                "formula": formula,
                "inputs": input_hashes,
                "output_sha256": _sha256(target),
            }
        (temporary / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "config_sha256": _sha256(Path(config_path)),
                    "derivations": records,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        destination = package_root / "masks_derived"
        backup = package_root / f".masks_derived.backup-{uuid.uuid4().hex}"
        if destination.exists():
            os.replace(destination, backup)
        try:
            os.replace(temporary, destination)
        except Exception:
            if backup.exists():
                os.replace(backup, destination)
            raise
        _remove_tree(backup)
        outputs = [destination / f"{name}.png" for name in formulas]
    finally:
        _remove_tree(temporary)
    return tuple(outputs)


def compute_derivations(
    package_root: Path,
    *,
    config_path: Path = DEFAULT_CONFIG,
    ontology: Ontology | None = None,
) -> tuple[dict[str, np.ndarray], dict[str, str], dict[str, str]]:
    """Evaluate every formula in memory for generation and QC-009 reproduction."""
    package_root = Path(package_root)
    authority = ontology or get_ontology()
    config = _load_config(config_path)
    part = read_mask(package_root / "label_map_part.png").astype(np.uint16)
    material = read_mask(package_root / "label_map_material.png").astype(np.uint8)
    if part.shape != material.shape:
        raise DeriveError(f"part map shape {part.shape} != material map shape {material.shape}")
    formulas = {str(name): str(formula) for name, formula in config["formulas"].items()}
    expected = {label.name for label in authority.labels if label.mask_type == "derived_union"}
    if set(formulas) != expected:
        missing = sorted(expected.difference(formulas))
        extra = sorted(set(formulas).difference(expected))
        raise DeriveError(f"derived formula registry drift; missing={missing}, extra={extra}")
    context = _FormulaContext(package_root, part, material, authority)
    masks: dict[str, np.ndarray] = {}
    for name, formula in formulas.items():
        mask = context.evaluate(formula)
        context.derived[name] = mask
        masks[name] = mask
    return masks, formulas, dict(context.input_hashes)


class _FormulaContext:
    def __init__(
        self, package_root: Path, part: np.ndarray, material: np.ndarray, ontology: Ontology
    ) -> None:
        self.package_root = package_root
        self.part = part
        self.material = material
        self.ontology = ontology
        self.derived: dict[str, np.ndarray] = {}
        self.input_hashes = {
            "label_map_part.png": _sha256(package_root / "label_map_part.png"),
            "label_map_material.png": _sha256(package_root / "label_map_material.png"),
        }

    def evaluate(self, formula: str) -> np.ndarray:
        if formula.startswith("edge("):
            return self._edge(formula)
        tokenized = formula.replace("(", " ( ").replace(")", " ) ")
        tokenized = tokenized.replace("|", " | ").replace("&", " & ").replace(" - ", " - ")
        tokens = tokenized.split()
        result, position = self._parse_union(tokens, 0)
        if position != len(tokens):
            raise DeriveError(f"unexpected formula token {tokens[position]!r}: {formula}")
        return result

    def _parse_union(self, tokens: list[str], position: int) -> tuple[np.ndarray, int]:
        value, position = self._parse_intersection(tokens, position)
        while position < len(tokens) and tokens[position] == "|":
            right, position = self._parse_intersection(tokens, position + 1)
            value = value | right
        return value, position

    def _parse_intersection(self, tokens: list[str], position: int) -> tuple[np.ndarray, int]:
        value, position = self._parse_atom(tokens, position)
        while position < len(tokens) and tokens[position] in {"&", "-"}:
            operator = tokens[position]
            right, position = self._parse_atom(tokens, position + 1)
            value = value & right if operator == "&" else value & ~right
        return value, position

    def _parse_atom(self, tokens: list[str], position: int) -> tuple[np.ndarray, int]:
        if position >= len(tokens):
            raise DeriveError("formula ended before an operand")
        token = tokens[position]
        if token == "(":
            value, position = self._parse_union(tokens, position + 1)
            if position >= len(tokens) or tokens[position] != ")":
                raise DeriveError("unclosed formula parenthesis")
            return value, position + 1
        return self._resolve(token), position + 1

    def _resolve(self, token: str) -> np.ndarray:
        if token.startswith("part:"):
            return self.part == self.ontology.label(token[5:]).id
        if token.startswith("material:"):
            return self.material == self.ontology.label(token[9:]).id
        if token.startswith("part_ids:"):
            return np.isin(self.part, _parse_ids(token[9:]))
        if token.startswith("material_ids:"):
            return np.isin(self.material, _parse_ids(token[13:]))
        if token.startswith("derived:"):
            token = token[8:]
        if token in self.derived:
            return self.derived[token]
        if token == "silhouette:person_full_visible":
            return np.isin(self.part, range(1, 50))
        if token == "projected:amodal_body_estimates":
            return self._projected_union()
        raise DeriveError(f"unknown formula operand: {token!r}")

    def _edge(self, formula: str) -> np.ndarray:
        if " within " in formula:
            match = re.fullmatch(r"edge\((.+) within (.+)\)", formula)
            if match is None:
                raise DeriveError(f"invalid within-edge formula: {formula}")
            subject = self.evaluate(match.group(1))
            container = self.evaluate(match.group(2))
            return _boundary(subject) & container
        match = re.fullmatch(r"edge\((.+), (.+), width=(\d+)px@1024\)", formula)
        if match is None:
            raise DeriveError(f"invalid contact-edge formula: {formula}")
        left = self.evaluate(match.group(1))
        right = self.evaluate(match.group(2))
        width = max(1, round(int(match.group(3)) * max(self.part.shape) / 1024))
        return (_dilate(left, width) & right) | (_dilate(right, width) & left)

    def _projected_union(self) -> np.ndarray:
        result = np.zeros(self.part.shape, dtype=bool)
        for path in sorted((self.package_root / "projected").glob("amodal_*.png")):
            mask = read_mask(path)
            if mask.shape != self.part.shape:
                raise DeriveError(f"projected mask shape mismatch: {path}")
            result |= mask > 0
            self.input_hashes[path.relative_to(self.package_root).as_posix()] = _sha256(path)
        return result


def _parse_ids(expression: str) -> tuple[int, ...]:
    values: list[int] = []
    for component in expression.split(","):
        if "-" in component:
            start, end = (int(value) for value in component.split("-", 1))
            values.extend(range(start, end + 1))
        else:
            values.append(int(component))
    return tuple(values)


def _boundary(mask: np.ndarray) -> np.ndarray:
    return mask & ~_erode(mask)


def _dilate(mask: np.ndarray, iterations: int = 1) -> np.ndarray:
    result = mask.copy()
    for _ in range(iterations):
        padded = np.pad(result, 1)
        result = (
            padded[1:-1, 1:-1]
            | padded[:-2, 1:-1]
            | padded[2:, 1:-1]
            | padded[1:-1, :-2]
            | padded[1:-1, 2:]
        )
    return result


def _erode(mask: np.ndarray) -> np.ndarray:
    padded = np.pad(mask, 1)
    return (
        padded[1:-1, 1:-1]
        & padded[:-2, 1:-1]
        & padded[2:, 1:-1]
        & padded[1:-1, :-2]
        & padded[1:-1, 2:]
    )


def _load_config(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("formulas"), dict):
        raise DeriveError(f"derived config must contain a formulas mapping: {path}")
    return document


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _remove_tree(path: Path) -> None:
    if not path.exists():
        return
    for child in path.iterdir():
        if child.is_dir():
            _remove_tree(child)
        else:
            child.unlink()
    path.rmdir()
