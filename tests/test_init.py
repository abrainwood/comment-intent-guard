import json
import os
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_INIT_SH = _REPO_ROOT / "init.sh"


def _init_tmp_repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return subprocess.run(
        ["bash", str(_INIT_SH)], cwd=tmp_path, capture_output=True, text=True
    )


def test_fresh_repo_gets_all_four_files_with_hookspath_set_and_pre_commit_executable(tmp_path):
    result = _init_tmp_repo(tmp_path)

    assert result.returncode == 0
    assert (tmp_path / ".comment-intent-guard.json").exists()
    assert (tmp_path / ".githooks" / "pre-commit").exists()
    assert (tmp_path / ".github" / "workflows" / "comment-guard.yml").exists()
    assert (tmp_path / "CLAUDE.md").exists()

    hooks_path = subprocess.run(
        ["git", "config", "core.hooksPath"], cwd=tmp_path, capture_output=True, text=True, check=True
    )
    assert hooks_path.stdout.strip() == ".githooks"

    pre_commit = tmp_path / ".githooks" / "pre-commit"
    assert pre_commit.stat().st_mode & 0o111

    assert "created .comment-intent-guard.json" in result.stdout
    assert "created .githooks/pre-commit" in result.stdout
    assert "created .github/workflows/comment-guard.yml" in result.stdout
    assert "created CLAUDE.md" in result.stdout
    assert "core.hooksPath set to .githooks" in result.stdout


def test_second_run_reports_every_file_as_unchanged(tmp_path):
    _init_tmp_repo(tmp_path)

    result = _init_tmp_repo(tmp_path)

    assert "unchanged .comment-intent-guard.json" in result.stdout
    assert "unchanged .githooks/pre-commit" in result.stdout
    assert "unchanged .github/workflows/comment-guard.yml" in result.stdout
    assert "unchanged CLAUDE.md" in result.stdout


def _snapshot(tmp_path):
    files = [
        tmp_path / ".comment-intent-guard.json",
        tmp_path / ".githooks" / "pre-commit",
        tmp_path / ".github" / "workflows" / "comment-guard.yml",
        tmp_path / "CLAUDE.md",
    ]
    return {f: f.read_bytes() for f in files}


def test_second_run_is_a_no_op(tmp_path):
    _init_tmp_repo(tmp_path)
    before = _snapshot(tmp_path)

    result = _init_tmp_repo(tmp_path)

    assert result.returncode == 0
    assert _snapshot(tmp_path) == before


def test_existing_hookspath_pointing_elsewhere_is_refused_and_nothing_is_written(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "core.hooksPath", "husky/hooks"], cwd=tmp_path, check=True)

    result = subprocess.run(["bash", str(_INIT_SH)], cwd=tmp_path, capture_output=True, text=True)

    assert result.returncode != 0
    assert "husky/hooks" in result.stderr
    assert not (tmp_path / ".comment-intent-guard.json").exists()


