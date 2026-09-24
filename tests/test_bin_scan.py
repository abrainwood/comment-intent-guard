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
