from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_authoritative_instructions_fail_closed_on_local_runtime() -> None:
    standing = _read("Plan/STANDING_ORDERS_AUTONOMOUS_BUILD.md")
    start = _read("Plan/Instructions/00_START_HERE.md")
    operating = _read("Plan/Instructions/02_AUTONOMOUS_OPERATING_RULES.md")
    playbook = _read("Plan/Instructions/03_SESSION_PLAYBOOK.md")
    local_policy = _read("Plan/DOCKER_RUNTIME_AND_SESSION_USE.md")
    handoff = _read("Plan/RESTART_HANDOFF_AUTONOMOUS_20260719.md")
    combined = "\n".join((standing, start, operating, playbook, local_policy, handoff))

    required = (
        "Pursuing-goal execution invariant (fail closed)",
        "RunPod unavailability never authorizes a local substitute",
        "A state-changing local runtime operation is authorized only when Kevin asks",
        "There is intentionally no automatic start/repair command sequence",
    )
    for phrase in required:
        assert phrase in combined

    forbidden = (
        "Live-probe Docker + Ollama",
        "Docker Desktop is in that autonomous scope",
        "Use Docker freely",
        "agents start/repair stacks themselves",
        "Docker is a first-class local runtime for MaskFactory",
    )
    for phrase in forbidden:
        assert phrase not in combined


def test_local_runtime_policy_contains_no_executable_auto_start_recipe() -> None:
    local_policy = _read("Plan/DOCKER_RUNTIME_AND_SESSION_USE.md")
    forbidden_commands = (
        "docker run -d --name ollama",
        "docker compose -f",
        "wsl -d Ubuntu-22.04",
        "python tools/bootstrap_cvat.py",
    )
    for command in forbidden_commands:
        assert command not in local_policy
