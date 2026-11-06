from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from uv_env import cli


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "project"
    env_files = root / "env"
    env_files.mkdir(parents=True)
    (root / "pyproject.toml").touch()
    (env_files / "dev.env").write_text("MODE=dev\n")
    (env_files / "prod.env").write_text("MODE=prod\n")
    nested = root / "src" / "package"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    return root


def test_use_list_status_and_clear(project: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(cli.app, ["use", "prod"])
    assert result.exit_code == 0, result.output
    assert (project / "env" / cli.SELECTION_FILE).read_text() == "use prod.env\n"

    result = runner.invoke(cli.app, ["list"])
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == ["Env files:", "  dev", "  prod *"]

    result = runner.invoke(cli.app, ["status"])
    assert result.exit_code == 0, result.output
    assert "Selected env stack: prod" in result.output
    assert str(project / "env" / "prod.env") in result.output

    result = runner.invoke(cli.app, ["clear"])
    assert result.exit_code == 0, result.output
    assert not (project / "env" / cli.SELECTION_FILE).exists()


def test_hidden_env_file_is_selectable(project: Path) -> None:
    (project / "env" / ".preview.env").write_text("MODE=preview\n")

    result = CliRunner().invoke(cli.app, ["use", ".preview"])

    assert result.exit_code == 0, result.output
    assert (project / "env" / cli.SELECTION_FILE).read_text() == "use .preview.env\n"


def test_nested_env_file_is_selectable(project: Path) -> None:
    nested = project / "env" / "services"
    nested.mkdir()
    (nested / "api.env").write_text("MODE=api\n")

    result = CliRunner().invoke(cli.app, ["use", "services/api"])

    assert result.exit_code == 0, result.output
    assert (project / "env" / cli.SELECTION_FILE).read_text() == "use services/api.env\n"


def test_use_selects_an_ordered_stack_and_saves_an_alias(project: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(cli.app, ["use", "--alias", "dev", "dev", "prod"])

    assert result.exit_code == 0, result.output
    assert result.output.strip() == "Selected env stack: dev"
    assert (project / "env" / cli.SELECTION_FILE).read_text() == (
        "use @dev\nalias dev dev.env prod.env\n"
    )

    result = runner.invoke(cli.app, ["use", "dev", "prod"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "Selected env stack: dev+prod"

    result = runner.invoke(cli.app, ["use", "@dev"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "Selected env stack: dev"


def test_use_prefers_dotenv_directory(project: Path) -> None:
    dotenv = project / ".env"
    dotenv.mkdir()
    (dotenv / "dev.env").write_text("MODE=preferred\n")

    result = CliRunner().invoke(cli.app, ["use", "dev"])

    assert result.exit_code == 0, result.output
    assert (dotenv / cli.SELECTION_FILE).read_text() == "use dev.env\n"
    assert not (project / "env" / cli.SELECTION_FILE).exists()


@pytest.mark.parametrize("name", ["../dev", "/tmp/dev", "bad\nname"])
def test_use_rejects_non_env_file_names(project: Path, name: str) -> None:
    result = CliRunner().invoke(cli.app, ["use", name])

    assert result.exit_code != 0
    assert "Provide an env-file path without whitespace or .. segments." in result.output


def test_status_rejects_invalid_selection(project: Path) -> None:
    (project / "env" / cli.SELECTION_FILE).write_text("missing.env\n")

    result = CliRunner().invoke(cli.app, ["status"])

    assert result.exit_code != 0
    assert "Env file does not exist: missing.env" in result.output


def test_init_writes_guarded_block_and_uninit_removes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: tmp_path))
    runner = CliRunner()

    result = runner.invoke(cli.app, ["init", "zsh"])
    assert result.exit_code == 0, result.output
    zshrc = tmp_path / ".zshrc"
    contents = zshrc.read_text()
    assert cli.START_MARKER in contents
    assert "if [[ -r " in contents
    assert "source " in contents
    assert "_UV_ENV_WRAP_MAKE" not in contents

    result = runner.invoke(cli.app, ["uninit", "zsh"])
    assert result.exit_code == 0, result.output
    assert cli.START_MARKER not in zshrc.read_text()


def test_bash_init_writes_guarded_block_and_uninit_removes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: tmp_path))
    runner = CliRunner()

    result = runner.invoke(cli.app, ["init", "bash"])
    assert result.exit_code == 0, result.output
    bashrc = tmp_path / ".bashrc"
    contents = bashrc.read_text()
    assert cli.START_MARKER in contents
    assert "if [[ -r " in contents
    assert "source " in contents

    result = runner.invoke(cli.app, ["uninit", "bash"])
    assert result.exit_code == 0, result.output
    assert cli.START_MARKER not in bashrc.read_text()


def test_init_can_enable_the_make_wrapper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: tmp_path))

    result = CliRunner().invoke(cli.app, ["init", "bash", "--wrap-make"])

    assert result.exit_code == 0, result.output
    contents = (tmp_path / ".bashrc").read_text()
    assert "_UV_ENV_WRAP_MAKE=1" in contents
    assert "unset _UV_ENV_WRAP_MAKE" in contents


def test_init_requires_a_supported_shell() -> None:
    runner = CliRunner()

    missing = runner.invoke(cli.app, ["init"])
    invalid = runner.invoke(cli.app, ["init", "fish"])

    assert missing.exit_code != 0
    assert invalid.exit_code != 0
    assert "Supported shells: zsh, bash" in invalid.output


def test_update_managed_block_replaces_existing_block() -> None:
    old = f"before\n{cli.START_MARKER}\nold\n{cli.END_MARKER}\nafter\n"
    block = f"{cli.START_MARKER}\nnew\n{cli.END_MARKER}"

    updated = cli.update_managed_block(old, block)

    assert updated == f"before\n{block}\nafter\n"
    assert cli.update_managed_block(updated, None) == "before\nafter"
