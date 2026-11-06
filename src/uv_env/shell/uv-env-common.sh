# Shared Bash/Zsh project and env-stack resolution for uv-env.
# Shell-specific hooks source this file; it intentionally uses only syntax both
# shells support and leaves prompt rendering to the caller.

function _uv_env_find_env_dir() {
    local directory="$PWD" root=""
    _UV_ENV_ENV_DIR=""
    _UV_ENV_PROJECT_ROOT=""

    while :; do
        if [[ -f "$directory/pyproject.toml" ]]; then
            root="$directory"
            break
        fi
        [[ "$directory" == "/" ]] && return
        directory="${directory%/*}"
        [[ -n "$directory" ]] || directory="/"
    done

    _UV_ENV_PROJECT_ROOT="$root"

    if [[ -d "$root/.env" ]]; then
        _UV_ENV_ENV_DIR="$root/.env"
    elif [[ -d "$root/env" ]]; then
        _UV_ENV_ENV_DIR="$root/env"
    fi
}

function _uv_env_resolve_stack() {
    local selection_file="" selection="" line="" alias_name="" alias_files=""
    local env_file="" env_file_path="" resolved_dir="" env_root="" stack_paths="" stack_name=""
    _UV_ENV_STACK_STATE="outside"
    _UV_ENV_STACK_NAME=""
    _UV_ENV_STACK_PATHS=""

    _uv_env_find_env_dir
    if [[ -z "$_UV_ENV_ENV_DIR" ]]; then
        # A project with no env-file directory is distinct from being outside a
        # project: show that no env file is selected in the former case.
        [[ -n "$_UV_ENV_PROJECT_ROOT" ]] && _UV_ENV_STACK_STATE="none"
        return
    fi
    if [[ -n "${ZSH_VERSION:-}" ]]; then
        env_root="${_UV_ENV_ENV_DIR:A}"
    else
        env_root="$(cd -P -- "$_UV_ENV_ENV_DIR" && pwd)" || return
    fi

    selection_file="$_UV_ENV_ENV_DIR/.uv-env"
    if [[ ! -f "$selection_file" ]]; then
        _UV_ENV_STACK_STATE="none"
        return
    fi

    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ -z "$line" || "$line" == \#* ]] && continue
        if [[ "$line" == use\ * ]]; then
            [[ -n "$selection" ]] && { _UV_ENV_STACK_STATE="invalid"; return; }
            selection="${line#use }"
        elif [[ -z "$selection" ]]; then
            # The original single-line selection format remains valid.
            selection="$line"
        fi
    done < "$selection_file"

    [[ -n "$selection" ]] || { _UV_ENV_STACK_STATE="none"; return; }
    if [[ "$selection" == @* ]]; then
        [[ "$selection" != *" "* ]] || { _UV_ENV_STACK_STATE="invalid"; return; }
        alias_name="${selection#@}"
        while IFS= read -r line || [[ -n "$line" ]]; do
            [[ "$line" == "alias $alias_name "* ]] || continue
            [[ -n "$alias_files" ]] && { _UV_ENV_STACK_STATE="invalid"; return; }
            alias_files="${line#"alias $alias_name "}"
        done < "$selection_file"
        [[ -n "$alias_files" ]] || { _UV_ENV_STACK_STATE="invalid"; return; }
        selection="$alias_files"
        stack_name="@$alias_name"
    fi

    while IFS= read -r env_file; do
        if [[ "$env_file" != *.env || "$env_file" == /* || "$env_file" == ../* ||
              "$env_file" == */../* || "$env_file" == */.. || "$env_file" == "." ||
              "$env_file" == ".." || "$env_file" == *$'\r'* ]]; then
            _UV_ENV_STACK_STATE="invalid"
            return
        fi
        env_file_path="$_UV_ENV_ENV_DIR/$env_file"
        if [[ ! -f "$env_file_path" || -L "$env_file_path" ]]; then
            _UV_ENV_STACK_STATE="invalid"
            return
        fi
        if [[ -n "${ZSH_VERSION:-}" ]]; then
            resolved_dir="${env_file_path:h:A}"
        else
            resolved_dir="$(cd -P -- "$(dirname -- "$env_file_path")" && pwd)" || return
        fi
        if [[ "$resolved_dir" != "$env_root" && "$resolved_dir" != "$env_root/"* ]]; then
            _UV_ENV_STACK_STATE="invalid"
            return
        fi
        env_file_path="$resolved_dir/${env_file_path##*/}"
        stack_paths="${stack_paths:+$stack_paths }$env_file_path"
    done < <(printf '%s\n' "$selection" | tr ' ' '\n')
    [[ -n "$stack_paths" ]] || {
        _UV_ENV_STACK_STATE="invalid"
        return
    }

    if [[ "$selection_file" && "$alias_name" == "" ]]; then
        stack_name=""
        while IFS= read -r env_file; do
            stack_name="${stack_name:+$stack_name+}${env_file%.env}"
        done < <(printf '%s\n' "$selection" | tr ' ' '\n')
    fi

    _UV_ENV_STACK_STATE="active"
    _UV_ENV_STACK_NAME="$stack_name"
    _UV_ENV_STACK_PATHS="$stack_paths"
}

# Define this only when requested by `uv-env init --wrap-make`.  Resolve the
# stack for every invocation so `make` also works correctly immediately
# after a directory change, before the next prompt hook runs.
function _uv_env_wrap_make() {
    function make() {
        _uv_env_resolve_stack
        if [[ "$_UV_ENV_STACK_STATE" == "active" ]]; then
            command env UV_ENV_FILE="$_UV_ENV_STACK_PATHS" uv run make "$@"
        else
            command make "$@"
        fi
    }
}
