#!/usr/bin/env bash
#
# Strip the `impeccable live` debug instrumentation out of the *tracked*
# Vite entrypoint (frontend/index.html).
#
# Why this exists:
#    `impeccable live` mutates a tracked source file by injecting markers like
#        <!-- impeccable-live-start -->
#        <script src="http://localhost:..."?token=...></script>
#        <!-- impeccable-live-end -->
#    If that file is ever committed, a live-only localhost script (and its
#    token) would be baked into the production build. `frontend/dist/` is
#    already ignored, so this guard covers the one path that can leak: a
#    `git add` / commit of the source file.
#
# The stripper is intentionally marker-based AND keyword-based so it catches
# current and future live-tool variants, not just the exact block seen today.
#
# Usage:
#   scripts/git/strip-impeccable-live.sh [FILE ...]    # strip the given files
#   FRONTEND_INDEX=... scripts/git/strip-impeccable-live.sh   # override target
#
# Exit codes:
#   0  nothing was stripped (file was already clean)
#   1  at least one file was modified
#   2  usage / target-not-found error
set -uo pipefail

# Standalone CLI (do not source it). Invoked as a subprocess by
# scripts/git/pre-commit so it cannot collide on caller variables or `$0`.
REPO_ROOT="$(git rev-parse --show-toplevel)"
DEFAULT_TARGET="${FRONTEND_INDEX:-$REPO_ROOT/frontend/index.html}"

# Keyword scrub: drop any line that still references a live debug endpoint even
# if the marker pair is malformed or half-present. Best-effort safety net; the
# block strip is the primary path.
read_keyword_scrub() {
    grep -v -E \
         -e 'impeccable-live' \
         -e 'localhost:[0-9]+/live\.js' \
         -e 'id="impeccable-live' \
         -e 'data-impeccable-live' || true
}

strip_file() {
    local file="$1"
    if [ ! -f "$file" ]; then
        echo "strip-impeccable-live: target not found: $file" >&2
        return 2
    fi

      # Work in system temp files (never in the source dir) and clean them up
      # on any return path so no .live-strip.* residue can pollute the tree.
    local tmp tmp_kw
    tmp="$(mktemp -t mw-impeccable-live.XXXXXX)"
    tmp_kw="$(mktemp -t mw-impeccable-live.XXXXXX)"
    trap "rm -f '$tmp' '$tmp_kw'" EXIT INT TERM

      # Primary: remove the full marker block (start..end inclusive).
    if grep -qE '<!-- *impeccable-live-start *-->' "$file"; then
        awk '
          /^<!-- *impeccable-live-start *-->/ { in_block = 1; next }
          in_block {
              if ($0 ~ /<!-- *impeccable-live-end *-->/) { in_block = 0 }
              next
          }
          { print }
          ' "$file" > "$tmp"

          # Safety net: scrub any surviving live-debug keyword lines the block
          # pattern did not catch (malformed markers, partial injections).
    if grep -qE 'impeccable-live|localhost:[0-9]+/live\.js' "$tmp" 2>/dev/null; then
        read_keyword_scrub < "$tmp" > "$tmp_kw"
        cat "$tmp_kw" > "$tmp"
    fi

            # Write back with `cat > file` (keeps inode/mode) rather than mv.
        if ! diff -q "$file" "$tmp" >/dev/null 2>&1; then
            cat "$tmp" > "$file"
            return 1
        fi
        return 0
    fi

      # No marker pair, but a stray live keyword may still be present.
    if grep -qE 'impeccable-live|localhost:[0-9]+/live\.js' "$file" 2>/dev/null; then
        read_keyword_scrub < "$file" > "$tmp"
        if ! diff -q "$file" "$tmp" >/dev/null 2>&1; then
            cat "$tmp" > "$file"
            return 1
        fi
    fi
    return 0
}

# No args: strip the default tracked entrypoint.
if [ "$#" -eq 0 ]; then
    strip_file "$DEFAULT_TARGET"
    exit
fi

rc=0
for f in "$@"; do
    strip_file "$f" || rc=$?
done
exit "$rc"
