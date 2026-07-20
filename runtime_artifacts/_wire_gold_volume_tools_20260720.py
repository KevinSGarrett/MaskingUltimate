"""Atomically re-apply gold-volume wiring into contested tool files."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _patch_admission() -> None:
    path = ROOT / "tools" / "build_autonomous_gold_admission.py"
    text = path.read_text(encoding="utf-8")
    import_block = (
        "from maskfactory.autonomy.gold_volume_sources import (\n"
        "    GoldVolumeSourcesError,\n"
        "    probe_gold_volume_sources,\n"
        ")\n"
    )
    if "probe_gold_volume_sources" not in text:
        anchor = "from maskfactory.autonomy.calibration import (\n"
        end = text.index(")\n", text.index(anchor)) + 2
        text = text[:end] + "\n" + import_block + text[end:]
    probe_block = (
        "    pool = scan_verified_candidates(args.machine_root)\n"
        '    evidence["autonomous_verified_pool"] = pool\n'
        "\n"
        "    try:\n"
        "        gold_volumes = probe_gold_volume_sources()\n"
        '        evidence["gold_volume_sources"] = gold_volumes.to_dict()\n'
        '        evidence["tournament_input_roots"] = {\n'
        "            name: str(path) for name, path in sorted(gold_volumes.selected_roots().items())\n"
        "        }\n"
        "    except GoldVolumeSourcesError as exc:\n"
        '        evidence["gold_volume_sources"] = {\n'
        '            "present": False,\n'
        '            "error": str(exc),\n'
        '            "junction_critical_runtime_to_usb": False,\n'
        "        }\n"
        '        evidence["tournament_input_roots"] = {}\n'
        "\n"
        "    if args.corpus is None:\n"
    )
    old = (
        "    pool = scan_verified_candidates(args.machine_root)\n"
        '    evidence["autonomous_verified_pool"] = pool\n'
        "\n"
        "    if args.corpus is None:\n"
    )
    if "tournament_input_roots" not in text:
        if old not in text:
            raise SystemExit("admission anchor missing")
        text = text.replace(old, probe_block, 1)
    path.write_text(text, encoding="utf-8")
    print("patched", path)


def _patch_source_slice() -> None:
    path = ROOT / "tools" / "run_local_multi_person_source_slice.py"
    text = path.read_text(encoding="utf-8")
    if "default_maskedwarehouse_lv_mhp_root" not in text:
        text = text.replace(
            "from maskfactory.autonomy.multi_person_gate import evaluate_multi_person_candidate_gate\n",
            "from maskfactory.autonomy.gold_volume_sources import default_maskedwarehouse_lv_mhp_root\n"
            "from maskfactory.autonomy.multi_person_gate import evaluate_multi_person_candidate_gate\n",
            1,
        )
    old = (
        "    parser.add_argument(\n"
        '        "--source-root",\n'
        "        type=Path,\n"
        '        default=Path(r"C:\\Comfy_UI_Main\\MaskedWarehouse\\Body\\LV-MHP-v1"),\n'
        "    )\n"
        '    parser.add_argument("--limit", type=int, default=12)\n'
        '    parser.add_argument("--output", type=Path, required=True)\n'
        '    parser.add_argument("--verify", action="store_true")\n'
        "    args = parser.parse_args(argv)\n"
        "\n"
        "    if args.verify:\n"
        '        document = json.loads(args.output.read_text(encoding="utf-8"))\n'
        '        recomputed = _sha_doc({key: value for key, value in document.items() if key != "sha256"})\n'
        '        if recomputed != document.get("sha256"):\n'
        "            raise SystemExit(\n"
        "                f\"seal mismatch: recomputed={recomputed} stored={document.get('sha256')}\"\n"
        "            )\n"
        "    else:\n"
        "        document = run_local_multi_person_source_slice(args.source_root, args.limit)\n"
    )
    new = (
        "    parser.add_argument(\n"
        '        "--source-root",\n'
        "        type=Path,\n"
        "        default=None,\n"
        '        help="Defaults to read-when-present MaskedWarehouse LV-MHP via gold_volume_sources.",\n'
        "    )\n"
        '    parser.add_argument("--limit", type=int, default=12)\n'
        '    parser.add_argument("--output", type=Path, required=True)\n'
        '    parser.add_argument("--verify", action="store_true")\n'
        "    args = parser.parse_args(argv)\n"
        "    source_root = args.source_root or default_maskedwarehouse_lv_mhp_root()\n"
        "\n"
        "    if args.verify:\n"
        '        document = json.loads(args.output.read_text(encoding="utf-8"))\n'
        '        recomputed = _sha_doc({key: value for key, value in document.items() if key != "sha256"})\n'
        '        if recomputed != document.get("sha256"):\n'
        "            raise SystemExit(\n"
        "                f\"seal mismatch: recomputed={recomputed} stored={document.get('sha256')}\"\n"
        "            )\n"
        "    else:\n"
        "        document = run_local_multi_person_source_slice(source_root, args.limit)\n"
    )
    if "source_root = args.source_root or default_maskedwarehouse_lv_mhp_root()" not in text:
        if old not in text:
            raise SystemExit("source_slice anchor missing")
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    print("patched", path)


if __name__ == "__main__":
    _patch_admission()
    _patch_source_slice()
