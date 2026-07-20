from pathlib import Path

checks = {
    "prod_audit": (
        "src/maskfactory/autonomy/production_audit.py",
        "build_production_weekly_audit_queue",
    ),
    "benchmark_mod": ("src/maskfactory/models/benchmark.py", "def mark_benchmarked_candidate"),
    "prod_corpus": ("src/maskfactory/vlm/production.py", "corpus_record_from_decision"),
    "cli_runs": ("src/maskfactory/cli.py", 'default=Path("runs")'),
    "cli_prod_audit": ("src/maskfactory/cli.py", "build_production_weekly_audit_queue"),
    "cli_mark": ("src/maskfactory/cli.py", "mark-benchmarked"),
    "stages_profile": (
        "src/maskfactory/stages/production.py",
        "MASKFACTORY_AUTONOMY_ALLOW_AUTONOMOUS_PROFILE",
    ),
    "weekly": ("tools/weekly_qa.ps1", "--lifecycle-root runs"),
    "admission": ("tools/build_autonomous_gold_admission.py", "scan_lifecycle_pool"),
    "corpus_mod": ("src/maskfactory/autonomy/corpus.py", "assemble_autonomous_verification_corpus"),
    "orchestrator": ("tools/run_measured_champions_path.py", "measured_champions_path_production"),
}
ok = True
for name, (rel, needle) in checks.items():
    path = Path(rel)
    present = path.is_file() and needle in path.read_text(encoding="utf-8")
    print(f"{name}: {'OK' if present else 'MISSING'}")
    ok = ok and present
raise SystemExit(0 if ok else 2)
