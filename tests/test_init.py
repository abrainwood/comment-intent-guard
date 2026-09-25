import json
import os
import shutil
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_INIT_SH = _REPO_ROOT / "init.sh"


def _init_tmp_repo(git_repo):
    return subprocess.run(
        ["bash", str(_INIT_SH)], cwd=git_repo, capture_output=True, text=True
    )


def test_bare_repo_gets_all_four_files_with_hookspath_set_and_pre_commit_executable(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

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

    assert ".comment-intent-guard.json created" in result.stdout
    assert ".githooks/pre-commit created" in result.stdout
    assert ".github/workflows/comment-guard.yml created" in result.stdout
    assert "CLAUDE.md created" in result.stdout
    assert "core.hooksPath set to .githooks" in result.stdout


def test_pre_commit_sh_blocks_a_staged_violation_in_a_bare_repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    _stage_violation(tmp_path)

    result = subprocess.run(
        ["bash", str(_PRE_COMMIT_SH)], cwd=tmp_path, capture_output=True, text=True, env=_guard_env()
    )

    assert result.returncode != 0
    assert "bad.py" in result.stdout + result.stderr


def test_second_run_reports_every_file_as_unchanged(git_repo):
    _init_tmp_repo(git_repo)

    result = _init_tmp_repo(git_repo)

    assert ".comment-intent-guard.json unchanged" in result.stdout
    assert ".githooks/pre-commit unchanged" in result.stdout
    assert ".github/workflows/comment-guard.yml unchanged" in result.stdout
    assert "CLAUDE.md unchanged" in result.stdout


def _snapshot(repo):
    files = [
        repo / ".comment-intent-guard.json",
        repo / ".githooks" / "pre-commit",
        repo / ".github" / "workflows" / "comment-guard.yml",
        repo / "CLAUDE.md",
    ]
    return {f: f.read_bytes() for f in files}


def test_second_run_is_a_no_op(git_repo):
    _init_tmp_repo(git_repo)
    before = _snapshot(git_repo)

    result = _init_tmp_repo(git_repo)

    assert result.returncode == 0
    assert _snapshot(git_repo) == before


def test_help_prints_usage_and_exits_0_without_touching_the_repo(git_repo):
    result = subprocess.run(
        ["bash", str(_INIT_SH), "--help"], cwd=git_repo, capture_output=True, text=True
    )

    assert result.returncode == 0
    assert "[--force]" in result.stdout
    assert not (git_repo / ".comment-intent-guard.json").exists()
    assert not (git_repo / ".githooks").exists()
    assert not (git_repo / ".github").exists()
    assert not (git_repo / "CLAUDE.md").exists()
    hooks_path = subprocess.run(
        ["git", "config", "core.hooksPath"], cwd=git_repo, capture_output=True, text=True
    )
    assert hooks_path.returncode != 0
    assert hooks_path.stdout.strip() == ""


def test_unknown_arg_prints_usage_to_stderr_and_exits_2_without_touching_the_repo(git_repo):
    result = subprocess.run(
        ["bash", str(_INIT_SH), "--bogus"], cwd=git_repo, capture_output=True, text=True
    )

    assert result.returncode == 2
    assert "[--force]" in result.stderr
    assert not (git_repo / ".comment-intent-guard.json").exists()
    assert not (git_repo / ".githooks").exists()
    assert not (git_repo / ".github").exists()
    assert not (git_repo / "CLAUDE.md").exists()
    hooks_path = subprocess.run(
        ["git", "config", "core.hooksPath"], cwd=git_repo, capture_output=True, text=True
    )
    assert hooks_path.returncode != 0
    assert hooks_path.stdout.strip() == ""


def test_help_outside_a_git_repo_prints_usage_and_exits_0(tmp_path):
    result = subprocess.run(
        ["bash", str(_INIT_SH), "--help"], cwd=tmp_path, capture_output=True, text=True
    )

    assert result.returncode == 0
    assert "[--force]" in result.stdout


def test_existing_hookspath_pointing_elsewhere_is_refused_and_nothing_is_written(git_repo):
    subprocess.run(["git", "config", "core.hooksPath", "husky/hooks"], cwd=git_repo, check=True)

    result = subprocess.run(["bash", str(_INIT_SH)], cwd=git_repo, capture_output=True, text=True)

    assert result.returncode != 0
    assert "husky/hooks" in result.stderr
    assert not (git_repo / ".comment-intent-guard.json").exists()


def test_native_git_hooks_pre_commit_is_refused_and_nothing_is_written(git_repo):
    native_hook = git_repo / ".git" / "hooks" / "pre-commit"
    native_hook.write_text("#!/bin/sh\necho native\n")

    result = subprocess.run(["bash", str(_INIT_SH)], cwd=git_repo, capture_output=True, text=True)

    assert result.returncode != 0
    assert str(native_hook) in result.stderr
    assert not (git_repo / ".comment-intent-guard.json").exists()


def _write_git_2_26_rev_parse_shim(bin_dir):
    real_git = shutil.which("git")
    shim = bin_dir / "git"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        "args=()\n"
        "for a in \"$@\"; do\n"
        "  if [ \"$a\" = \"--path-format=absolute\" ]; then\n"
        "    echo \"$a\"\n"
        "  else\n"
        "    args+=(\"$a\")\n"
        "  fi\n"
        "done\n"
        f'exec "{real_git}" "${{args[@]}}"\n'
    )
    shim.chmod(0o755)


