from __future__ import annotations

import shlex
import shutil
import subprocess
import os
from pathlib import Path

import pytest
from typer.main import get_command
from typer.testing import CliRunner

from uv_env import cli

ZSH = shutil.which("zsh")
UV = shutil.which("uv")
HOOK = Path(__file__).parents[1] / "src" / "uv_env" / "shell" / "zsh" / "uv-env.zsh"

pytestmark = pytest.mark.skipif(ZSH is None, reason="zsh is not installed")


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


def run_zsh(project: Path, script: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ | {"ZDOTDIR": str(project.parent)}
    return subprocess.run(
        [ZSH, "-fc", script],
        cwd=project / "nested",
        text=True,
        capture_output=True,
        check=True,
        env=environment,
    )


def test_hook_is_valid_zsh() -> None:
    subprocess.run([ZSH, "-n", str(HOOK)], check=True)


def test_hook_exports_selected_profile(project: Path) -> None:
    (project / "env" / cli.SELECTION_FILE).write_text("prod.env\n")
    script = f"source {shlex.quote(str(HOOK))}; print -r -- $UV_ENV_FILE; print -r -- $UV_ENV_PROMPT"

    result = run_zsh(project, script)

    path, prompt = result.stdout.splitlines()
    assert path == str((project / "env" / "prod.env").resolve())
    assert prompt == "%F{cyan}[uv-env: prod]%f"


def test_hook_marks_an_unselected_profile(project: Path) -> None:
    result = run_zsh(project, f"source {shlex.quote(str(HOOK))}; print -r -- $UV_ENV_PROMPT")

    assert result.stdout.strip() == "%F{yellow}[uv-env: <unset>]%f"


def test_make_wrapper_loads_the_selected_profile(project: Path, tmp_path: Path) -> None:
    (project / "env" / cli.SELECTION_FILE).write_text("prod.env\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        "#!/usr/bin/env bash\n"
        "shift\n"
        "test \"$1\" = --env-file\n"
        "env_file=$2\n"
        "shift 2\n"
        "set -a\n"
        ". \"$env_file\"\n"
        "set +a\n"
        "exec \"$@\"\n"
    )
    fake_make = fake_bin / "make"
    fake_make.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$UV_ENV_TEST_PROFILE\"\n")
    fake_uv.chmod(0o755)
    fake_make.chmod(0o755)

    script = (
        f"PATH={shlex.quote(str(fake_bin))}:$PATH; _UV_ENV_WRAP_MAKE=1; "
        f"source {shlex.quote(str(HOOK))}; make target"
    )

    assert run_zsh(project, script).stdout.strip() == "prod"


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
    assert run_zsh(project, script).stdout.strip() == "prod"

    second = runner.invoke(cli.app, ["use", "dev"])
    assert second.exit_code == 0, second.output
    assert run_zsh(project, script).stdout.strip() == "dev"


def test_completion_commands_match_cli(project: Path) -> None:
    script = (
        f"source {shlex.quote(str(HOOK))}; "
        'function compadd() { local name="${@[-1]}"; completed=("${(@P)name}"); }; '
        'words=(uv-env ""); CURRENT=2; _uv-env; print -rl -- $completed'
    )

    result = run_zsh(project, script)
    completed = set(result.stdout.splitlines())
    commands = set(get_command(cli.app).commands)

    assert completed == commands


def test_completion_offers_supported_shells(project: Path) -> None:
    script = (
        f"source {shlex.quote(str(HOOK))}; "
        'function compadd() { completed=("$@"); }; '
        'words=(uv-env init ""); CURRENT=3; _uv-env; print -rl -- $completed'
    )

    result = run_zsh(project, script)

    assert result.stdout.splitlines() == ["zsh", "bash"]


def test_completion_includes_hidden_profiles(project: Path) -> None:
    (project / "env" / ".preview.env").touch()
    script = (
        f"source {shlex.quote(str(HOOK))}; "
        'function compadd() { local name="${@[-1]}"; completed=("${(@P)name}"); }; '
        "_uv_env_complete_profiles; print -rl -- $completed"
    )

    result = run_zsh(project, script)

    assert result.stdout.splitlines() == [".preview", "dev", "prod"]


def test_completion_is_initialized_when_zsh_has_not_done_so(project: Path) -> None:
    script = (
        f"source {shlex.quote(str(HOOK))}; "
        'print -r -- "$_comps[uv-env]"'
    )

    result = run_zsh(project, script)

    assert result.stdout.strip() == "_uv-env"


def test_re_sourcing_replaces_hooks_without_repeating_the_prompt(project: Path) -> None:
    (project / "env" / cli.SELECTION_FILE).write_text("prod.env\n")
    script = (
        "PROMPT='base> '; UV_ENV_FILE=outside.env; "
        "autoload -Uz compinit; compinit -C; "
        f"source {shlex.quote(str(HOOK))}; source {shlex.quote(str(HOOK))}; "
        "print -r -- $UV_ENV_FILE; print -r -- $PROMPT; "
        "print -rl -- $precmd_functions"
    )

    result = run_zsh(project, script)
    environment_file, prompt, *precmd_functions = result.stdout.splitlines()

    assert environment_file == str((project / "env" / "prod.env").resolve())
    assert prompt == "${UV_ENV_PROMPT:+${UV_ENV_PROMPT} }base> "
    assert precmd_functions.count("uv_env_refresh") == 1