def test_native_git_hooks_pre_commit_is_refused_and_nothing_is_written(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    native_hook = tmp_path / ".git" / "hooks" / "pre-commit"
    native_hook.write_text("#!/bin/sh\necho native\n")

    result = subprocess.run(["bash", str(_INIT_SH)], cwd=tmp_path, capture_output=True, text=True)

    assert result.returncode != 0
    assert str(native_hook) in result.stderr
    assert not (tmp_path / ".comment-intent-guard.json").exists()


def test_differing_workflow_yml_is_refused_before_any_write(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    workflow = tmp_path / ".github" / "workflows" / "comment-guard.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: something else entirely\n")

    result = subprocess.run(["bash", str(_INIT_SH)], cwd=tmp_path, capture_output=True, text=True)

    assert result.returncode != 0
    assert workflow.read_text() == "name: something else entirely\n"
    assert not (tmp_path / ".comment-intent-guard.json").exists()
    assert not (tmp_path / ".githooks" / "pre-commit").exists()
    hooks_path = subprocess.run(
        ["git", "config", "core.hooksPath"], cwd=tmp_path, capture_output=True, text=True
    )
    assert hooks_path.returncode != 0 or hooks_path.stdout.strip() == ""


def test_stale_marked_pre_commit_is_refused_without_force(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".githooks").mkdir()
    stale = tmp_path / ".githooks" / "pre-commit"
    stale.write_text("#!/usr/bin/env bash\n# comment-intent-guard pre-commit\necho stale\n")

    result = subprocess.run(["bash", str(_INIT_SH)], cwd=tmp_path, capture_output=True, text=True)

    assert result.returncode != 0
    assert stale.read_text() == "#!/usr/bin/env bash\n# comment-intent-guard pre-commit\necho stale\n"


def test_force_overwrites_a_stale_marked_pre_commit(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".githooks").mkdir()
    stale = tmp_path / ".githooks" / "pre-commit"
    stale.write_text("#!/usr/bin/env bash\n# comment-intent-guard pre-commit\necho stale\n")

    result = subprocess.run(
        ["bash", str(_INIT_SH), "--force"], cwd=tmp_path, capture_output=True, text=True
    )

    assert result.returncode == 0
    assert stale.read_text() == (_REPO_ROOT / "templates" / "pre-commit.sh").read_text()
    assert "overwritten .githooks/pre-commit" in result.stdout


def test_foreign_pre_commit_is_refused_and_nothing_is_written(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".githooks").mkdir()
    foreign = tmp_path / ".githooks" / "pre-commit"
    foreign.write_text("#!/usr/bin/env bash\necho 'some other tool'\n")

    result = subprocess.run(["bash", str(_INIT_SH)], cwd=tmp_path, capture_output=True, text=True)

    assert result.returncode != 0
    assert str(foreign) in result.stderr
    assert foreign.read_text() == "#!/usr/bin/env bash\necho 'some other tool'\n"
    assert not (tmp_path / ".comment-intent-guard.json").exists()
    assert not (tmp_path / "CLAUDE.md").exists()


def test_force_overwrites_a_differing_json_and_workflow_yml(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".comment-intent-guard.json").write_text('{"id_prefix_allowlist": ["old"]}')
    workflow = tmp_path / ".github" / "workflows" / "comment-guard.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: something else entirely\n")

    result = subprocess.run(
        ["bash", str(_INIT_SH), "--force"], cwd=tmp_path, capture_output=True, text=True
    )

    assert result.returncode == 0
    assert (tmp_path / ".comment-intent-guard.json").read_text() == (
        _REPO_ROOT / "templates" / "comment-intent-guard.json"
    ).read_text()
    assert workflow.read_text() == (_REPO_ROOT / "templates" / "comment-guard.yml").read_text()


