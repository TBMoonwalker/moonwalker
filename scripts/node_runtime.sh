#!/usr/bin/env bash
# Shared Node/npm discovery; selected Homebrew paths affect only this process.

print_node_runtime_help() {
    echo "Moonwalker uses the Node.js version pinned in .nvmrc."
    echo
    echo "macOS or Linux with nvm (recommended):"
    echo "  Install nvm: https://github.com/nvm-sh/nvm#installing-and-updating"
    echo "  nvm install"
    echo "  nvm use"
    echo "  ./run.sh start"
    echo
    echo "macOS with Homebrew:"
    echo "  brew install node@24"
    # Print the command literally for the user to run in their own shell.
    # shellcheck disable=SC2016
    echo '  export PATH="$(brew --prefix node@24)/bin:$PATH"'
    echo "  ./run.sh start"
}

frontend_runtime_matches() {
    local node_version npm_version node_minor

    command -v node >/dev/null 2>&1 || return 1
    command -v npm >/dev/null 2>&1 || return 1
    node_version="$(node -p 'process.versions.node' 2>/dev/null)" || return 1
    npm_version="$(npm --version 2>/dev/null)" || return 1
    [[ "$node_version" =~ ^24\.([0-9]+)\.[0-9]+$ ]] || return 1
    node_minor="${BASH_REMATCH[1]}"
    [[ "$npm_version" =~ ^11\.[0-9]+\.[0-9]+$ ]] || return 1
    [ "$node_minor" -ge 11 ]
}

check_frontend_runtime() {
    local brew_bin prefix

    if frontend_runtime_matches; then
        return 0
    fi
    if [ "$(uname -s)" = "Darwin" ]; then
        for brew_bin in "$(command -v brew 2>/dev/null || true)" /opt/homebrew/bin/brew /usr/local/bin/brew; do
            [ -x "$brew_bin" ] || continue
            prefix="$(HOMEBREW_NO_AUTO_UPDATE=1 "$brew_bin" --prefix node@24 2>/dev/null)" || continue
            [ -x "$prefix/bin/node" ] && [ -x "$prefix/bin/npm" ] || continue
            if PATH="$prefix/bin:$PATH" frontend_runtime_matches; then
                # npm and its child processes must resolve this same Node runtime.
                export PATH="$prefix/bin:$PATH"
                hash -r
                return 0
            fi
        done
    fi
    echo "Required: Node.js >=24.11.0 <25 and npm >=11 <12." >&2
    print_node_runtime_help >&2
    return 1
}
