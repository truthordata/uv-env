"""Commands for selecting a project's uv environment-file stack."""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False)

ENV_DIRECTORIES = (".env", "env")
SELECTION_FILE = ".uv-env"
START_MARKER = "# >>> uv-env shell integration >>>"
END_MARKER = "# <<< uv-env shell integration <<<"


def find_project_root() -> Path:
    """Return the nearest directory that uv can treat as a project."""
    for directory in (Path.cwd(), *Path.cwd().parents):
        if (directory / "pyproject.toml").is_file():
            return directory
    raise typer.BadParameter("No uv project found in this directory or its parents.")


def env_dir() -> Path:
    """Return the project's env-file directory, preferring ``.env/``."""
    root = find_project_root()
    for name in ENV_DIRECTORIES:
        directory = root / name
        if directory.is_dir():
            return directory
    expected = " or ".join(f"{name}/" for name in ENV_DIRECTORIES)
    raise typer.BadParameter(f"No env-file directory in {root}; expected {expected}.")


def env_file_path(name: str) -> Path:
    """Validate *name* and return its env-file path."""
    candidate_name = Path(name)
    if (
        not name
        or candidate_name.is_absolute()
        or ".." in candidate_name.parts
        or name in {".", ".."}
        or any(character.isspace() for character in name)
        or "\n" in name
        or "\r" in name
    ):
        raise typer.BadParameter("Provide an env-file path without whitespace or .. segments.")
    if not name.endswith(".env"):
        name += ".env"

    directory = env_dir().resolve()
    candidate = directory / name
    if candidate.is_symlink():
        raise typer.BadParameter("Env file must be a regular file, not a symlink.")
    path = candidate.resolve()
    if not path.is_relative_to(directory):
        raise typer.BadParameter("Env file must be inside the env-file directory.")
    if not path.is_file():
        raise typer.BadParameter(f"Env file does not exist: {name}")
    return path


def env_files() -> list[Path]:
    """Return selectable env files in display order."""
    return [
        path
        for path in sorted(env_dir().rglob("*.env"))
        if path.is_file() and not path.is_symlink()
    ]


def env_file_display_name(path: Path) -> str:
    """Return an env-file path relative to the env directory, without `.env`."""
    return path.relative_to(env_dir().resolve()).with_suffix("").as_posix()


@dataclass(frozen=True)
class EnvStack:
    """An ordered selection of env files, optionally identified by an alias."""

    name: str | None
    files: tuple[Path, ...]

    @property
    def display_name(self) -> str:
        return self.name or "+".join(env_file_display_name(path) for path in self.files)


@dataclass
class StackConfig:
    selected: tuple[str, ...] | None
    aliases: dict[str, tuple[str, ...]]


def _validate_alias(name: str) -> str:
    if not name or name.startswith("@") or any(character.isspace() for character in name):
        raise typer.BadParameter("Alias names cannot be empty, start with @, or contain whitespace.")
    return name


def _canonical_env_file_name(name: str) -> str:
    if name.startswith("@"):
        raise typer.BadParameter("An alias must be the only selection argument.")
    path = env_file_path(name)
    return path.relative_to(env_dir().resolve()).as_posix()


def read_stack_config() -> StackConfig:
    """Read the lightweight selection and alias format, accepting legacy files."""
    path = env_dir() / SELECTION_FILE
    if not path.is_file():
        return StackConfig(None, {})
    lines = [line.strip() for line in path.read_text().splitlines() if line.strip() and not line.startswith("#")]
    if not lines:
        return StackConfig(None, {})
    if len(lines) == 1 and not lines[0].startswith(("use ", "alias ")):
        return StackConfig((lines[0],), {})

    selected: tuple[str, ...] | None = None
    aliases: dict[str, tuple[str, ...]] = {}
    for line in lines:
        fields = line.split()
        if fields[0] == "use" and len(fields) > 1 and selected is None:
            selected = tuple(fields[1:])
        elif fields[0] == "alias" and len(fields) > 2 and fields[1] not in aliases:
            aliases[_validate_alias(fields[1])] = tuple(fields[2:])
        else:
            raise typer.BadParameter(f"Invalid {SELECTION_FILE} entry: {line}")
    return StackConfig(selected, aliases)


