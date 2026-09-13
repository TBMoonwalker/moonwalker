#!/usr/bin/env bash
#
# Install the committed git hooks (.git/hooks are not tracked by git, so this
# makes scripts/git/pre-commit take effect after a clone or checkout).
#
# The wrapper is idempotent and version-stamped so re-runs are cheap. It points
# at the committed logic so the real code lives in the repo, not in .git/.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"

# Resolve Git's *effective* hooks directory.
# core.hooksPath (if set) IS a hooks dir and wins; otherwise the default is
# <common-dir>/hooks. --git-common-dir is the git dir (needs a /hooks suffix),
# and it is correct even in a linked worktree, where .git is a file and Git runs
# hooks from the shared .git/hooks, NOT the per-worktree .git/worktrees/<n>/hooks.
core_hooks_path="$(git -C "$REPO_ROOT" config --get core.hooksPath || true)"
if [ -n "$core_hooks_path" ]; then
     HOOKS_PATH="$core_hooks_path"
     if [[ "$HOOKS_PATH" != /* ]]; then
         HOOKS_PATH="$REPO_ROOT/$core_hooks_path"
     fi
else
    common_dir="$(git -C "$REPO_ROOT" rev-parse --git-common-dir)"
    if [[ "$common_dir" != /* ]]; then
         common_dir="$REPO_ROOT/$common_dir"
    fi
    HOOKS_PATH="$common_dir/hooks"
fi

WRAPPER="$HOOKS_PATH/pre-commit"

mkdir -p "$HOOKS_PATH"

cat > "$WRAPPER" <<EOF
#!/usr/bin/env bash
# Installed by scripts/git/install-hooks.sh — do not edit; the real logic is
# in scripts/git/pre-commit.
exec "$REPO_ROOT/scripts/git/pre-commit" "\$@"
EOF

chmod +x "$WRAPPER"
chmod +x "$REPO_ROOT/scripts/git/pre-commit" "$REPO_ROOT/scripts/git/strip-impeccable-live.sh"

echo "Installed: $WRAPPER"
echo "   -> $REPO_ROOT/scripts/git/pre-commit"
