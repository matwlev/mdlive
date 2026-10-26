#!/usr/bin/env bash
# Install from a checkout or GitHub without modifying the system Python.
set -euo pipefail

usage() {
    cat <<'HELP'
Usage: bash install.sh [--no-modify-path]
       curl -fsSL https://raw.githubusercontent.com/matwlev/mdlive/main/install.sh | bash

Install mdlive in ~/.local/share/mdlive/venv and link ~/.local/bin/mdlive.
Add ~/.local/bin to the appropriate shell startup file unless disabled.
Requires Python 3.11+ with venv support. No sudo or Git required.
Run again to update. A checkout installs local code; a downloaded or piped
script installs the main branch from GitHub.

Environment overrides:
  MDLIVE_PYTHON       Python 3.11+ executable
  MDLIVE_INSTALL_DIR  Installation directory (default: ~/.local/share/mdlive)
  MDLIVE_BIN_DIR      Command directory (default: ~/.local/bin)
  MDLIVE_PROFILE      Shell startup file to update instead of the default
HELP
}

modify_path=true
case "${1:-}" in
    -h|--help) usage; exit 0 ;;
    --no-modify-path) modify_path=false ;;
    '') ;;
    *) usage >&2; exit 2 ;;
esac
if (( $# > 1 )); then usage >&2; exit 2; fi

# BASH_SOURCE is empty when run as `curl ... | bash`.
source_dir=""
script_path="${BASH_SOURCE[0]:-}"
if [[ -n "$script_path" && -f "$script_path" ]]; then
    script_dir="$(cd -- "$(dirname -- "$script_path")" && pwd)"
    if [[ -f "$script_dir/pyproject.toml" && -d "$script_dir/src/mdlive" ]]; then
        source_dir="$script_dir"
    fi
fi
install_source="${source_dir:-https://github.com/matwlev/mdlive/archive/refs/heads/main.tar.gz}"
python="${MDLIVE_PYTHON:-}"
if [[ -z "$python" ]]; then
    candidates=(python3.14 python3.13 python3.12 python3.11 python3 python)
    if [[ -n "$source_dir" ]]; then candidates+=("$source_dir/.venv/bin/python"); fi
    for candidate in "${candidates[@]}"; do
        if command -v "$candidate" >/dev/null 2>&1 &&
           "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' 2>/dev/null; then
            python="$candidate"
            break
        fi
    done
fi
if [[ -z "$python" ]] || ! "$python" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' </dev/null 2>/dev/null; then
    echo 'Python 3.11+ was not found. Install Python 3.11 or newer, then run this installer again. You can also set MDLIVE_PYTHON to a suitable interpreter.' >&2
    exit 1
fi

install_dir="${MDLIVE_INSTALL_DIR:-$HOME/.local/share/mdlive}"
bin_dir="${MDLIVE_BIN_DIR:-$HOME/.local/bin}"
mkdir -p -- "$install_dir" "$bin_dir"
install_dir="$(cd -- "$install_dir" && pwd)"
bin_dir="$(cd -- "$bin_dir" && pwd)"
venv="$install_dir/venv"
command_path="$bin_dir/mdlive"
if [[ -e "$command_path" || -L "$command_path" ]]; then
    if [[ ! -L "$command_path" || "$(readlink "$command_path")" != "$venv/bin/mdlive" ]]; then
        echo "Refusing to replace an existing command: $command_path" >&2
        exit 1
    fi
fi

if [[ ! -x "$venv/bin/python" ]]; then
    if ! "$python" -m venv "$venv" </dev/null; then
        echo 'Could not create a Python virtual environment. Install venv support for your Python (python3-venv on Debian/Ubuntu), then try again.' >&2
        exit 1
    fi
fi
echo "Installing mdlive from $install_source"
if ! "$venv/bin/python" -m pip install --upgrade "$install_source" </dev/null; then
    echo 'Installation failed. Check your internet connection and the error above, then run the installer again.' >&2
    exit 1
fi
if [[ ! -L "$command_path" ]]; then
    ln -s -- "$venv/bin/mdlive" "$command_path"
fi
"$command_path" --version

if "$modify_path"; then
    # bash's escaping is also valid in zsh; no untrusted path is evaluated.
    printf -v path_line 'export PATH=%q:"$PATH"' "$bin_dir"
    profiles=()
    if [[ -n "${MDLIVE_PROFILE:-}" ]]; then
        profiles=("$MDLIVE_PROFILE")
    else
        case "${SHELL:-/bin/sh}" in
            */zsh) profiles=("${ZDOTDIR:-$HOME}/.zshrc") ;;
            */bash) profiles=("$HOME/.bashrc" "$HOME/.bash_profile") ;;
            */sh|*/dash|*/ksh) profiles=("$HOME/.profile") ;;
            *) echo "Shell not recognized. Add this to your shell configuration: $path_line" ;;
        esac
    fi
    for profile in "${profiles[@]}"; do
        mkdir -p -- "$(dirname -- "$profile")"
        if [[ ! -f "$profile" ]] || ! grep -Fqx -- "$path_line" "$profile"; then
            printf '\n# mdlive command\n%s\n' "$path_line" >> "$profile"
            echo "Updated $profile"
        fi
    done
fi
printf '\nInstalled: %s\n' "$command_path"
if [[ ":$PATH:" != *":$bin_dir:"* ]]; then
    printf 'Open a new terminal, or run now:\n'
    printf '  export PATH=%q:"$PATH"\n' "$bin_dir"
fi
