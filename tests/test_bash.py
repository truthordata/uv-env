from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.main import get_command
from typer.testing import CliRunner

from uv_env import cli

BASH = shutil.which("bash")
UV = shutil.which("uv")
HOOK = Path(__file__).parents[1] / "src" / "uv_env" / "shell" / "bash" / "uv-env.bash"

pytestmark = pytest.mark.skipif(BASH is None, reason="bash is not installed")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    profiles = root / "env"
    profiles.mkdir(parents=True)
    (root / "pyproject.toml").touch()
    (profiles / "dev.env").write_text("UV_ENV_TEST_PROFILE=dev\n")
    (profiles / "prod.env").write_text("UV_ENV_TEST_PROFILE=prod\n")
    (root / "nested").mkdir()
    return root


def run_bash(project: Path, script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [BASH, "--noprofile", "--norc", "-c", script],
        cwd=project / "nested",
        text=True,
        capture_output=True,
        check=True,
    )


def test_hook_is_valid_bash() -> None:
    subprocess.run([BASH, "-n", str(HOOK)], check=True)


def test_hook_exports_selected_profile(project: Path) -> None:
    (project / "env" / cli.SELECTION_FILE).write_text("prod.env\n")
    script = f"PS1='base> '; source {shlex.quote(str(HOOK))}; printf '%s\\n%s\\n' \"$UV_ENV_FILE\" \"$UV_ENV_PROMPT\""

    result = run_bash(project, script)

    path, prompt = result.stdout.splitlines()
    assert path == str((project / "env" / "prod.env").resolve())
    assert prompt == r"\[\e[36m\][uv-env: prod]\[\e[0m\]"


def test_hook_marks_an_unselected_profile(project: Path) -> None:
    result = run_bash(project, f"source {shlex.quote(str(HOOK))}; printf '%s\\n' \"$UV_ENV_PROMPT\"")

    assert result.stdout.strip() == r"\[\e[33m\][uv-env: <unset>]\[\e[0m\]"


@pytest.mark.skipif(UV is None, reason="uv is not installed")
def test_uv_loads_selected_profile_and_applies_a_switch(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(project / "nested")
    runner = CliRunner()

    first = runner.invoke(cli.app, ["use", "prod"])
    assert first.exit_code == 0, first.output

    command = "python -c 'import os; print(os.environ[\"UV_ENV_TEST_PROFILE\"])'"
    script = f"source {shlex.quote(str(HOOK))}; {UV} run --no-project --offline {command}"
    assert run_bash(project, script).stdout.strip() == "prod"

    second = runner.invoke(cli.app, ["use", "dev"])
    assert second.exit_code == 0, second.output
    assert run_bash(project, script).stdout.strip() == "dev"


def test_completion_commands_and_shells(project: Path) -> None:
    script = (
        f"source {shlex.quote(str(HOOK))}; "
        "COMP_WORDS=(uv-env ''); COMP_CWORD=1; _uv_env_complete; printf '%s\\n' \"${COMPREPLY[@]}\"; "
        "COMP_WORDS=(uv-env init ''); COMP_CWORD=2; _uv_env_complete; printf '%s\\n' \"${COMPREPLY[@]}\""
    )

    result = run_bash(project, script)

    lines = result.stdout.splitlines()
    assert set(lines[: len(get_command(cli.app).commands)]) == set(get_command(cli.app).commands)
    assert lines[-2:] == ["zsh", "bash"]


def test_completion_includes_hidden_profiles(project: Path) -> None:
    (project / "env" / ".preview.env").touch()
    script = (
        f"source {shlex.quote(str(HOOK))}; "
        "COMP_WORDS=(uv-env use ''); COMP_CWORD=2; _uv_env_complete; printf '%s\\n' \"${COMPREPLY[@]}\""
    )

    result = run_bash(project, script)

    assert result.stdout.splitlines() == [".preview", "dev", "prod"]


def test_re_sourcing_replaces_prompt_hook_without_repeating_the_prompt(project: Path) -> None:
    (project / "env" / cli.SELECTION_FILE).write_text("prod.env\n")
    script = (
        "PS1='base> '; PROMPT_COMMAND=existing_prompt; UV_ENV_FILE=outside.env; "
        f"source {shlex.quote(str(HOOK))}; source {shlex.quote(str(HOOK))}; "
        "printf '%s\\n%s\\n%s\\n' \"$UV_ENV_FILE\" \"$PS1\" \"$PROMPT_COMMAND\""
    )

    result = run_bash(project, script)

    environment_file, prompt, prompt_command = result.stdout.splitlines()
    assert environment_file == str((project / "env" / "prod.env").resolve())
    assert prompt == "${UV_ENV_PROMPT:+${UV_ENV_PROMPT} }base> "
    assert prompt_command == "existing_prompt;uv_env_refresh"
