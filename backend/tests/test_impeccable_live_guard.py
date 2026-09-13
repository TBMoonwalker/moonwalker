"""Structural regression coverage for the impeccable-live guard scripts.

These scripts are committed logic under ``scripts/git`` (the real code lives in
the repo; ``.git/hooks`` only receives a thin wrapper). They have no shell test
harness, so this mirrors the repo's ``test_run_script.py`` approach: assert the
load-bearing control flow by reading the source rather than executing it.
"""

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
    assert script.index("1) echo", case_idx) > case_idx
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

    assert 'git -C "$REPO_ROOT" add --all -- "$TARGET_FILE"' in script
    assert 'git -C "$REPO_ROOT" show ":$TARGET_FILE"' in script
    assert "INJECT_RE=" in script
    assert "ARTIFACT_RE=" in script


def test_install_hooks_writes_idempotent_wrapper() -> None:
    script = INSTALL_HOOKS.read_text()

    assert 'WRAPPER="$HOOKS_DIR/pre-commit"' in script
    assert 'chmod +x "$WRAPPER"' in script
    assert "exec" in script
    assert "scripts/git/pre-commit" in script