def write_stack_config(config: StackConfig) -> None:
    """Write a canonical, shell-readable selection and alias configuration."""
    lines: list[str] = []
    if config.selected:
        lines.append("use " + " ".join(config.selected))
    lines.extend(f"alias {name} {' '.join(files)}" for name, files in config.aliases.items())
    path = env_dir() / SELECTION_FILE
    if lines:
        path.write_text("\n".join(lines) + "\n")
    elif path.exists():
        path.unlink()


def resolve_stack(selection: tuple[str, ...], aliases: dict[str, tuple[str, ...]]) -> EnvStack:
    """Resolve an ad hoc env-file stack or one saved alias."""
    if len(selection) == 1 and selection[0].startswith("@"):
        alias = selection[0][1:]
        if alias not in aliases:
            raise typer.BadParameter(f"Alias does not exist: @{alias}")
        return EnvStack(alias, tuple(env_file_path(name) for name in aliases[alias]))
    return EnvStack(None, tuple(env_file_path(name) for name in selection))


def selected_stack() -> EnvStack | None:
    """Return the currently selected stack, if any."""
    config = read_stack_config()
    return resolve_stack(config.selected, config.aliases) if config.selected else None


@app.command("list")
def list_env_files() -> None:
    """List env files and saved stack aliases."""
    config = read_stack_config()
    selected = selected_stack()
    selected_names = {path.name for path in selected.files} if selected and selected.name is None else set()
    typer.echo("Env files:")
    for path in env_files():
        marker = " *" if path.name in selected_names else ""
        typer.echo(f"  {env_file_display_name(path)}{marker}")
    if config.aliases:
        typer.echo("Saved stacks:")
        for name, files in config.aliases.items():
            marker = " *" if selected and selected.name == name else ""
            typer.echo(f"  @{name}{marker}  {' + '.join(Path(file).with_suffix('').as_posix() for file in files)}")


@app.command()
def status() -> None:
    """Show the selected env stack, if any."""
    selected = selected_stack()
    if selected is None:
        typer.echo("No env stack selected.")
        return
    typer.echo(f"Selected env stack: {selected.display_name}")
    for path in selected.files:
        typer.echo(f"Environment file: {path}")


@app.command()
def use(
    names: list[str] = typer.Argument(..., help="Env-file names or one @alias."),
    alias: str | None = typer.Option(None, "--alias", help="Save this stack under NAME."),
) -> None:
    """Select one or more env files, or a saved @alias."""
    config = read_stack_config()
    selection = tuple(names)
    if alias:
        alias = _validate_alias(alias)
        if len(selection) == 1 and selection[0].startswith("@"):
            raise typer.BadParameter("An alias must contain env files, not another alias.")
        files = tuple(_canonical_env_file_name(name) for name in selection)
        config.aliases[alias] = files
        selection = (f"@{alias}",)
    elif len(selection) == 1 and selection[0].startswith("@"):
        resolve_stack(selection, config.aliases)
    else:
        selection = tuple(_canonical_env_file_name(name) for name in selection)
    stack = resolve_stack(selection, config.aliases)
    config.selected = selection
    write_stack_config(config)
    typer.echo(f"Selected env stack: {stack.display_name}")


