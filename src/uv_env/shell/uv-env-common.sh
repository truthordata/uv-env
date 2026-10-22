# Shared Bash/Zsh project and profile resolution for uv-env.
# Shell-specific hooks source this file; it intentionally uses only syntax both
# shells support and leaves prompt rendering to the caller.

function _uv_env_find_profile_dir() {
    local directory="$PWD" root=""
    _UV_ENV_PROFILE_DIR=""
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
        _UV_ENV_PROFILE_DIR="$root/.env"
    elif [[ -d "$root/env" ]]; then
        _UV_ENV_PROFILE_DIR="$root/env"
    fi
}

function _uv_env_resolve_profile() {
    local selection="" profile="" profile_path=""
    _UV_ENV_PROFILE_STATE="outside"
    _UV_ENV_PROFILE_NAME=""
    _UV_ENV_PROFILE_PATH=""

    _uv_env_find_profile_dir
    if [[ -z "$_UV_ENV_PROFILE_DIR" ]]; then
        # A project with no profile directory is distinct from being outside a
        # project: show that no profile is selected in the former case.
        [[ -n "$_UV_ENV_PROJECT_ROOT" ]] && _UV_ENV_PROFILE_STATE="none"
        return
    fi

    selection="$_UV_ENV_PROFILE_DIR/.uv-env"
    if [[ ! -f "$selection" ]]; then
        _UV_ENV_PROFILE_STATE="none"
        return
    fi

    IFS= read -r profile < "$selection" || true
    if [[ -z "$profile" || "$profile" != *.env || "$profile" == */* ||
          "$profile" == "." || "$profile" == ".." || "$profile" == *$'\r'* ]]; then
        _UV_ENV_PROFILE_STATE="invalid"
        return
    fi

    profile_path="$_UV_ENV_PROFILE_DIR/$profile"
    if [[ ! -f "$profile_path" || -L "$profile_path" ]]; then
        _UV_ENV_PROFILE_STATE="invalid"
        return
    fi

    _UV_ENV_PROFILE_STATE="active"
    _UV_ENV_PROFILE_NAME="${profile%.env}"
    _UV_ENV_PROFILE_PATH="$profile_path"
}