def test_claude_md_marker_already_present_is_not_duplicated(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    existing = "# My repo\n\n<!-- comment-intent-guard:comment-guard-init -->\nAlready wired up.\n"
    (tmp_path / "CLAUDE.md").write_text(existing)

    result = subprocess.run(["bash", str(_INIT_SH)], cwd=tmp_path, capture_output=True, text=True)

    assert result.returncode == 0
    assert (tmp_path / "CLAUDE.md").read_text() == existing


def test_claude_md_append_separates_with_a_newline_when_file_lacks_trailing_newline(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "CLAUDE.md").write_text("# My repo\nNo trailing newline here")

    result = subprocess.run(["bash", str(_INIT_SH)], cwd=tmp_path, capture_output=True, text=True)

    assert result.returncode == 0
    content = (tmp_path / "CLAUDE.md").read_text()
    assert "here\n\n<!-- comment-intent-guard:comment-guard-init -->" in content
    assert "appended CLAUDE.md" in result.stdout


_BIN_WRAPPER = _REPO_ROOT / "bin" / "comment-intent-guard"


def test_bin_wrapper_init_behaves_like_init_sh(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    result = subprocess.run(
        ["sh", str(_BIN_WRAPPER), "init"], cwd=tmp_path, capture_output=True, text=True
    )

    assert result.returncode == 0
    assert (tmp_path / ".comment-intent-guard.json").exists()
    assert (tmp_path / ".githooks" / "pre-commit").exists()
    assert (tmp_path / ".github" / "workflows" / "comment-guard.yml").exists()
    assert (tmp_path / "CLAUDE.md").exists()


def test_bin_wrapper_check_exits_3_on_a_violating_file(tmp_path):
    violating = tmp_path / "bad.py"
    violating.write_text('def test_x():\n    """a docstring"""\n')

    result = subprocess.run(
        ["sh", str(_BIN_WRAPPER), "check", "--all", str(violating)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 3


def _guard_env():
    return {**os.environ, "COMMENT_INTENT_GUARD": str(_REPO_ROOT / "comment_intent_guard.py")}


def _init_repo_and_get_pre_commit(tmp_path):
    _init_tmp_repo(tmp_path)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", "init"],
        cwd=tmp_path,
        check=True,
        env=_guard_env(),
    )
    return tmp_path / ".githooks" / "pre-commit"


def test_pre_commit_blocks_a_staged_violating_python_file_and_prints_the_finding(tmp_path):
    pre_commit = _init_repo_and_get_pre_commit(tmp_path)
    violating = tmp_path / "bad.py"
    violating.write_text('def test_x():\n    """a docstring"""\n')
    subprocess.run(["git", "add", "bad.py"], cwd=tmp_path, check=True)

    result = subprocess.run(
        ["bash", str(pre_commit)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_guard_env(),
    )

    assert result.returncode == 1
    assert "BLOCKED" in result.stdout + result.stderr
    assert "opens with a docstring" in result.stdout + result.stderr
    assert "commit aborted" in result.stderr


def test_pre_commit_exit_4_from_the_guard_warns_and_passes(tmp_path):
    pre_commit = _init_repo_and_get_pre_commit(tmp_path)
    unreadable = tmp_path / "unreadable.py"
    # invalid UTF-8 makes the guard's own file read raise UnicodeDecodeError,
    # which it reports as an internal error (exit 4), not a bright line.
    unreadable.write_bytes(b"\xff\xfe\x00bad-bytes")
    subprocess.run(["git", "add", "unreadable.py"], cwd=tmp_path, check=True)

    result = subprocess.run(
        ["bash", str(pre_commit)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_guard_env(),
    )

    assert result.returncode == 0
    assert str(_REPO_ROOT / "comment_intent_guard.py") in result.stderr
    assert "Python" in result.stderr
    assert "exited 4" in result.stderr


_PRE_COMMIT_SH = _REPO_ROOT / "templates" / "pre-commit.sh"


def _stage_violation(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "bad.py").write_text('def test_x():\n    """a docstring"""\n')
    subprocess.run(["git", "add", "bad.py"], cwd=tmp_path, check=True)


def test_script_discovery_falls_back_to_claude_plugin_root_when_env_is_unset(tmp_path):
    _stage_violation(tmp_path)
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(_REPO_ROOT)}
    env.pop("COMMENT_INTENT_GUARD", None)

    result = subprocess.run(
        ["bash", str(_PRE_COMMIT_SH)], cwd=tmp_path, capture_output=True, text=True, env=env
    )

    assert result.returncode != 0
    assert "bad.py" in result.stdout + result.stderr


def test_script_discovery_resolves_via_installed_plugins_json(tmp_path):
    import json

    repo = tmp_path / "repo"
    repo.mkdir()
    _stage_violation(repo)
    fake_home = tmp_path / "fake_home"
    install_dir = fake_home / ".claude" / "plugins" / "cache" / "some-marketplace" / "comment-intent-guard" / "1.0.0"
    install_dir.mkdir(parents=True)
    (install_dir / "comment_intent_guard.py").write_text(
        (_REPO_ROOT / "comment_intent_guard.py").read_text()
    )
    installed_json = fake_home / ".claude" / "plugins" / "installed_plugins.json"
    installed_json.write_text(json.dumps({
        "version": 2,
        "plugins": {
            "comment-intent-guard@some-marketplace": [
                {
                    "scope": "user",
                    "installPath": str(install_dir),
                    "version": "1.0.0",
                    "installedAt": "2026-01-01T00:00:00.000Z",
                    "lastUpdated": "2026-01-01T00:00:00.000Z",
                }
            ]
        },
    }))
    env = {**os.environ, "HOME": str(fake_home)}
    env.pop("COMMENT_INTENT_GUARD", None)
    env.pop("CLAUDE_PLUGIN_ROOT", None)

    result = subprocess.run(
        ["bash", str(_PRE_COMMIT_SH)], cwd=repo, capture_output=True, text=True, env=env
    )

    assert result.returncode != 0
    assert "bad.py" in result.stdout + result.stderr


def test_script_discovery_warns_and_falls_through_on_malformed_installed_plugins_json(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _stage_violation(repo)
    fake_home = tmp_path / "fake_home"
    plugins_dir = fake_home / ".claude" / "plugins"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "installed_plugins.json").write_text("{not valid json")
    env = {**os.environ, "HOME": str(fake_home)}
    env.pop("COMMENT_INTENT_GUARD", None)
    env.pop("CLAUDE_PLUGIN_ROOT", None)

    result = subprocess.run(
        ["bash", str(_PRE_COMMIT_SH)], cwd=repo, capture_output=True, text=True, env=env
    )

    assert result.returncode == 0
    assert "installed_plugins.json" in result.stderr
    assert "Traceback" not in result.stderr


def test_script_discovery_warns_and_falls_through_on_wrong_shaped_installed_plugins_json(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _stage_violation(repo)
    fake_home = tmp_path / "fake_home"
    plugins_dir = fake_home / ".claude" / "plugins"
    plugins_dir.mkdir(parents=True)
    (plugins_dir / "installed_plugins.json").write_text("[]")
    env = {**os.environ, "HOME": str(fake_home)}
    env.pop("COMMENT_INTENT_GUARD", None)
    env.pop("CLAUDE_PLUGIN_ROOT", None)

    result = subprocess.run(
        ["bash", str(_PRE_COMMIT_SH)], cwd=repo, capture_output=True, text=True, env=env
    )

    assert result.returncode == 0
    assert "installed_plugins.json" in result.stderr
    assert "Traceback" not in result.stderr


def test_script_discovery_falls_back_to_newest_under_claude_plugins_cache_dir(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _stage_violation(repo)
    fake_home = tmp_path / "fake_home"
    plugin_dir = fake_home / ".claude" / "plugins" / "cache" / "some-marketplace" / "comment-intent-guard" / "1.0.0"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "comment_intent_guard.py").write_text(
        (_REPO_ROOT / "comment_intent_guard.py").read_text()
    )
    env = {**os.environ, "HOME": str(fake_home)}
    env.pop("COMMENT_INTENT_GUARD", None)
    env.pop("CLAUDE_PLUGIN_ROOT", None)

    result = subprocess.run(
        ["bash", str(_PRE_COMMIT_SH)], cwd=repo, capture_output=True, text=True, env=env
    )

    assert result.returncode != 0
    assert "bad.py" in result.stdout + result.stderr


def test_script_discovery_picks_the_newer_of_two_plugin_candidates(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _stage_violation(repo)
    fake_home = tmp_path / "fake_home"
    cache = fake_home / ".claude" / "plugins" / "cache"
    older_dir = cache / "marketplace-a" / "comment-intent-guard" / "1.0.0"
    newer_dir = cache / "marketplace-b" / "comment-intent-guard" / "2.0.0"
    older_dir.mkdir(parents=True)
    newer_dir.mkdir(parents=True)

    stub = (
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "print('MARKER_{label}: ' + ' '.join(sys.argv[1:]))\n"
        "sys.exit(1)\n"
    )
    (older_dir / "comment_intent_guard.py").write_text(stub.format(label="OLDER"))
    (newer_dir / "comment_intent_guard.py").write_text(stub.format(label="NEWER"))

    old_time = 1_700_000_000
    new_time = 1_800_000_000
    os.utime(older_dir / "comment_intent_guard.py", (old_time, old_time))
    os.utime(newer_dir / "comment_intent_guard.py", (new_time, new_time))

    env = {**os.environ, "HOME": str(fake_home)}
    env.pop("COMMENT_INTENT_GUARD", None)
    env.pop("CLAUDE_PLUGIN_ROOT", None)

    result = subprocess.run(
        ["bash", str(_PRE_COMMIT_SH)], cwd=repo, capture_output=True, text=True, env=env
    )

    assert "MARKER_NEWER" in result.stdout
    assert "MARKER_OLDER" not in result.stdout


def test_pre_commit_allows_a_clean_staged_python_file(tmp_path):
    pre_commit = _init_repo_and_get_pre_commit(tmp_path)
    clean = tmp_path / "good.py"
    clean.write_text("def add(a, b):\n    return a + b\n")
    subprocess.run(["git", "add", "good.py"], cwd=tmp_path, check=True)

    result = subprocess.run(
        ["bash", str(pre_commit)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_guard_env(),
    )

    assert result.returncode == 0


def test_pre_commit_passes_with_a_warning_when_no_discovery_arm_resolves(tmp_path):
    pre_commit = _init_repo_and_get_pre_commit(tmp_path)
    violating = tmp_path / "bad.py"
    violating.write_text('def test_x():\n    """a docstring"""\n')
    subprocess.run(["git", "add", "bad.py"], cwd=tmp_path, check=True)
    env = {**os.environ, "HOME": str(tmp_path / "empty_home")}
    env.pop("COMMENT_INTENT_GUARD", None)
    env.pop("CLAUDE_PLUGIN_ROOT", None)

    result = subprocess.run(
        ["bash", str(pre_commit)], cwd=tmp_path, capture_output=True, text=True, env=env
    )

    assert result.returncode == 0
    assert "could not locate" in result.stderr


def test_pre_commit_ignores_a_staged_txt_file_but_checks_a_staged_yaml_file(tmp_path):
    pre_commit = _init_repo_and_get_pre_commit(tmp_path)
    (tmp_path / "notes.txt").write_text('"""a docstring"""\nnot code, should be ignored\n')
    violating_yaml = tmp_path / "bad.yaml"
    violating_yaml.write_text("name: x  # 2026-01-01 added this\n")
    subprocess.run(["git", "add", "notes.txt", "bad.yaml"], cwd=tmp_path, check=True)

    result = subprocess.run(
        ["bash", str(pre_commit)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_guard_env(),
    )

    assert "notes.txt" not in result.stdout + result.stderr
    assert "bad.yaml" in result.stdout + result.stderr


def test_pre_commit_handles_a_non_ascii_staged_filename(tmp_path):
    pre_commit = _init_repo_and_get_pre_commit(tmp_path)
    violating = tmp_path / "café.py"
    violating.write_text('def test_x():\n    """a docstring"""\n')
    subprocess.run(["git", "add", "café.py"], cwd=tmp_path, check=True)

    result = subprocess.run(
        ["bash", str(pre_commit)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_guard_env(),
    )

    assert result.returncode == 1
    assert "café.py" in result.stdout + result.stderr
    assert "caf\\303\\251.py" not in result.stdout + result.stderr


def test_pre_commit_blocks_a_staged_violation_even_when_the_worktree_copy_was_later_fixed(tmp_path):
    pre_commit = _init_repo_and_get_pre_commit(tmp_path)
    target = tmp_path / "sneaky.py"
    target.write_text('def test_x():\n    """a docstring"""\n')
    subprocess.run(["git", "add", "sneaky.py"], cwd=tmp_path, check=True)
    # Fix it in the worktree without re-staging - the index still holds the violation.
    target.write_text("def add(a, b):\n    return a + b\n")

    result = subprocess.run(
        ["bash", str(pre_commit)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_guard_env(),
    )

    assert result.returncode != 0
    assert "sneaky.py" in result.stdout + result.stderr


def test_pre_commit_honors_a_staged_id_prefix_allowlist_for_a_filename_id_token(tmp_path):
    pre_commit = _init_repo_and_get_pre_commit(tmp_path)
    config = tmp_path / ".comment-intent-guard.json"
    config.write_text(json.dumps({"id_prefix_allowlist": ["abc"]}))
    allowed = tmp_path / "abc12.py"
    allowed.write_text("def add(a, b):\n    return a + b\n")
    subprocess.run(["git", "add", ".comment-intent-guard.json", "abc12.py"], cwd=tmp_path, check=True)

    result = subprocess.run(
        ["bash", str(pre_commit)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_guard_env(),
    )

    assert result.returncode == 0


def test_pre_commit_allows_a_staged_clean_file_even_when_the_worktree_copy_was_later_broken(tmp_path):
    pre_commit = _init_repo_and_get_pre_commit(tmp_path)
    target = tmp_path / "sneaky.py"
    target.write_text("def add(a, b):\n    return a + b\n")
    subprocess.run(["git", "add", "sneaky.py"], cwd=tmp_path, check=True)
    # Break it in the worktree without re-staging - the index still holds the clean version.
    target.write_text('def test_x():\n    """a docstring"""\n')

    result = subprocess.run(
        ["bash", str(pre_commit)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=_guard_env(),
    )

    assert result.returncode == 0
