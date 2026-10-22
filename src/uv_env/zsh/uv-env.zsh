# uv-env Zsh integration. This file is sourced by `uv-env init zsh`.

if [[ -n "${_UV_ENV_ZSH_LOADED:-}" ]]; then
    # Re-sourcing is a safe reload: remove only hooks we own, then restore the
    # shell state captured before the previous integration was applied.
    autoload -Uz add-zsh-hook
    add-zsh-hook -d chpwd uv_env_refresh 2>/dev/null
    add-zsh-hook -d precmd uv_env_refresh 2>/dev/null
    add-zsh-hook -d precmd _uv_env_register_completion 2>/dev/null
    _uv_env_restore_file
    PROMPT="$_UV_ENV_BASE_PROMPT"
fi

typeset -g _UV_ENV_ZSH_LOADED=1

typeset -g _UV_ENV_BASE_FILE_SET=0
typeset -g _UV_ENV_BASE_FILE=""
(( ${+UV_ENV_FILE} )) && {
    _UV_ENV_BASE_FILE_SET=1
    _UV_ENV_BASE_FILE="$UV_ENV_FILE"
}

typeset -g _UV_ENV_BASE_PROMPT="$PROMPT"
typeset -g UV_ENV_PROMPT=""

function _uv_env_restore_file() {
    if (( _UV_ENV_BASE_FILE_SET )); then
        export UV_ENV_FILE="$_UV_ENV_BASE_FILE"
    else
        unset UV_ENV_FILE
    fi
}

function uv_env_refresh() {
    local directory="$PWD" root="" profiles="" selection="" profile="" profile_path=""

    # A pyproject.toml is enough for `uv run` to treat a directory as a project.
    while [[ "$directory" != "/" ]]; do
        if [[ -f "$directory/pyproject.toml" ]]; then
            root="$directory"
            break
        fi
        directory="${directory:h}"
    done

    if [[ -z "$root" ]]; then
        UV_ENV_PROMPT=""
        _uv_env_restore_file
        return
    fi

    if [[ -d "$root/.env" ]]; then
        profiles="$root/.env"
    elif [[ -d "$root/env" ]]; then
        profiles="$root/env"
    else
        UV_ENV_PROMPT="%F{yellow}[uv-env: none]%f"
        _uv_env_restore_file
        return
    fi

    selection="$profiles/.uv-env"
    if [[ ! -f "$selection" ]]; then
        UV_ENV_PROMPT="%F{yellow}[uv-env: none]%f"
        _uv_env_restore_file
        return
    fi

    profile="$(<"$selection")"
    if [[ -z "$profile" || "$profile" != *.env || "$profile" == */* ||
          "$profile" == "." || "$profile" == ".." ||
          "$profile" == *$'\n'* || "$profile" == *$'\r'* ]]; then
        UV_ENV_PROMPT="%F{red}[uv-env: invalid]%f"
        _uv_env_restore_file
        return
    fi

    profile_path="$profiles/$profile"
    if [[ ! -f "$profile_path" || -L "$profile_path" ]]; then
        UV_ENV_PROMPT="%F{red}[uv-env: invalid]%f"
        _uv_env_restore_file
        return
    fi

    export UV_ENV_FILE="${profile_path:A}"
    UV_ENV_PROMPT="%F{cyan}[uv-env: ${profile%.env}]%f"
}

autoload -Uz add-zsh-hook
add-zsh-hook chpwd uv_env_refresh
add-zsh-hook precmd uv_env_refresh

setopt PROMPT_SUBST
PROMPT='${UV_ENV_PROMPT:+${UV_ENV_PROMPT} }'"${_UV_ENV_BASE_PROMPT}"

# Complete only the profile argument of `uv-env use`. This runs on Tab, not on
# every prompt, and deliberately mirrors the same .env/ then env/ lookup.
function _uv_env_complete_profiles() {
    local directory="$PWD" root="" profiles="" profile
    local -a names

    while [[ "$directory" != "/" ]]; do
        if [[ -f "$directory/pyproject.toml" ]]; then
            root="$directory"
            break
        fi
        directory="${directory:h}"
    done
    [[ -z "$root" ]] && return 1

    if [[ -d "$root/.env" ]]; then
        profiles="$root/.env"
    elif [[ -d "$root/env" ]]; then
        profiles="$root/env"
    else
        return 1
    fi

    # D includes dot-prefixed profiles such as .prod.env; N handles no matches.
    for profile in "$profiles"/*.env(ND); do
        [[ -f "$profile" && ! -L "$profile" ]] || continue
        names+=("${profile:t:r}")
    done
    (( ${#names} )) && compadd -Q -a names
}

function _uv-env() {
    local -a commands
    commands=(list status use select clear init uninit)

    if (( CURRENT == 2 )); then
        compadd -a commands
        return
    fi

    case "${words[2]:-}" in
        use)
            (( CURRENT == 3 )) && _uv_env_complete_profiles
            ;;
        init|uninit)
            (( CURRENT == 3 )) && compadd zsh
            ;;
    esac
}

# Do not run compinit ourselves: it can be comparatively expensive and is
# user-managed. Register now when it is ready, or at the first prompt after a
# later compinit invocation.
function _uv_env_register_completion() {
    (( $+functions[compdef] )) || return 0
    compdef _uv-env uv-env
    add-zsh-hook -d precmd _uv_env_register_completion
}

_uv_env_register_completion
(( $+functions[compdef] )) || add-zsh-hook precmd _uv_env_register_completion
uv_env_refresh
