from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from uv_env import cli


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "project"
    profiles = root / "env"
    profiles.mkdir(parents=True)
    (root / "pyproject.toml").touch()
    (profiles / "dev.env").write_text("MODE=dev\n")
    (profiles / "prod.env").write_text("MODE=prod\n")
    nested = root / "src" / "package"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    return root


def test_use_list_status_and_clear(project: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(cli.app, ["use", "prod"])
    assert result.exit_code == 0, result.output
    assert (project / "env" / cli.SELECTION_FILE).read_text() == "prod.env\n"

    result = runner.invoke(cli.app, ["list"])
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == ["dev", "prod *"]

    result = runner.invoke(cli.app, ["status"])
    assert result.exit_code == 0, result.output
    assert "Selected profile: prod" in result.output
    assert str(project / "env" / "prod.env") in result.output

    result = runner.invoke(cli.app, ["clear"])
    assert result.exit_code == 0, result.output
    assert not (project / "env" / cli.SELECTION_FILE).exists()


def test_hidden_profile_is_selectable(project: Path) -> None:
    (project / "env" / ".preview.env").write_text("MODE=preview\n")

    result = CliRunner().invoke(cli.app, ["use", ".preview"])

    assert result.exit_code == 0, result.output
    assert (project / "env" / cli.SELECTION_FILE).read_text() == ".preview.env\n"


def test_use_prefers_dotenv_directory(project: Path) -> None:
    dotenv = project / ".env"
    dotenv.mkdir()
    (dotenv / "dev.env").write_text("MODE=preferred\n")

    result = CliRunner().invoke(cli.app, ["use", "dev"])

    assert result.exit_code == 0, result.output
    assert (dotenv / cli.SELECTION_FILE).read_text() == "dev.env\n"
    assert not (project / "env" / cli.SELECTION_FILE).exists()


@pytest.mark.parametrize("name", ["../dev", "nested/dev", "bad\nname"])
def test_use_rejects_non_profile_names(project: Path, name: str) -> None:
    result = CliRunner().invoke(cli.app, ["use", name])

    assert result.exit_code != 0
    assert "Provide a profile name, not a path." in result.output


def test_status_rejects_invalid_selection(project: Path) -> None:
    (project / "env" / cli.SELECTION_FILE).write_text("missing.env\n")

    result = CliRunner().invoke(cli.app, ["status"])

    assert result.exit_code != 0
    assert "Profile does not exist: missing.env" in result.output


def test_init_writes_guarded_block_and_uninit_removes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: tmp_path))
    runner = CliRunner()

    result = runner.invoke(cli.app, ["init"])
    assert result.exit_code == 0, result.output
    zshrc = tmp_path / ".zshrc"
    contents = zshrc.read_text()
    assert cli.ZSH_START_MARKER in contents
    assert "if [[ -r " in contents
    assert "source " in contents

    result = runner.invoke(cli.app, ["uninit"])
    assert result.exit_code == 0, result.output
    assert cli.ZSH_START_MARKER not in zshrc.read_text()


def test_update_managed_block_replaces_existing_block() -> None:
    old = f"before\n{cli.ZSH_START_MARKER}\nold\n{cli.ZSH_END_MARKER}\nafter\n"
    block = f"{cli.ZSH_START_MARKER}\nnew\n{cli.ZSH_END_MARKER}"

    updated = cli.update_managed_block(old, block)

    assert updated == f"before\n{block}\nafter\n"
    assert cli.update_managed_block(updated, None) == "before\nafter"
