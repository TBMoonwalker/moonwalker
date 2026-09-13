#!/usr/bin/env bash
#
# Guard the *tracked* Vite entrypoint (frontend/index.html) against the durable
# artifacts `impeccable live` can leave behind.
#
# Two artifact classes, two strategies:
#
#   1. INJECT  — the localhost helper <script> + its marker block. Always
#      unwanted in tracked source; strip it.
#            <!-- impeccable-live-start -->
#            <script src="http://localhost:8400/live.js?token=..."></script>
#            <!-- impeccable-live-end -->
#      (the block also carries data-impeccable-csp-* and the design-panel /
#       interaction / pick markers, so the block strip removes them too)
#
#   2. SESSION ARTIFACTS — variant/carbonize wrappers written into source during
#      or after a live session. These are intentional mid-session and must NOT
#      be silently mutated by a commit strip; they are cleaned by the documented
#      path (`impeccable live-server stop`, then remove leftover
#      impeccable-variants-*/impeccable-carbonize-* blocks). The guard therefore
#      FAILS CLOSED: it detects them, blocks the commit, and prints that command.
#
# frontend/dist/ is gitignored, so the only leak path this guards is a `git add`
# / commit of tracked source. The strip works in system temp files (with a trap)
# and writes back preserving inode/mode; pre-commit runs it as a subprocess.
#
# Usage:
#   scripts/git/strip-impeccable-live.sh [FILE ...]
#   MW_LIVE_STRIP_INDEX=... scripts/git/strip-impeccable-live.sh    # override target
#
# Exit codes:
#   0  clean
#   1  an INJECT marker was stripped (file modified)
#   2  usage / target-not-found / partial INJECT block (start without end, or
#      a start marker surviving the structured strip -> rewrite refused)
#   3  SESSION ARTIFACT residue present -> run `impeccable live-server stop`
#      and clean leftover wrapper blocks before committing
set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
DEFAULT_TARGET="${MW_LIVE_STRIP_INDEX:-$REPO_ROOT/frontend/index.html}"

# Always-unwanted INJECT markers / keywords.
INJECT_RE='impeccable-live|localhost:[0-9]+/live\.js|data-impeccable-csp|id="impeccable-live'

# Mid-session SESSION ARTIFACT markers: block the commit, do not auto-mutate.
ARTIFACT_RE='impeccable-variants-start|impeccable-variants-end|impeccable-carbonize-start|impeccable-carbonize-end|data-impeccable-variant=|data-impeccable-variants=|data-impeccable-css=|data-impeccable-carbonize|data-impeccable-params='

# Remove every whole line that carries an INJECT marker; a malformed/partial
# block is the safety net under the structured block strip below.
scrub_inject() {
     grep -v -E \
            -e 'impeccable-live' \
            -e 'localhost:[0-9]+/live\.js' \
            -e 'data-impeccable-csp' \
            -e 'id="impeccable-live' || true
}

strip_file() {
     local file="$1"
    if [ ! -f "$file" ]; then
         echo "strip-impeccable-live: target not found: $file" >&2
         return 2
      fi

       # System temp file only; trap ensures no residue leaks into the tree.
    local tmp
    tmp="$(mktemp -t mw-impeccable-live.XXXXXX)"
    trap "rm -f '$tmp'" EXIT INT TERM

       # Marker counts. A balanced pair, a standalone keyword, or an orphaned end
       # marker is handled by per-line removal below; a live-start with no matching
       # end is refused, since a partial injection would leave a dangling block.
    local stripped=0
    local has_start has_end
    has_start="$(grep -cE '<!-- *impeccable-live-start *-->' "$file" 2>/dev/null || true)"
    has_end="$(grep -cE '<!-- *impeccable-live-end *-->' "$file" 2>/dev/null || true)"
    if [ -n "$has_start" ] && [ "$has_start" -gt 0 ] && [ "$has_end" -lt "$has_start" ]; then
         echo "strip-impeccable-live: incomplete INJECT marker in $file: a live-start" >&2
         echo "  marker has no matching live-end. Repair or remove it by hand" >&2
         echo "  (run 'impeccable live-server stop', then clean the leftover), then commit." >&2
         return 2
    fi
       # Drop every line carrying an INJECT marker or keyword. Per-line removal is
       # truncation-proof: it deletes only marker-bearing lines, never the text
       # after a marker, so balanced, same-line, reversed, or orphaned markers are
       # all handled safely.
    if grep -qE "$INJECT_RE" "$file" 2>/dev/null; then
         scrub_inject < "$file" > "$tmp"
         cat "$tmp" > "$file"
         stripped=1
    fi
       # Final-state guard: a correct scrub leaves no INJECT marker. If any
       # survived, the rewrite misbehaved; fail closed instead of staging a
       # partial entrypoint.
    if grep -qE "$INJECT_RE" "$file" 2>/dev/null; then
         echo "strip-impeccable-live: unrepaired INJECT residue in $file" >&2
         echo "   an INJECT marker survived the scrub. Run 'impeccable live-server stop'," >&2
         echo "   then repair/remove the leftover by hand, then commit." >&2
         return 2
    fi

      # Fail closed on residual SESSION ARTIFACTS (do not auto-mutate them).
    if grep -nE "$ARTIFACT_RE" "$file" >/dev/null 2>&1; then
         echo "strip-impeccable-live: SESSION ARTIFACT residue in $file (live-mode wrapper left in source):" >&2
         grep -nE "$ARTIFACT_RE" "$file" | head >&2 || true
         echo "  -> run 'impeccable live-server stop', remove any remaining" >&2
         echo "     impeccable-variants-*/impeccable-carbonize-* blocks, then commit." >&2
         return 3
      fi

     [ "$stripped" -eq 1 ] && return 1
     return 0
}

# No args: guard the default tracked entrypoint.
if [ "$#" -eq 0 ]; then
     strip_file "$DEFAULT_TARGET"
     exit
fi

rc=0
for f in "$@"; do
     strip_file "$f" || rc=$?
     # 3 (artifact residue) short-circuits; do not keep "stripping".
     if [ "$rc" -eq 3 ]; then
         break
     fi
done
exit "$rc"
