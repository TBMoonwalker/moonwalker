"""Structural and runtime regression coverage for the impeccable-live guard scripts.

The guard scripts are committed logic under ``scripts/git`` (the real code lives
in the repo; ``.git/hooks`` only receives a thin wrapper). Most tests assert the
load-bearing control flow by reading the source (the repo's ``test_run_script.py``
approach); one test executes the strip to prove the partial-injection fail-closed
property.
"""

import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
RUN_SCRIPT = ROOT_DIR / "run.sh"
PRE_COMMIT = ROOT_DIR / "scripts/git/pre-commit"
STRIP_SCRIPT = ROOT_DIR / "scripts/git/strip-impeccable-live.sh"
INSTALL_HOOKS = ROOT_DIR / "scripts/git/install-hooks.sh"


def test_run_sh_fails_fast_when_spa_assets_not_staged() -> None:
    script = RUN_SCRIPT.read_text()

    stage_assets = "cp frontend/dist/index.html backend/templates/"
    guard = "if [ ! -f backend/templates/index.html ] || [ ! -d backend/static/assets ]"
    hard_exit = "exit 1"

    assert guard in script
    guard_idx = script.index(guard)
    assert script.index(stage_assets) < guard_idx
    assert script.index(hard_exit, guard_idx) > guard_idx
    assert "The backend will return 500" in script


def test_strip_script_defines_fail_closed_artifact_residue() -> None:
    script = STRIP_SCRIPT.read_text()

    assert "ARTIFACT_RE=" in script
    assert "SESSION ARTIFACT residue" in script
    assert "return 3" in script


def test_strip_script_defines_all_documented_return_codes() -> None:
    script = STRIP_SCRIPT.read_text()

    for code in ("return 0", "return 1", "return 2", "return 3", 'exit "$rc"'):
        assert code in script


def test_strip_script_scrubs_inject_and_short_circuits_on_residue() -> None:
    script = STRIP_SCRIPT.read_text()

    assert "scrub_inject" in script
    assert "INJECT_RE=" in script
    fan = script.index('for f in "$@"')
    assert script.index('if [ "$rc" -eq 3 ]', fan) > fan


def test_pre_commit_maps_strip_return_codes_to_actions() -> None:
    script = PRE_COMMIT.read_text()

    strip_call = '"$STRIP" "$TARGET_FILE"'
    assert strip_call in script
    assert "set +e" in script

    case_idx = script.index('case "$strip_rc" in')
    assert script.index("BLOCKED", case_idx) > case_idx
    assert "BLOCKED" in script
    assert 'exit "$strip_rc"' in script


def test_pre_commit_keeps_inject_gate_a_superset_of_strip() -> None:
    pre_commit = PRE_COMMIT.read_text()
    strip = STRIP_SCRIPT.read_text()

    pre_marker = pre_commit.split("INJECT_RE='", 1)[1].split("'", 1)[0]
    strip_marker = strip.split("INJECT_RE='", 1)[1].split("'", 1)[0]
    for alternative in strip_marker.split("|"):
        assert alternative in pre_marker


def test_pre_commit_gates_the_staged_blob() -> None:
    script = PRE_COMMIT.read_text()

    # A whole-tree --all re-stage is never used: it would pull unrelated,
    # deliberately-unstaged edits into the commit (partial staging).
    assert 'git -C "$REPO_ROOT" add -- "$TARGET_FILE"' in script
    assert "add --all --" not in script
    assert 'git -C "$REPO_ROOT" show ":$TARGET_FILE"' in script
    assert "INJECT_RE=" in script
    assert "ARTIFACT_RE=" in script


def test_pre_commit_only_re_stages_when_the_strip_modified_the_file() -> None:
    # Re-staging is scoped to the 1) arm (INJECT stripped), so a clean run (0)
    # leaves the index untouched and cannot hijack a partial-staging commit.
    script = PRE_COMMIT.read_text()

    case_idx = script.index('case "$strip_rc" in')
    arm1 = script.index("1)", case_idx)
    arm2 = script.index("3)", arm1)
    re_stage = script.index('add -- "$TARGET_FILE"', arm1)
    assert arm1 < re_stage < arm2


def test_strip_script_fails_closed_on_unbalanced_inject_markers() -> None:
    script = STRIP_SCRIPT.read_text()

    # A live-start without a matching live-end must never let the awk block stay
    # open and truncate the rest of the entrypoint.
    assert "has_start=" in script
    assert "has_end=" in script
    assert 'has_start" -gt 0 ' in script
    assert 'has_end" -lt ' in script
    # Fail closed: refuse to rewrite a partial block (return 2).
    assert "incomplete INJECT marker" in script
    assert "return 2" in script


def test_install_hooks_resolves_the_git_dir_for_worktrees() -> None:
    script = INSTALL_HOOKS.read_text()

    # In a linked worktree .git is a file, not a directory, so the hooks dir must
    # be resolved through git rather than built by hand.
    assert "--absolute-git-dir" in script
    assert 'HOOKS_DIR="$REPO_ROOT/.git/hooks"' not in script


def test_install_hooks_writes_idempotent_wrapper() -> None:
    script = INSTALL_HOOKS.read_text()

    assert 'WRAPPER="$HOOKS_DIR/pre-commit"' in script
    assert 'chmod +x "$WRAPPER"' in script
    assert "exec" in script
    assert "scripts/git/pre-commit" in script


def test_strip_script_refuses_partial_injection_at_runtime(tmp_path) -> None:
    # The single most safety-critical property: a live-start with no matching
    # live-end must NOT let the awk block stay open and truncate the Vue mount.
    target = tmp_path / "index.html"
    target.write_text(
        "<html>\n"
        "<!-- impeccable-live-start -->\n"
        '<script src="http://localhost:8400/live.js"></script>\n'
        '<div id="app"></div>\n'
        '<script type="module" src="/src/main.ts"></script>\n'
        "</html>\n",
    )

    result = subprocess.run(
        ["bash", str(STRIP_SCRIPT), str(target)],
        text=True,
        capture_output=True,
    )

    # Fail closed (rc 2) and the entrypoint is NOT truncated.
    assert result.returncode == 2
    content = target.read_text()
    assert 'id="app"' in content
    assert "/src/main.ts" in content
