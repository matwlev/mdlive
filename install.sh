#!/usr/bin/env bash
# Install from this checkout without modifying the system Python.
set -euo pipefail

usage() {
    cat <<'HELP'
Usage: ./install.sh [--no-modify-path]

Install mdlive in ~/.local/share/mdlive/venv and link ~/.local/bin/mdlive.
Add ~/.local/bin to the appropriate shell startup file unless disabled.
No sudo required. Run again to install updated code from this checkout.

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

source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python="${MDLIVE_PYTHON:-}"
if [[ -z "$python" ]]; then
    for candidate in python3.14 python3.13 python3.12 python3.11 python3 "$source_dir/.venv/bin/python"; do
        if command -v "$candidate" >/dev/null 2>&1 &&
           "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' 2>/dev/null; then
            python="$candidate"
            break
        fi
    done
fi
if [[ -z "$python" ]] || ! "$python" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
    echo 'Python 3.11+ is required. Set MDLIVE_PYTHON to a suitable interpreter.' >&2
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
    "$python" -m venv "$venv"
fi
"$venv/bin/python" -m pip install --upgrade "$source_dir"
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
