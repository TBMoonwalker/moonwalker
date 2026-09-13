#!/usr/bin/env bash
#
# Install the committed git pre-commit hook so the impeccable-live guard runs
# after a clone or checkout. .git/hooks is not tracked by git, so the real logic
# lives in scripts/git/pre-commit and this only (re)creates a thin, idempotent,
# version-stamped wrapper.
#
# Safety:
#   * The user's existing pre-commit hook is never destroyed. A pre-existing hook
#     that is not ours is backed up to pre-commit.user and chained, so existing
#     checks keep running.
#   * The wrapper resolves the committed script from the *active* worktree at run
#     time (git rev-parse --show-toplevel), so it is correct for every worktree
#     and survives removal of the worktree in which it was installed.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"

# Resolve Git's *effective* hooks directory. core.hooksPath (if set) is a hooks
# dir and wins; otherwise the default is <common-dir>/hooks. --git-common-dir is
# the shared git dir (needs a /hooks suffix); it is correct even in a linked
# worktree, where Git runs hooks from the shared .git/hooks, not a per-worktree
# one.
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
USER_HOOK="$HOOKS_PATH/pre-commit.user"
MARKER="# Installed by scripts/git/install-hooks.sh"

mkdir -p "$HOOKS_PATH"

# Preserve, then chain, a pre-existing hook that is not ours. Copy it aside once
# (so a re-run does not clobber the original) so the user's existing checks stay
# intact; our wrapper runs after it.
if [ -f "$WRAPPER" ] && ! grep -qF "$MARKER" "$WRAPPER"; then
     [ -e "$USER_HOOK" ] || cp -p "$WRAPPER" "$USER_HOOK"
     chmod +x "$USER_HOOK"
fi

cat > "$WRAPPER" <<EOF
#!/usr/bin/env bash
$MARKER - do not edit; the real logic lives in scripts/git/pre-commit.
# Run a preserved user hook first, then the Moonwalker guard. Both resolve from
# the active worktree so the hook is correct for every worktree and survives the
# removal of the one it was installed in.
dir="\$(git rev-parse --show-toplevel 2>/dev/null || true)"
[ -n "\$dir" ] || exit 0
user="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)/pre-commit.user"
if [ -f "\$user" ]; then
      if ! "\$user" "\$@"; then
           exit 1
      fi
fi
guard="\$dir/scripts/git/pre-commit"
[ -x "\$guard" ] || exit 0
exec "\$guard" "\$@"
EOF

chmod +x "$WRAPPER"
chmod +x "$REPO_ROOT/scripts/git/pre-commit" "$REPO_ROOT/scripts/git/strip-impeccable-live.sh"

echo "Installed: $WRAPPER"
echo "    -> \$dir/scripts/git/pre-commit (resolved per worktree at run time)"
if [ -f "$USER_HOOK" ]; then
     echo "    chained existing hook preserved: $USER_HOOK"
fi
