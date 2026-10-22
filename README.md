# uv-env

`uv-env` selects a local dotenv profile for a uv project. It is deliberately
small: profile files and the current selection are local environment state; the
shell hook only sets `UV_ENV_FILE`, which uv reads when it runs.

## Install

Install once with uv, then enable the Zsh prompt integration:

```sh
uv tool install uv-env
uv-env init
```

`init` works on macOS and Linux. It adds a small, managed `source` block to
`~/.zshrc`; rerunning it after an upgrade updates that block. Remove it with
`uv-env uninit`.

## Remove

For a full cleanup, remove the shell block before uninstalling the tool:

```sh
uv-env uninit
uv tool uninstall uv-env
```

The managed block checks whether its installed hook still exists, so directly
uninstalling the tool cannot break later Zsh startup. Rerun `uv-env init` after
upgrading to replace an older integration block with this guarded version.

## Development

Run the test suite with pytest through uv:

```sh
uv run pytest
```

The suite covers the CLI and Zsh integration, including a real `uv run` check
that a selected profile is loaded and that switching profiles changes the next
command's environment. Zsh- or uv-specific tests are skipped when those tools
are unavailable.

## Project layout

Put named dotenv files in `.env/` (preferred) or `env/`. The selection is a
plain filename in `.uv-env` alongside them. Treat the entire directory like a
dotenv file: keep it out of version control, including the selection. The
repository's `.gitignore` already ignores both `.env/` and `env/`.

```text
my-project/
├── pyproject.toml
└── .env/
    ├── dev.env
    ├── prod.env
    └── .uv-env             # contains: dev.env
```

Select a profile and use uv normally:

```sh
uv-env use dev
uv run python -c 'import os; print(os.environ["DATABASE_URL"])'
```

`uv-env list`, `uv-env status`, and `uv-env clear` respectively list, inspect,
and clear the selection. Profile names may be supplied with or without the
`.env` suffix. In Zsh, `uv-env <Tab>` completes commands and `uv-env use <Tab>`
completes profile names without their suffix. Completion candidates must be
regular files ending in `.env` in the nearest project's `.env/` or `env/`
directory; dot-prefixed profiles such as `.prod.env` are supported and complete
as `.prod`.

For an interactive picker, run `uv-env select`. When [fzf](https://github.com/junegunn/fzf)
is installed it provides a searchable up/down-arrow menu; otherwise uv-env
falls back to a numbered prompt without adding fzf as a required dependency.

When Zsh enters a directory below a project, the prompt shows the active
profile, for example `[uv-env: dev]`. With no selection it shows
`[uv-env: none]`; an invalid selector is shown in red and is never passed to
uv. Leaving the project restores the previous value of `UV_ENV_FILE`.
