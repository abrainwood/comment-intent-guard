import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BIN_WRAPPER = _REPO_ROOT / "bin" / "comment-intent-guard"


def test_scan_outside_a_git_repo_exits_2_with_a_message(tmp_path):
    result = subprocess.run(
        ["sh", str(_BIN_WRAPPER), "scan"], cwd=tmp_path, capture_output=True, text=True
    )

    assert result.returncode == 2
    assert "git" in result.stderr.lower()


def _init_repo_with_a_commit(repo_dir):
    subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)
    (repo_dir / "committed.py").write_text("def add(a, b):\n    return a + b\n")
    subprocess.run(["git", "add", "committed.py"], cwd=repo_dir, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", "init"],
        cwd=repo_dir,
        check=True,
    )


def test_scan_on_a_clean_repo_exits_0_with_nothing_uncommitted(tmp_path):
    _init_repo_with_a_commit(tmp_path)

    result = subprocess.run(
        ["sh", str(_BIN_WRAPPER), "scan"], cwd=tmp_path, capture_output=True, text=True
    )

    assert result.returncode == 0
    assert "nothing uncommitted" in result.stdout


def test_scan_reports_an_untracked_violating_python_file_and_exits_3(tmp_path):
    _init_repo_with_a_commit(tmp_path)
    (tmp_path / "bad.py").write_text('def test_x():\n    """a docstring"""\n')

    result = subprocess.run(
        ["sh", str(_BIN_WRAPPER), "scan"], cwd=tmp_path, capture_output=True, text=True
    )

    assert result.returncode == 3
    assert "bad.py" in result.stdout + result.stderr


def test_scan_does_not_flag_a_pre_existing_advisory_touched_only_by_a_clean_append(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    config = tmp_path / "config.yaml"
    config.write_text(
        "# first reason for this shape\n"
        "# second reason for this shape\n"
        "# third reason for this shape\n"
        "# fourth reason for this shape\n"
        "# fifth reason for this shape\n"
        "key: value\n"
    )
    subprocess.run(["git", "add", "config.yaml"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", "init"],
        cwd=tmp_path,
        check=True,
    )
    with config.open("a") as handle:
        handle.write("new_key: value\n")

    result = subprocess.run(
        ["sh", str(_BIN_WRAPPER), "scan"], cwd=tmp_path, capture_output=True, text=True
    )

    assert result.returncode == 0
    assert "config.yaml" not in result.stdout + result.stderr


def test_scan_ignores_a_deleted_tracked_file_but_still_reports_an_untracked_violation(tmp_path):
    _init_repo_with_a_commit(tmp_path)
    (tmp_path / "committed.py").unlink()
    (tmp_path / "bad.py").write_text('def test_x():\n    """a docstring"""\n')

    result = subprocess.run(
        ["sh", str(_BIN_WRAPPER), "scan"], cwd=tmp_path, capture_output=True, text=True
    )

    assert result.returncode == 3
    assert "bad.py" in result.stdout + result.stderr
    assert "committed.py" not in result.stdout + result.stderr
    assert "No such file" not in result.stdout + result.stderr


def test_scan_pathspec_is_not_shell_glob_expanded_against_the_repo_root(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", "init"],
        cwd=tmp_path,
        check=True,
    )
    # A top-level match for one glob in the pathspec (top.py) sits alongside
    # a match nested in a subdirectory (sub/bad.py). If the shell expands
    # the pathspec's *.py against the cwd before git ever sees it, only the
    # top-level match survives and the nested violation goes unreported.
    (tmp_path / "top.py").write_text("def add(a, b):\n    return a + b\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "bad.py").write_text('def test_x():\n    """a docstring"""\n')

    result = subprocess.run(
        ["sh", str(_BIN_WRAPPER), "scan"], cwd=tmp_path, capture_output=True, text=True
    )

    assert result.returncode == 3
    assert "bad.py" in result.stdout + result.stderr
