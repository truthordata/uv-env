# uv-env Zsh integration. This file is sourced by `uv-env init zsh`.

typeset _uv_env_zsh_dir="${${(%):-%N}:A:h}"
source "$_uv_env_zsh_dir/../uv-env-common.sh"
unset _uv_env_zsh_dir

if [[ -n "${_UV_ENV_ZSH_LOADED:-}" ]]; then
    # Re-sourcing is a safe reload: remove only hooks we own, then restore the
    # shell state captured before the previous integration was applied.
    autoload -Uz add-zsh-hook
    add-zsh-hook -d chpwd uv_env_refresh 2>/dev/null
    add-zsh-hook -d precmd uv_env_refresh 2>/dev/null
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
    _uv_env_resolve_profile
    case "$_UV_ENV_PROFILE_STATE" in
        outside)
            UV_ENV_PROMPT=""
            _uv_env_restore_file
            ;;
        none)
            UV_ENV_PROMPT="%F{yellow}[uv-env: <unset>]%f"
            _uv_env_restore_file
            ;;
        invalid)
            UV_ENV_PROMPT="%F{red}[uv-env: invalid]%f"
            _uv_env_restore_file
            ;;
        active)
            export UV_ENV_FILE="${_UV_ENV_PROFILE_PATH:A}"
            UV_ENV_PROMPT="%F{cyan}[uv-env: $_UV_ENV_PROFILE_NAME]%f"
            ;;
    esac
}

autoload -Uz add-zsh-hook
add-zsh-hook chpwd uv_env_refresh
add-zsh-hook precmd uv_env_refresh

setopt PROMPT_SUBST
PROMPT='${UV_ENV_PROMPT:+${UV_ENV_PROMPT} }'"${_UV_ENV_BASE_PROMPT}"

# Complete only the profile argument of `uv-env use`. This runs on Tab, not on
# every prompt, and deliberately mirrors the same .env/ then env/ lookup.
function _uv_env_complete_profiles() {
    local profiles="" profile
    local -a names

    _uv_env_find_profile_dir
    profiles="$_UV_ENV_PROFILE_DIR"
    [[ -n "$profiles" ]] || return 1

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
            (( CURRENT == 3 )) && compadd zsh bash
            ;;
    esac
}

# A plain Zsh installation has filename completion but no `compdef` until
# compinit runs. Bootstrap it only when the user's configuration has not
# already done so; established Zsh setups take this fast path.
if (( ! $+functions[compdef] )); then
    autoload -Uz compinit
    compinit
fi
compdef _uv-env uv-env
uv_env_refresh