@app.command()
def select() -> None:
    """Interactively select an env file; use fzf for an arrow-key picker when available."""
    available = env_files()
    if not available:
        raise typer.BadParameter("No env files found.")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise typer.BadParameter("The select command requires an interactive terminal.")

    fzf = shutil.which("fzf")
    if fzf:
        result = subprocess.run(
            [fzf, "--prompt=uv-env> ", "--height=10", "--reverse"],
            input="\n".join(env_file_display_name(path) for path in available) + "\n",
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 130:
            return
        if result.returncode != 0:
            typer.echo(result.stderr, err=True, nl=False)
            raise typer.Exit(result.returncode)
        choice = result.stdout.strip()
        if not choice:
            return
        use([choice])
        return

    typer.echo("fzf is not installed; choose by number instead.")
    for index, path in enumerate(available, start=1):
        typer.echo(f"{index}. {env_file_display_name(path)}")
    choice = typer.prompt("Profile number", type=int)
    if choice < 1 or choice > len(available):
        raise typer.BadParameter("Profile number is out of range.")
    use([env_file_display_name(available[choice - 1])])


@app.command()
def clear() -> None:
    """Clear the selected stack without deleting env files or aliases."""
    config = read_stack_config()
    if config.selected:
        config.selected = None
        write_stack_config(config)
        typer.echo("Env stack selection cleared.")
    else:
        typer.echo("No env stack was selected.")


def integration_file(shell: str) -> Path:
    """Return the packaged integration script for *shell*."""
    extension = "zsh" if shell == "zsh" else "bash"
    path = Path(__file__).resolve().parent / "shell" / shell / f"uv-env.{extension}"
    if not path.is_file():
        raise typer.BadParameter(f"{shell.capitalize()} integration file is missing: {path}")
    return path


def update_managed_block(
    contents: str,
    block: str | None,
) -> str:
    """Replace or remove a shell-integration block owned by uv-env."""
    pattern = re.compile(
        rf"(?m)^{re.escape(START_MARKER)}\n.*?^{re.escape(END_MARKER)}\n?",
        re.DOTALL,
    )
    if pattern.search(contents):
        def replacement(match: re.Match[str]) -> str:
            if block is None:
                return ""
            return block + ("\n" if match.group().endswith("\n") else "")

        return pattern.sub(replacement, contents).rstrip() + ("\n" if block else "")
    if block is None:
        return contents
    return contents.rstrip() + ("\n\n" if contents.strip() else "") + block + "\n"


def shell_configuration(shell: str) -> tuple[Path, Path, str]:
    """Return the rc file and managed-block details for a supported shell."""
    shell = shell.lower()
    if shell == "zsh":
        return (
            Path.home() / ".zshrc",
            integration_file(shell),
            "Zsh",
        )
    if shell == "bash":
        return (
            Path.home() / ".bashrc",
            integration_file(shell),
            "Bash",
        )
    raise typer.BadParameter("Supported shells: zsh, bash")


@app.command()
def init(
    shell: str = typer.Argument(..., help="Shell integration: zsh or bash."),
    wrap_make: bool = typer.Option(
        False,
        "--wrap-make",
        help="Run make through uv with the selected env stack in active projects.",
    ),
) -> None:
    """Install Zsh or Bash shell integration."""
    rc_file, hook, display_name = shell_configuration(shell)
    source_line = f"source {shlex.quote(str(hook))}"
    wrap_make_lines = ""
    if wrap_make:
        wrap_make_lines = "    _UV_ENV_WRAP_MAKE=1\n"
        wrap_make_lines += "    source " + shlex.quote(str(hook)) + "\n"
        wrap_make_lines += "    unset _UV_ENV_WRAP_MAKE\n"
    else:
        wrap_make_lines = f"    {source_line}\n"
    block = (
        f"{START_MARKER}\n"
        f"if [[ -r {shlex.quote(str(hook))} ]]; then\n"
        f"{wrap_make_lines}"
        "fi\n"
        f"{END_MARKER}"
    )
    contents = rc_file.read_text() if rc_file.exists() else ""
    rc_file.write_text(update_managed_block(contents, block))
    typer.echo(f"Configured {display_name} integration in {rc_file}")
    typer.echo(f"Restart {display_name} or run: source ~/{rc_file.name}")


@app.command()
def uninit(shell: str = typer.Argument(..., help="Shell integration: zsh or bash.")) -> None:
    """Remove the shell integration installed by ``uv-env init``."""
    rc_file, _, display_name = shell_configuration(shell)
    if not rc_file.exists():
        typer.echo(f"{display_name} integration is not configured.")
        return
    original = rc_file.read_text()
    updated = update_managed_block(original, None)
    if updated == original:
        typer.echo(f"{display_name} integration is not configured.")
        return
    rc_file.write_text(updated)
    typer.echo(f"Removed {display_name} integration from {rc_file}")


if __name__ == "__main__":
    app()