def test_native_hook_check_works_when_git_garbles_the_unrecognized_path_format_flag(tmp_path, git_repo):
    bin_dir = tmp_path / "oldgitbin"
    bin_dir.mkdir()
    _write_git_2_26_rev_parse_shim(bin_dir)
    repo = git_repo
    native_hook = repo / ".git" / "hooks" / "pre-commit"
    native_hook.write_text("#!/bin/sh\necho native\n")
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}

    result = subprocess.run(
        ["bash", str(_INIT_SH)], cwd=repo, capture_output=True, text=True, env=env
    )

    assert result.returncode != 0
    assert str(native_hook) in result.stderr
    assert not (repo / ".comment-intent-guard.json").exists()


def test_native_hook_check_sees_a_linked_worktrees_shared_hooks_dir(tmp_path, git_repo):
    main_repo = git_repo
    native_hook = main_repo / ".git" / "hooks" / "pre-commit"
    native_hook.write_text("#!/bin/sh\necho native\n")
    worktree = tmp_path / "worktree"
    subprocess.run(
        ["git", "worktree", "add", "-q", str(worktree), "-b", "wt-branch"], cwd=main_repo, check=True
    )

    result = subprocess.run(["bash", str(_INIT_SH)], cwd=worktree, capture_output=True, text=True)

    assert result.returncode != 0
    assert str(native_hook) in result.stderr
    assert not (worktree / ".comment-intent-guard.json").exists()


def test_differing_workflow_yml_is_left_alone_while_other_targets_are_written(git_repo):
    workflow = git_repo / ".github" / "workflows" / "comment-guard.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: something else entirely\n")

    result = subprocess.run(["bash", str(_INIT_SH)], cwd=git_repo, capture_output=True, text=True)

    assert result.returncode == 0
    assert workflow.read_text() == "name: something else entirely\n"
    assert (git_repo / ".comment-intent-guard.json").exists()
    assert (git_repo / ".githooks" / "pre-commit").exists()
    assert (git_repo / "CLAUDE.md").exists()
    hooks_path = subprocess.run(
        ["git", "config", "core.hooksPath"], cwd=git_repo, capture_output=True, text=True, check=True
    )
    assert hooks_path.stdout.strip() == ".githooks"


def test_stale_marked_pre_commit_is_left_alone_while_other_targets_are_written(git_repo):
    (git_repo / ".githooks").mkdir()
    stale = git_repo / ".githooks" / "pre-commit"
    stale.write_text("#!/usr/bin/env bash\n# comment-intent-guard pre-commit\necho stale\n")

    result = subprocess.run(["bash", str(_INIT_SH)], cwd=git_repo, capture_output=True, text=True)

    assert result.returncode == 0
    assert stale.read_text() == "#!/usr/bin/env bash\n# comment-intent-guard pre-commit\necho stale\n"
    assert (git_repo / ".comment-intent-guard.json").exists()
    assert (git_repo / ".github" / "workflows" / "comment-guard.yml").exists()
    assert (git_repo / "CLAUDE.md").exists()


def test_force_overwrites_a_stale_marked_pre_commit(git_repo):
    (git_repo / ".githooks").mkdir()
    stale = git_repo / ".githooks" / "pre-commit"
    stale.write_text("#!/usr/bin/env bash\n# comment-intent-guard pre-commit\necho stale\n")

    result = subprocess.run(
        ["bash", str(_INIT_SH), "--force"], cwd=git_repo, capture_output=True, text=True
    )

    assert result.returncode == 0
    assert stale.read_text() == (_REPO_ROOT / "templates" / "pre-commit.sh").read_text()
    assert ".githooks/pre-commit overwritten" in result.stdout


