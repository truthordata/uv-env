# uv-env Bash integration. This file is sourced by `uv-env init bash`.

_uv_env_bash_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$_uv_env_bash_dir/../uv-env-common.sh"
unset _uv_env_bash_dir

[[ "${_UV_ENV_WRAP_MAKE:-}" == "1" ]] && _uv_env_wrap_make

if [[ -n "${_UV_ENV_BASH_LOADED:-}" ]]; then
    # Re-sourcing is a safe reload: restore only state owned by this hook before
    # installing a fresh prompt hook and completion registration.
    _uv_env_restore_file
    PS1="$_UV_ENV_BASE_PROMPT"
    if (( _UV_ENV_BASE_PROMPT_COMMAND_SET )); then
        if (( _UV_ENV_BASE_PROMPT_COMMAND_IS_ARRAY )); then
            PROMPT_COMMAND=("${_UV_ENV_BASE_PROMPT_COMMAND_ARRAY[@]}")
        else
            PROMPT_COMMAND="$_UV_ENV_BASE_PROMPT_COMMAND"
        fi
    else
        unset PROMPT_COMMAND
    fi
    complete -r uv-env 2>/dev/null || true
fi

_UV_ENV_BASH_LOADED=1
_UV_ENV_BASE_FILE_SET=0
_UV_ENV_BASE_FILE=""
[[ ${UV_ENV_FILE+x} ]] && {
    _UV_ENV_BASE_FILE_SET=1
    _UV_ENV_BASE_FILE="$UV_ENV_FILE"
}
_UV_ENV_BASE_PROMPT="$PS1"
UV_ENV_PROMPT=""

function _uv_env_restore_file() {
    if (( _UV_ENV_BASE_FILE_SET )); then
        export UV_ENV_FILE="$_UV_ENV_BASE_FILE"
    else
        unset UV_ENV_FILE
    fi
}

function uv_env_refresh() {
    _uv_env_resolve_stack
    case "$_UV_ENV_STACK_STATE" in
        outside)
            UV_ENV_PROMPT=""
            _uv_env_restore_file
            ;;
        none)
            UV_ENV_PROMPT='\[\e[33m\][uv-env: <unset>]\[\e[0m\]'
            _uv_env_restore_file
            ;;
        invalid)
            UV_ENV_PROMPT='\[\e[31m\][uv-env: invalid]\[\e[0m\]'
            _uv_env_restore_file
            ;;
        active)
            export UV_ENV_FILE="$_UV_ENV_STACK_PATHS"
            UV_ENV_PROMPT="\\[\\e[36m\\][uv-env: $_UV_ENV_STACK_NAME]\\[\\e[0m\\]"
            ;;
    esac
}

function _uv_env_complete_env_files() {
    local env_files="" env_file relative="" line="" alias="" current="${COMP_WORDS[COMP_CWORD]}"
    local dotglob_state
    COMPREPLY=()

    _uv_env_find_env_dir
    env_files="$_UV_ENV_ENV_DIR"
    [[ -n "$env_files" ]] || return

    dotglob_state="$(shopt -p dotglob)"
    shopt -s nullglob dotglob
    while IFS= read -r env_file; do
        [[ -f "$env_file" && ! -L "$env_file" ]] || continue
        relative="${env_file#"$env_files"/}"
        relative="${relative%.env}"
        [[ " ${COMP_WORDS[*]} " == *" $relative "* ]] && continue
        [[ "$relative" == "$current"* ]] && COMPREPLY+=("$relative")
    done < <(find -P "$env_files" -type f -name '*.env' ! -type l)
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ "$line" == alias\ * ]] || continue
        alias="${line#alias }"
        alias="${alias%% *}"
        [[ "@$alias" == "$current"* ]] && COMPREPLY+=("@$alias")
    done < "$env_files/.uv-env" 2>/dev/null
    eval "$dotglob_state"
}

function _uv_env_complete() {
    local current="${COMP_WORDS[COMP_CWORD]}"
    local commands="list status use select clear init uninit"

    COMPREPLY=()
    if (( COMP_CWORD == 1 )); then
        COMPREPLY=( $(compgen -W "$commands" -- "$current") )
        return
    fi

    case "${COMP_WORDS[1]:-}" in
        use)
            (( COMP_CWORD >= 2 )) && _uv_env_complete_env_files
            ;;
        init|uninit)
            (( COMP_CWORD == 2 )) && COMPREPLY=( $(compgen -W "zsh bash" -- "$current") )
            ;;
    esac
}

_UV_ENV_BASE_PROMPT_COMMAND_SET=0
_UV_ENV_BASE_PROMPT_COMMAND_IS_ARRAY=0
_UV_ENV_BASE_PROMPT_COMMAND=""
_UV_ENV_BASE_PROMPT_COMMAND_ARRAY=()
if [[ ${PROMPT_COMMAND+x} ]]; then
    _UV_ENV_BASE_PROMPT_COMMAND_SET=1
    if [[ "$(declare -p PROMPT_COMMAND 2>/dev/null)" == "declare -a "* ]]; then
        _UV_ENV_BASE_PROMPT_COMMAND_IS_ARRAY=1
        _UV_ENV_BASE_PROMPT_COMMAND_ARRAY=("${PROMPT_COMMAND[@]}")
        PROMPT_COMMAND=("${PROMPT_COMMAND[@]}" uv_env_refresh)
    else
        _UV_ENV_BASE_PROMPT_COMMAND="$PROMPT_COMMAND"
        PROMPT_COMMAND="${PROMPT_COMMAND:+$PROMPT_COMMAND;}uv_env_refresh"
    fi
else
    PROMPT_COMMAND=uv_env_refresh
fi

shopt -s promptvars
PS1='${UV_ENV_PROMPT:+${UV_ENV_PROMPT} }'"${_UV_ENV_BASE_PROMPT}"
complete -F _uv_env_complete uv-env
uv_env_refresh
