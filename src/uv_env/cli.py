"""Commands for selecting a project's uv environment-file profile."""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False)

PROFILE_DIRECTORIES = (".env", "env")
SELECTION_FILE = ".uv-env"
ZSH_START_MARKER = "# >>> uv-env zsh integration >>>"
ZSH_END_MARKER = "# <<< uv-env zsh integration <<<"


def find_project_root() -> Path:
    """Return the nearest directory that uv can treat as a project."""
    for directory in (Path.cwd(), *Path.cwd().parents):
        if (directory / "pyproject.toml").is_file():
            return directory
    raise typer.BadParameter("No uv project found in this directory or its parents.")


def profile_dir() -> Path:
    """Return the project's profile directory, preferring ``.env/``."""
    root = find_project_root()
    for name in PROFILE_DIRECTORIES:
        directory = root / name
        if directory.is_dir():
            return directory
    expected = " or ".join(f"{name}/" for name in PROFILE_DIRECTORIES)
    raise typer.BadParameter(f"No profile directory in {root}; expected {expected}.")


def profile_path(name: str) -> Path:
    """Validate *name* and return its profile path."""
    if (
        not name
        or Path(name).name != name
        or name in {".", ".."}
        or "\n" in name
        or "\r" in name
    ):
        raise typer.BadParameter("Provide a profile name, not a path.")
    if not name.endswith(".env"):
        name += ".env"

    directory = profile_dir().resolve()
    candidate = directory / name
    if candidate.is_symlink():
        raise typer.BadParameter("Profile must be a regular file, not a symlink.")
    path = candidate.resolve()
    if path.parent != directory:
        raise typer.BadParameter("Profile must be inside the profile directory.")
    if not path.is_file():
        raise typer.BadParameter(f"Profile does not exist: {name}")
    return path


def profiles() -> list[Path]:
    """Return selectable profiles in display order."""
    return [
        path
        for path in sorted(profile_dir().glob("*.env"))
        if path.is_file() and not path.is_symlink()
    ]


def select_profile(path: Path) -> None:
    """Persist a previously validated profile selection."""
    (profile_dir() / SELECTION_FILE).write_text(path.name + "\n")
    typer.echo(f"Selected profile: {path.stem}")


def selected_profile() -> Path | None:
    """Return the selected profile, or ``None`` when no profile is selected."""
    directory = profile_dir()
    selection = directory / SELECTION_FILE
    if not selection.is_file():
        return None

    name = selection.read_text().strip()
    if not name:
        raise typer.BadParameter(f"{SELECTION_FILE} is empty.")
    return profile_path(name)


@app.command("list")
def list_profiles() -> None:
    """List profiles; the selected profile is marked with an asterisk."""
    directory = profile_dir()
    selected = selected_profile()
    selected_name = selected.name if selected else None
    for path in profiles():
        marker = " *" if path.name == selected_name else ""
        typer.echo(f"{path.stem}{marker}")


@app.command()
def status() -> None:
    """Show the selected profile, if any."""
    selected = selected_profile()
    if selected is None:
        typer.echo("No profile selected.")
        return
    typer.echo(f"Selected profile: {selected.stem}")
    typer.echo(f"Environment file: {selected}")


@app.command()
def use(name: str) -> None:
    """Select NAME for this project (the .env suffix is optional)."""
    select_profile(profile_path(name))


@app.command()
def select() -> None:
    """Interactively select a profile; use fzf for an arrow-key picker when available."""
    available = profiles()
    if not available:
        raise typer.BadParameter("No .env profiles found.")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise typer.BadParameter("The select command requires an interactive terminal.")

    fzf = shutil.which("fzf")
    if fzf:
        result = subprocess.run(
            [fzf, "--prompt=uv-env> ", "--height=10", "--reverse"],
            input="\n".join(path.stem for path in available) + "\n",
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
        select_profile(profile_path(choice))
        return

    typer.echo("fzf is not installed; choose by number instead.")
    for index, path in enumerate(available, start=1):
        typer.echo(f"{index}. {path.stem}")
    choice = typer.prompt("Profile number", type=int)
    if choice < 1 or choice > len(available):
        raise typer.BadParameter("Profile number is out of range.")
    select_profile(available[choice - 1])


@app.command()
def clear() -> None:
    """Clear the project's selected profile without deleting any profiles."""
    selection = profile_dir() / SELECTION_FILE
    if selection.exists():
        selection.unlink()
        typer.echo("Profile selection cleared.")
    else:
        typer.echo("No profile was selected.")


def zsh_integration_file() -> Path:
    path = Path(__file__).resolve().parent / "zsh" / "uv-env.zsh"
    if not path.is_file():
        raise typer.BadParameter(f"Zsh integration file is missing: {path}")
    return path


def update_managed_block(contents: str, block: str | None) -> str:
    """Replace or remove the zsh block owned by uv-env."""
    pattern = re.compile(
        rf"(?m)^{re.escape(ZSH_START_MARKER)}\n.*?^{re.escape(ZSH_END_MARKER)}\n?",
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


@app.command()
def init(shell: str = typer.Argument("zsh", help="Shell integration to configure.")) -> None:
    """Install shell integration (currently zsh, on macOS and Linux)."""
    if shell != "zsh":
        raise typer.BadParameter("Supported shells: zsh")

    zshrc = Path.home() / ".zshrc"
    source_line = f"source {shlex.quote(str(zsh_integration_file()))}"
    block = (
        f"{ZSH_START_MARKER}\n"
        f"if [[ -r {shlex.quote(str(zsh_integration_file()))} ]]; then\n"
        f"    {source_line}\n"
        "fi\n"
        f"{ZSH_END_MARKER}"
    )
    contents = zshrc.read_text() if zshrc.exists() else ""
    zshrc.write_text(update_managed_block(contents, block))
    typer.echo(f"Configured Zsh integration in {zshrc}")
    typer.echo("Restart Zsh or run: source ~/.zshrc")


@app.command()
def uninit(shell: str = typer.Argument("zsh", help="Shell integration to remove.")) -> None:
    """Remove the shell integration installed by ``uv-env init``."""
    if shell != "zsh":
        raise typer.BadParameter("Supported shells: zsh")
    zshrc = Path.home() / ".zshrc"
    if not zshrc.exists():
        typer.echo("Zsh integration is not configured.")
        return
    original = zshrc.read_text()
    updated = update_managed_block(original, None)
    if updated == original:
        typer.echo("Zsh integration is not configured.")
        return
    zshrc.write_text(updated)
    typer.echo(f"Removed Zsh integration from {zshrc}")


if __name__ == "__main__":
    app()