def test_foreign_pre_commit_is_left_alone_while_other_targets_are_written(git_repo):
    (git_repo / ".githooks").mkdir()
    foreign = git_repo / ".githooks" / "pre-commit"
    foreign.write_text("#!/usr/bin/env bash\necho 'some other tool'\n")

    result = subprocess.run(["bash", str(_INIT_SH)], cwd=git_repo, capture_output=True, text=True)

    assert result.returncode == 0
    assert foreign.read_text() == "#!/usr/bin/env bash\necho 'some other tool'\n"
    assert (git_repo / ".comment-intent-guard.json").exists()
    assert (git_repo / "CLAUDE.md").exists()


def test_force_never_overwrites_a_foreign_unmarked_pre_commit_hook(git_repo):
    (git_repo / ".githooks").mkdir()
    foreign = git_repo / ".githooks" / "pre-commit"
    foreign.write_text("#!/usr/bin/env bash\necho 'some other tool'\n")

    result = subprocess.run(
        ["bash", str(_INIT_SH), "--force"], cwd=git_repo, capture_output=True, text=True
    )

    assert result.returncode == 0
    assert foreign.read_text() == "#!/usr/bin/env bash\necho 'some other tool'\n"
    assert "left alone" in result.stdout


_WORKFLOW_COPY_INSTRUCTIONS = "# Copy into .github/workflows/ to enforce the guard on every PR."


def _workflow_effective_content():
    template = (_REPO_ROOT / "templates" / "comment-guard.yml").read_text()
    assert _WORKFLOW_COPY_INSTRUCTIONS in template
    lines = [line for line in template.splitlines(keepends=True) if line.rstrip("\n") != _WORKFLOW_COPY_INSTRUCTIONS]
    return "".join(lines)


def test_force_overwrites_workflow_but_never_the_allowlist_json(git_repo):
    custom_json = '{"id_prefix_allowlist": ["old"]}'
    (git_repo / ".comment-intent-guard.json").write_text(custom_json)
    workflow = git_repo / ".github" / "workflows" / "comment-guard.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: something else entirely\n")

    result = subprocess.run(
        ["bash", str(_INIT_SH), "--force"], cwd=git_repo, capture_output=True, text=True
    )

    assert result.returncode == 0
    assert (git_repo / ".comment-intent-guard.json").read_text() == custom_json
    assert "merge" in result.stdout.lower()
    assert workflow.read_text() == _workflow_effective_content()


def test_customised_allowlist_json_is_left_byte_identical_while_missing_targets_are_written(git_repo):
    custom_json = json.dumps({"id_prefix_allowlist": ["abc", "def"], "filename_only_id_prefix_allowlist": []})
    (git_repo / ".comment-intent-guard.json").write_text(custom_json)

    result = subprocess.run(["bash", str(_INIT_SH)], cwd=git_repo, capture_output=True, text=True)

    assert result.returncode == 0
    assert (git_repo / ".comment-intent-guard.json").read_text() == custom_json
    assert (git_repo / ".githooks" / "pre-commit").exists()
    assert (git_repo / ".github" / "workflows" / "comment-guard.yml").exists()
    assert (git_repo / "CLAUDE.md").exists()
    hooks_path = subprocess.run(
        ["git", "config", "core.hooksPath"], cwd=git_repo, capture_output=True, text=True, check=True
    )
    assert hooks_path.stdout.strip() == ".githooks"


def test_created_workflow_yml_does_not_carry_the_copy_instructions_line(git_repo):
    result = _init_tmp_repo(git_repo)

    assert result.returncode == 0
    content = (git_repo / ".github" / "workflows" / "comment-guard.yml").read_text()
    assert "Copy into .github/workflows/" not in content
    assert content == _workflow_effective_content()


def test_a_pre_1_1_workflow_carrying_the_copy_line_upgrades_instead_of_being_left_alone(git_repo):
    workflow = git_repo / ".github" / "workflows" / "comment-guard.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text((_REPO_ROOT / "templates" / "comment-guard.yml").read_text())

    result = subprocess.run(["bash", str(_INIT_SH)], cwd=git_repo, capture_output=True, text=True)

    assert result.returncode == 0
    assert "left alone" not in result.stdout
    assert ".github/workflows/comment-guard.yml updated" in result.stdout
    assert workflow.read_text() == _workflow_effective_content()


