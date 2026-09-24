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


def test_foreign_pre_commit_is_refused_and_nothing_is_written(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".githooks").mkdir()
    foreign = tmp_path / ".githooks" / "pre-commit"
    foreign.write_text("#!/usr/bin/env bash\necho 'some other tool'\n")

    result = subprocess.run(["bash", str(_INIT_SH)], cwd=tmp_path, capture_output=True, text=True)

    assert result.returncode != 0
    assert "pre-commit" in result.stderr
    assert foreign.read_text() == "#!/usr/bin/env bash\necho 'some other tool'\n"
    assert not (tmp_path / ".comment-intent-guard.json").exists()
    assert not (tmp_path / "CLAUDE.md").exists()


def test_claude_md_marker_already_present_is_not_duplicated(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    existing = "# My repo\n\n<!-- comment-intent-guard:comment-guard-init -->\nAlready wired up.\n"
    (tmp_path / "CLAUDE.md").write_text(existing)

    result = subprocess.run(["bash", str(_INIT_SH)], cwd=tmp_path, capture_output=True, text=True)

    assert result.returncode == 0
    assert (tmp_path / "CLAUDE.md").read_text() == existing


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

    assert result.returncode != 0
    assert "bad.py" in result.stdout + result.stderr


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


def test_script_discovery_falls_back_to_newest_under_claude_plugins_dir(tmp_path, monkeypatch):
    _stage_violation(tmp_path)
    fake_home = tmp_path.parent / "fake_home"
    plugin_dir = fake_home / ".claude" / "plugins" / "some-marketplace" / "comment-intent-guard"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "comment_intent_guard.py").write_text(
        (_REPO_ROOT / "comment_intent_guard.py").read_text()
    )
    env = {**os.environ, "HOME": str(fake_home)}
    env.pop("COMMENT_INTENT_GUARD", None)
    env.pop("CLAUDE_PLUGIN_ROOT", None)

    result = subprocess.run(
        ["bash", str(_PRE_COMMIT_SH)], cwd=tmp_path, capture_output=True, text=True, env=env
    )

    assert result.returncode != 0
    assert "bad.py" in result.stdout + result.stderr


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
