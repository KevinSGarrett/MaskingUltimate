import os
from pathlib import Path

from tools.run_birefnet_wsl import _attach_checkpoint


def test_birefnet_checkpoint_attachment_preserves_exact_bytes(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.safetensors"
    source.write_bytes(b"immutable-checkpoint")
    destination = tmp_path / "model.safetensors"
    monkeypatch.setattr(
        Path, "symlink_to", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError())
    )
    mode = _attach_checkpoint(source, destination)
    assert mode in {"hardlink", "copy"}
    assert destination.read_bytes() == source.read_bytes()
    if mode == "hardlink":
        assert os.stat(destination).st_ino == os.stat(source).st_ino