def test_workflow_containing_only_the_copy_line_does_not_crash_the_upgrade_check(git_repo):
    workflow = git_repo / ".github" / "workflows" / "comment-guard.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(_WORKFLOW_COPY_INSTRUCTIONS + "\n")

    result = subprocess.run(["bash", str(_INIT_SH)], cwd=git_repo, capture_output=True, text=True)

    assert result.returncode == 0
    assert "comment-guard.yml" in result.stdout


def test_claude_md_marker_already_present_is_not_duplicated(git_repo):
    existing = "# My repo\n\n<!-- comment-intent-guard:comment-guard-init -->\nAlready wired up.\n"
    (git_repo / "CLAUDE.md").write_text(existing)

    result = subprocess.run(["bash", str(_INIT_SH)], cwd=git_repo, capture_output=True, text=True)

    assert result.returncode == 0
    assert (git_repo / "CLAUDE.md").read_text() == existing


def test_claude_md_append_separates_with_a_newline_when_file_lacks_trailing_newline(git_repo):
    (git_repo / "CLAUDE.md").write_text("# My repo\nNo trailing newline here")

    result = subprocess.run(["bash", str(_INIT_SH)], cwd=git_repo, capture_output=True, text=True)

    assert result.returncode == 0
    content = (git_repo / "CLAUDE.md").read_text()
    assert "here\n\n<!-- comment-intent-guard:comment-guard-init -->" in content
    assert "CLAUDE.md appended" in result.stdout


_BIN_WRAPPER = _REPO_ROOT / "bin" / "comment-intent-guard"


def test_bin_wrapper_check_help_shows_the_comment_intent_guard_check_prog_name(tmp_path):
    result = subprocess.run(
        ["sh", str(_BIN_WRAPPER), "check", "--help"], cwd=tmp_path, capture_output=True, text=True
    )

    assert result.returncode == 0
    assert "usage: comment-intent-guard check " in result.stdout


def test_bin_wrapper_init_behaves_like_init_sh(git_repo):
    result = subprocess.run(
        ["sh", str(_BIN_WRAPPER), "init"], cwd=git_repo, capture_output=True, text=True
    )

    assert result.returncode == 0
    assert (git_repo / ".comment-intent-guard.json").exists()
    assert (git_repo / ".githooks" / "pre-commit").exists()
    assert (git_repo / ".github" / "workflows" / "comment-guard.yml").exists()
    assert (git_repo / "CLAUDE.md").exists()


def test_bin_wrapper_resolves_through_a_symlink(git_repo):
    link = git_repo / "civg"
    link.symlink_to(_BIN_WRAPPER)

    result = subprocess.run(["sh", str(link), "init"], cwd=git_repo, capture_output=True, text=True)

    assert result.returncode == 0
    assert (git_repo / ".comment-intent-guard.json").exists()


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


def _stub_guard_env(tmp_path, script_body):
    stub = tmp_path / "stub_guard.py"
    stub.write_text(script_body)
    return stub, {**os.environ, "COMMENT_INTENT_GUARD": str(stub)}


def _argv_recording_stub_body(exit_code):
    return f"import sys\nprint('ARGV:' + ' '.join(sys.argv[1:]))\nsys.exit({exit_code})\n"


def _argv_file_recording_stub_body(path):
    return f"import sys\nopen({str(path)!r}, 'w').write(' '.join(sys.argv[1:]))\nsys.exit(0)\n"


def _passed_files(stdout):
    return [a for a in stdout.split("ARGV:", 1)[1].split() if a != "--all"]


def test_pre_commit_blocks_a_staged_violating_python_file_and_prints_the_finding(initialised_repo):
    pre_commit = initialised_repo / ".githooks" / "pre-commit"
    violating = initialised_repo / "bad.py"
    violating.write_text('def test_x():\n    """a docstring"""\n')
    subprocess.run(["git", "add", "bad.py"], cwd=initialised_repo, check=True)

    result = subprocess.run(
        ["bash", str(pre_commit)],
        cwd=initialised_repo,
        capture_output=True,
        text=True,
        env=_guard_env(),
    )

    assert result.returncode == 1
    assert "BLOCKED" in result.stdout + result.stderr
    assert "opens with a docstring" in result.stdout + result.stderr
    assert "commit aborted" in result.stderr


