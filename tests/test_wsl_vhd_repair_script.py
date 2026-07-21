from pathlib import Path

SCRIPT = Path("tools/Repair-MaskFactoryWslVhd.ps1")


def test_repair_script_is_backup_first_and_never_self_elevates() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "[switch]$ConfirmRepair" in text
    assert "Test-IsAdministrator" in text
    assert "It will not self-elevate or open a UAC prompt" in text
    assert "Copy-Item -LiteralPath $resolvedVhd" in text
    assert "source_backup_hash_match" in text
    assert "Get-FileHash -Algorithm SHA256" in text
    assert "Start-Process" not in text
    assert "-Verb RunAs" not in text
    assert "--unregister" not in text


def test_repair_script_targets_only_one_verified_ext4_vhd() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert '"--mount", $resolvedVhd, "--vhd", "--bare"' in text
    assert '"/sbin/blkid"' in text
    assert "Expected exactly one newly attached ext4 repair disk" in text
    assert "The repair device is mounted; refusing to run e2fsck" in text
    assert '"/sbin/e2fsck", "-f", "-p", $repairDevice' in text
    assert '"/sbin/e2fsck", "-f", "-y", $repairDevice' in text
    assert "wsl.exe --unmount $resolvedVhd" in text
    assert "Exact-path WSL VHD detach failed" in text
    assert "Docker Desktop was not restarted to avoid a disk-sharing conflict" in text
    assert "wsl.exe --unmount 2" not in text


def test_repair_script_preserves_docker_and_authority_boundaries() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert '"desktop", "stop"' in text
    assert '"desktop", "start"' in text
    assert "Docker Desktop restart failed after the VHD was detached" in text
    assert "docker_vhd_repaired = $false" in text
    assert "distribution_unregistered = $false" in text
    assert "vhd_moved_or_replaced = $false" in text
    assert "mask_or_gold_authority_changed = $false" in text
    assert "emergency_ro" in text


def test_repair_script_hashes_and_probes_before_docker_restart() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    post_hash = "$postRepairHash = (Get-FileHash"
    post_probe = "$rootProbe = Invoke-CheckedNative"
    docker_start = 'ArgumentList @("desktop", "start")'
    assert text.index(post_hash) < text.index(post_probe) < text.index(docker_start)
    assert "if ($operationError)" in text
    assert "throw $operationError" in text
