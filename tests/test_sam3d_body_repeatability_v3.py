from __future__ import annotations

from pathlib import Path

from tools import run_sam3d_body_repeatability_v3 as runner


def test_v3_injects_the_immutable_source_root_once(monkeypatch, tmp_path) -> None:
    source = tmp_path / "official_source"
    monkeypatch.setattr(runner.sys, "path", ["sentinel"])
    runner._inject_source_root(source)
    runner._inject_source_root(source)
    assert runner.sys.path[0] == str(source)
    assert runner.sys.path.count(str(source)) == 1


def test_v3_injects_source_root_before_official_package_import() -> None:
    source = Path(runner.__file__).read_text(encoding="utf-8")
    assert source.index("_inject_source_root(args.source_root)") < source.index(
        "from sam_3d_body import SAM3DBodyEstimator, load_sam_3d_body"
    )