def test_pre_commit_exit_4_from_the_guard_warns_and_passes(initialised_repo):
    pre_commit = initialised_repo / ".githooks" / "pre-commit"
    (initialised_repo / "thing.py").write_text("VALUE = 1\n")
    subprocess.run(["git", "add", "thing.py"], cwd=initialised_repo, check=True)
    stub, env = _stub_guard_env(initialised_repo, "import sys\nsys.exit(4)\n")

    result = subprocess.run(
        ["bash", str(pre_commit)], cwd=initialised_repo, capture_output=True, text=True, env=env,
    )

    assert result.returncode == 0
    assert str(stub) in result.stderr
    assert "Python" in result.stderr
    assert "exited 4" in result.stderr


_PRE_COMMIT_SH = _REPO_ROOT / "templates" / "pre-commit.sh"


def _stage_violation(repo):
    (repo / "bad.py").write_text('def test_x():\n    """a docstring"""\n')
    subprocess.run(["git", "add", "bad.py"], cwd=repo, check=True)


def test_script_discovery_falls_back_to_claude_plugin_root_when_env_is_unset(git_repo):
    _stage_violation(git_repo)
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(_REPO_ROOT)}
    env.pop("COMMENT_INTENT_GUARD", None)

    result = subprocess.run(
        ["bash", str(_PRE_COMMIT_SH)], cwd=git_repo, capture_output=True, text=True, env=env
    )

    assert result.returncode != 0
    assert "bad.py" in result.stdout + result.stderr


def test_script_discovery_resolves_via_installed_plugins_json(tmp_path, git_repo):
    import json

    repo = git_repo
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


def test_script_discovery_warns_and_falls_through_on_malformed_installed_plugins_json(tmp_path, git_repo):
    repo = git_repo
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


def test_script_discovery_warns_and_falls_through_on_wrong_shaped_installed_plugins_json(tmp_path, git_repo):
    repo = git_repo
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


def test_script_discovery_falls_back_to_newest_under_claude_plugins_cache_dir(tmp_path, git_repo):
    repo = git_repo
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


def test_script_discovery_picks_the_newer_of_two_plugin_candidates(tmp_path, git_repo):
    repo = git_repo
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


