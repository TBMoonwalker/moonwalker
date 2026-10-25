#!/usr/bin/env bash
# Shared interpreter discovery for startup and fresh CI environments.

find_python_runtime() {
    local required_major required_minor required_series candidate brew_bin prefix
    local version_check='import sys; sys.exit(sys.version_info[:2] != tuple(map(int, sys.argv[1].split("."))))'

    IFS=. read -r required_major required_minor _ < "$1"
    if ! [[ "$required_major" =~ ^[0-9]+$ && "$required_minor" =~ ^[0-9]+$ ]]; then
        echo "Invalid Python version file: $1" >&2
        return 1
    fi
    required_series="${required_major}.${required_minor}"

    for candidate in "python${required_series}" python3; do
        candidate="$(command -v "$candidate" 2>/dev/null)" || continue
        if "$candidate" -c "$version_check" "$required_series" >/dev/null 2>&1; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    if [ "$(uname -s)" = "Darwin" ]; then
        # GUI shells may omit Homebrew from PATH on both Apple Silicon and Intel.
        for brew_bin in "$(command -v brew 2>/dev/null || true)" /opt/homebrew/bin/brew /usr/local/bin/brew; do
            [ -x "$brew_bin" ] || continue
            prefix="$(HOMEBREW_NO_AUTO_UPDATE=1 "$brew_bin" --prefix "python@${required_series}" 2>/dev/null)" || continue
            for candidate in "$prefix/bin/python${required_series}" "$prefix/libexec/bin/python3"; do
                [ -x "$candidate" ] || continue
                if "$candidate" -c "$version_check" "$required_series" >/dev/null 2>&1; then
                    printf '%s\n' "$candidate"
                    return 0
                fi
            done
        done
    fi

    echo "Python ${required_series} is required. See .python-version." >&2
    echo "On macOS with Homebrew: brew install python@${required_series}" >&2
    return 1
}
