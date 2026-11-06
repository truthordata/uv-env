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
    env_files = root / "env"
    env_files.mkdir(parents=True)
    (root / "pyproject.toml").touch()
    (env_files / "dev.env").write_text("UV_ENV_TEST_STACK=dev\n")
    (env_files / "prod.env").write_text("UV_ENV_TEST_STACK=prod\n")
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


def test_hook_exports_selected_env_stack(project: Path) -> None:
    (project / "env" / cli.SELECTION_FILE).write_text("prod.env\n")
    script = f"PS1='base> '; source {shlex.quote(str(HOOK))}; printf '%s\\n%s\\n' \"$UV_ENV_FILE\" \"$UV_ENV_PROMPT\""

    result = run_bash(project, script)

    path, prompt = result.stdout.splitlines()
    assert path == str((project / "env" / "prod.env").resolve())
    assert prompt == r"\[\e[36m\][uv-env: prod]\[\e[0m\]"


def test_hook_prefixes_an_alias_stack_with_at(project: Path) -> None:
    (project / "env" / cli.SELECTION_FILE).write_text("use @test\nalias test dev.env prod.env\n")
    script = f"source {shlex.quote(str(HOOK))}; printf '%s\n' \"$UV_ENV_PROMPT\""

    assert run_bash(project, script).stdout.strip() == r"\[\e[36m\][uv-env: @test]\[\e[0m\]"


def test_hook_marks_an_unselected_env_stack(project: Path) -> None:
    result = run_bash(project, f"source {shlex.quote(str(HOOK))}; printf '%s\\n' \"$UV_ENV_PROMPT\"")

    assert result.stdout.strip() == r"\[\e[33m\][uv-env: <unset>]\[\e[0m\]"


def test_make_wrapper_loads_later_env_file_override(project: Path, tmp_path: Path) -> None:
    (project / "env" / cli.SELECTION_FILE).write_text("use @test\nalias test dev.env prod.env\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        "#!/usr/bin/env bash\n"
        "shift\n"
        "set -a\n"
        "for env_file in $UV_ENV_FILE; do . \"$env_file\"; done\n"
        "set +a\n"
        "exec \"$@\"\n"
    )
    fake_make = fake_bin / "make"
    fake_make.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$UV_ENV_TEST_STACK\"\n")
    fake_uv.chmod(0o755)
    fake_make.chmod(0o755)

    script = (
        f"PATH={shlex.quote(str(fake_bin))}:$PATH; _UV_ENV_WRAP_MAKE=1; "
        f"source {shlex.quote(str(HOOK))}; make target"
    )

    assert run_bash(project, script).stdout.strip() == "prod"


@pytest.mark.skipif(UV is None, reason="uv is not installed")
def test_uv_end_to_end_loads_an_alias_stack_with_later_override(
    project: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(project / "nested")
    runner = CliRunner()

    result = runner.invoke(cli.app, ["use", "--alias", "test", "dev", "prod"])
    assert result.exit_code == 0, result.output

    command = "python -c 'import os; print(os.environ[\"UV_ENV_TEST_STACK\"])'"
    cache = tmp_path / "uv-cache"
    script = (
        f"source {shlex.quote(str(HOOK))}; "
        f"UV_CACHE_DIR={shlex.quote(str(cache))} {UV} run --no-project --offline {command}"
    )
    assert run_bash(project, script).stdout.strip() == "prod"


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


def test_completion_includes_env_files_and_aliases(project: Path) -> None:
    (project / "env" / ".preview.env").touch()
    nested = project / "env" / "services"
    nested.mkdir()
    (nested / "api.env").touch()
    (project / "env" / cli.SELECTION_FILE).write_text("use @test\nalias test dev.env prod.env\n")
    script = (
        f"source {shlex.quote(str(HOOK))}; "
        "COMP_WORDS=(uv-env use ''); COMP_CWORD=2; _uv_env_complete; printf '%s\\n' \"${COMPREPLY[@]}\""
    )

    result = run_bash(project, script)

    assert set(result.stdout.splitlines()) == {".preview", "dev", "prod", "services/api", "@test"}


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
