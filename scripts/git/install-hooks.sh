#!/usr/bin/env bash
#
# Install the committed git hooks (.git/hooks are not tracked by git, so this
# makes scripts/git/pre-commit take effect after a clone or checkout).
#
# The wrapper is idempotent and version-stamped so re-runs are cheap. It points
# at the committed logic so the real code lives in the repo, not in .git/.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOKS_DIR="$REPO_ROOT/.git/hooks"
WRAPPER="$HOOKS_DIR/pre-commit"

mkdir -p "$HOOKS_DIR"

cat > "$WRAPPER" <<EOF
#!/usr/bin/env bash
# Installed by scripts/git/install-hooks.sh — do not edit; the real logic is
# in scripts/git/pre-commit.
exec "$REPO_ROOT/scripts/git/pre-commit" "\$@"
EOF

chmod +x "$WRAPPER"
chmod +x "$REPO_ROOT/scripts/git/pre-commit" "$REPO_ROOT/scripts/git/strip-impeccable-live.sh"

echo "Installed: $WRAPPER"
echo "  -> $REPO_ROOT/scripts/git/pre-commit"
