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

    strip_call = '"$STRIP" "$tmp"'
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

    # The cleaned staged blob is written back through the index
    # (--cacheinfo), never by re-staging a whole tree, so unrelated
    # unstaged edits are not swept into the commit.
    assert "update-index --cacheinfo" in script
    assert "hash-object -w --stdin" in script
    assert "add --all --" not in script
    assert 'git -C "$REPO_ROOT" add --' not in script
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
    re_stage = script.index("update-index --cacheinfo", arm1)
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

    # In a linked worktree .git is a file, not a directory, so the
    # hooks dir must be resolved through git (common-dir / hooksPath)
    # rather than built by hand.
    assert "--git-common-dir" in script
    assert "core.hooksPath" in script
    assert "--absolute-git-dir" not in script
    assert 'HOOKS_DIR="$REPO_ROOT/.git/hooks"' not in script


def test_install_hooks_writes_idempotent_wrapper() -> None:
    script = INSTALL_HOOKS.read_text()

    assert 'WRAPPER="$HOOKS_PATH/pre-commit"' in script
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


def test_strip_script_strips_same_line_inject_block_without_truncating(
    tmp_path,
) -> None:
    # Regression for the P1: when a start and end marker sit on the SAME line,
    # the structured strip must drop the whole block (rc 1) without truncating
    # the rest of the entrypoint (a block-open awk would discard the Vue mount
    # and app script to EOF).
    target = tmp_path / "index.html"
    target.write_text(
        "<html>\n"
        '<!-- impeccable-live-start --><script src="http://localhost:8400/live.js"></'
        "script><!-- impeccable-live-end -->\n"
        '<div id="app"></div>\n'
        '<script type="module" src="/src/main.ts"></script>\n'
        "</html>\n",
    )

    result = subprocess.run(
        ["bash", str(STRIP_SCRIPT), str(target)],
        text=True,
        capture_output=True,
    )

    # Block was stripped (rc 1) and NOTHING after it was truncated.
    assert result.returncode == 1
    content = target.read_text()
    assert "impeccable-live" not in content
    assert "localhost:" not in content
    assert 'id="app"' in content
    assert "/src/main.ts" in content


def test_install_hooks_preserves_and_chains_a_user_hook() -> None:
    # Regression for the P2: installing must not silently destroy a pre-existing,
    # non-Moonwalker pre-commit hook. It is backed up to pre-commit.user and the
    # wrapper chains it first, so the Moonwalker guard is never bypassed; a missing
    # guard script skips instead of breaking unrelated commits.
    script = INSTALL_HOOKS.read_text()

    assert "pre-commit.user" in script
    assert r'grep -qF "$MARKER"' in script
    assert r'if ! "\$user"' in script
    assert r'[ -x "\$guard" ] || exit 0' in script
    assert "git rev-parse --show-toplevel" in script


def test_install_hooks_chains_user_hook_before_guard_at_runtime(tmp_path) -> None:
    # P2 guard-bypass regression: a preserved user hook must run first and the
    # Moonwalker guard must still execute. Proven at runtime in a temp repo.
    repo = tmp_path / "repo"
    scripts = repo / "scripts" / "git"
    scripts.mkdir(parents=True)
    (repo / "frontend").mkdir()
    for name in ("pre-commit", "strip-impeccable-live.sh"):
        dst = scripts / name
        dst.write_text((ROOT_DIR / "scripts" / "git" / name).read_text())
        dst.chmod(0o755)
    (repo / "frontend" / "index.html").write_text("<html>\n</html>\n")

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    git("add", "-A")
    git("commit", "-qm", "init")
    # Seed a non-Moonwalker user hook, then install the guard over it.
    wrapper = repo / ".git" / "hooks" / "pre-commit"
    wrapper.write_text("#!/usr/bin/env bash\necho USER_HOOK_RAN\nexit 0\n")
    wrapper.chmod(0o755)
    subprocess.run(
        [
            "bash",
            str(ROOT_DIR / "scripts" / "git" / "install-hooks.sh"),
        ],
        cwd=str(repo),
        capture_output=True,
        check=False,
    )
    result = subprocess.run(
        ["bash", str(wrapper)],
        cwd=str(repo),
        text=True,
        capture_output=True,
    )
    # The chained user hook ran first, proving the guard did not bypass it.
    assert "USER_HOOK_RAN" in result.stdout


def test_wrapper_skips_gracefully_when_guard_script_is_absent(tmp_path) -> None:
    # P2 worktree-without-guard: a checkout that does not carry the guard
    # script must not break every commit; the wrapper skips gracefully.
    repo = tmp_path / "bare"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=str(repo), capture_output=True)
    wrapper = repo / ".git" / "hooks" / "pre-commit"
    wrapper.write_text(
        '#!/usr/bin/env bash\ndir="$(git rev-parse --show-toplevel 2>/dev/null || true)"\n[ -n "$dir" ] || exit 0\nguard="$dir/scripts/git/pre-commit"\n[ -x "$guard" ] || exit 0\nexec "$guard" "$@"\n'.rstrip()
    )
    wrapper.chmod(0o755)
    result = subprocess.run(
        [
            "bash",
            str(wrapper),
        ],
        cwd=str(repo),
        capture_output=True,
    )
    # No guard script here -> graceful skip (exit 0), not an exec error.
    assert result.returncode == 0
