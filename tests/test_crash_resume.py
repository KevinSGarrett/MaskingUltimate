import json
import os
import subprocess
import sys
import time
from pathlib import Path

from maskfactory.orchestrator import run_pipeline
from maskfactory.reindex import reindex_packages
from test_manifest_schema import valid_manifest

ROOT = Path(__file__).resolve().parents[1]


def test_hard_kill_mid_stage_resumes_cleanly_and_reindex_diff_is_zero(tmp_path: Path) -> None:
    work_root = tmp_path / "work"
    marker = tmp_path / "runner_started"
    script = f"""
import time
from pathlib import Path
from maskfactory.orchestrator import run_pipeline

def runner(context):
    (context.output_dir / "partial.bin").write_bytes(b"partial")
    Path({str(marker)!r}).write_text("started", encoding="utf-8")
    time.sleep(60)
    return {{"should_not_finish": True}}

run_pipeline(
    "img_a3f9c2e17b04",
    selected=("S02",),
    work_root=Path({str(work_root)!r}),
    runners={{"S02": runner}},
)
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + environment.get("PYTHONPATH", "")
    process = subprocess.Popen([sys.executable, "-c", script], env=environment)
    try:
        deadline = time.monotonic() + 10
        while not marker.is_file() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.is_file(), "child stage never reached its write point"
        process.kill()
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    assert process.returncode != 0
    stage_parent = work_root / "s02"
    assert list(stage_parent.glob("img_a3f9c2e17b04.tmp-*")), "hard kill did not leave staging"

    def resumed_runner(context):
        (context.output_dir / "complete.bin").write_bytes(b"complete")
        return {"resumed": True}

    result = run_pipeline(
        "img_a3f9c2e17b04",
        selected=("S02",),
        work_root=work_root,
        runners={"S02": resumed_runner},
    )
    assert result[0].status == "complete"
    assert not list(stage_parent.glob("img_a3f9c2e17b04.tmp-*"))
    final = stage_parent / "img_a3f9c2e17b04"
    assert (final / "complete.bin").read_bytes() == b"complete"
    assert not (final / "partial.bin").exists()
    assert json.loads((final / "manifest_delta.json").read_text(encoding="utf-8")) == {
        "resumed": True
    }

    packages = tmp_path / "packages"
    manifest = valid_manifest()
    manifest_path = packages / manifest["image_id"] / "instances" / "p0" / "manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    database = tmp_path / "state.sqlite"
    reindex_packages(packages_root=packages, database=database, dry_run=False)
    assert reindex_packages(packages_root=packages, database=database, dry_run=True).clean