def test_pre_commit_allows_a_clean_staged_python_file(initialised_repo):
    pre_commit = initialised_repo / ".githooks" / "pre-commit"
    clean = initialised_repo / "good.py"
    clean.write_text("def add(a, b):\n    return a + b\n")
    subprocess.run(["git", "add", "good.py"], cwd=initialised_repo, check=True)
    argv_log = initialised_repo / "argv.log"
    _, env = _stub_guard_env(initialised_repo, _argv_file_recording_stub_body(argv_log))

    result = subprocess.run(
        ["bash", str(pre_commit)],
        cwd=initialised_repo,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    passed = [a for a in argv_log.read_text().split() if a != "--all"]
    assert passed == ["good.py"]


def test_pre_commit_prints_advisory_findings_and_still_allows_the_commit(initialised_repo):
    pre_commit = initialised_repo / ".githooks" / "pre-commit"
    advisory_only = initialised_repo / "config.yaml"
    advisory_only.write_text("key: value\n")
    subprocess.run(["git", "add", "config.yaml"], cwd=initialised_repo, check=True)
    _, env = _stub_guard_env(
        initialised_repo, "print('config.yaml: advisory finding')\nimport sys\nsys.exit(1)\n"
    )

    result = subprocess.run(
        ["bash", str(pre_commit)],
        cwd=initialised_repo,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    assert "config.yaml: advisory finding" in result.stdout


def test_pre_commit_passes_with_a_warning_when_no_discovery_arm_resolves(initialised_repo):
    pre_commit = initialised_repo / ".githooks" / "pre-commit"
    violating = initialised_repo / "bad.py"
    violating.write_text('def test_x():\n    """a docstring"""\n')
    subprocess.run(["git", "add", "bad.py"], cwd=initialised_repo, check=True)
    env = {**os.environ, "HOME": str(initialised_repo / "empty_home")}
    env.pop("COMMENT_INTENT_GUARD", None)
    env.pop("CLAUDE_PLUGIN_ROOT", None)

    result = subprocess.run(
        ["bash", str(pre_commit)], cwd=initialised_repo, capture_output=True, text=True, env=env
    )

    assert result.returncode == 0
    assert "could not locate" in result.stderr


def test_pre_commit_ignores_a_staged_txt_file_but_checks_a_staged_yaml_file(initialised_repo):
    pre_commit = initialised_repo / ".githooks" / "pre-commit"
    (initialised_repo / "notes.txt").write_text('"""a docstring"""\nnot code, should be ignored\n')
    (initialised_repo / "bad.yaml").write_text("name: x\n")
    subprocess.run(["git", "add", "notes.txt", "bad.yaml"], cwd=initialised_repo, check=True)
    _, env = _stub_guard_env(initialised_repo, _argv_recording_stub_body(1))

    result = subprocess.run(
        ["bash", str(pre_commit)],
        cwd=initialised_repo,
        capture_output=True,
        text=True,
        env=env,
    )

    assert _passed_files(result.stdout) == ["bad.yaml"]


def test_pre_commit_passes_exactly_the_checked_extensions_to_the_guard(git_repo):
    _, env = _stub_guard_env(git_repo, _argv_recording_stub_body(1))
    checked = ["a.py", "b.yml", "c.yaml", "d.jinja", "e.j2"]
    ignored = ["f.txt"]
    for name in checked + ignored:
        (git_repo / name).write_text("x\n")
    subprocess.run(["git", "add", *checked, *ignored], cwd=git_repo, check=True)

    result = subprocess.run(
        ["bash", str(_PRE_COMMIT_SH)], cwd=git_repo, capture_output=True, text=True, env=env
    )

    assert result.returncode == 0
    assert set(_passed_files(result.stdout)) == set(checked)


def test_pre_commit_handles_a_non_ascii_staged_filename(initialised_repo):
    pre_commit = initialised_repo / ".githooks" / "pre-commit"
    target = initialised_repo / "café.py"
    target.write_text("x = 1\n")
    subprocess.run(["git", "add", "café.py"], cwd=initialised_repo, check=True)
    _, env = _stub_guard_env(initialised_repo, _argv_recording_stub_body(1))

    result = subprocess.run(
        ["bash", str(pre_commit)],
        cwd=initialised_repo,
        capture_output=True,
        text=True,
        env=env,
    )

    assert _passed_files(result.stdout) == ["café.py"]
    assert "caf\\303\\251.py" not in result.stdout + result.stderr


def test_pre_commit_blocks_a_staged_violation_even_when_the_worktree_copy_was_later_fixed(initialised_repo):
    pre_commit = initialised_repo / ".githooks" / "pre-commit"
    staged_then_fixed = initialised_repo / "sneaky.py"
    staged_then_fixed.write_text('def test_x():\n    """a docstring"""\n')
    subprocess.run(["git", "add", "sneaky.py"], cwd=initialised_repo, check=True)
    staged_then_fixed.write_text("def add(a, b):\n    return a + b\n")

    result = subprocess.run(
        ["bash", str(pre_commit)],
        cwd=initialised_repo,
        capture_output=True,
        text=True,
        env=_guard_env(),
    )

    assert result.returncode != 0
    assert "sneaky.py" in result.stdout + result.stderr


def test_pre_commit_honors_a_staged_id_prefix_allowlist_for_a_filename_id_token(initialised_repo):
    pre_commit = initialised_repo / ".githooks" / "pre-commit"
    config = initialised_repo / ".comment-intent-guard.json"
    config.write_text(json.dumps({"id_prefix_allowlist": ["abc"]}))
    allowed = initialised_repo / "abc12.py"
    allowed.write_text("def add(a, b):\n    return a + b\n")
    subprocess.run(["git", "add", ".comment-intent-guard.json", "abc12.py"], cwd=initialised_repo, check=True)

    result = subprocess.run(
        ["bash", str(pre_commit)],
        cwd=initialised_repo,
        capture_output=True,
        text=True,
        env=_guard_env(),
    )

    assert result.returncode == 0


def test_pre_commit_allows_a_staged_clean_file_even_when_the_worktree_copy_was_later_broken(initialised_repo):
    pre_commit = initialised_repo / ".githooks" / "pre-commit"
    staged_then_broken = initialised_repo / "sneaky.py"
    staged_then_broken.write_text("def add(a, b):\n    return a + b\n")
    subprocess.run(["git", "add", "sneaky.py"], cwd=initialised_repo, check=True)
    staged_then_broken.write_text('def test_x():\n    """a docstring"""\n')

    result = subprocess.run(
        ["bash", str(pre_commit)],
        cwd=initialised_repo,
        capture_output=True,
        text=True,
        env=_guard_env(),
    )

    assert result.returncode == 0
