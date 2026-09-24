import shutil
import subprocess
import tempfile

import pytest

_TEMPLATE_DIR = None


def git_repo_template_dir():
    global _TEMPLATE_DIR
    if _TEMPLATE_DIR is None:
        template = tempfile.mkdtemp(prefix="comment_intent_guard_git_template_")
        subprocess.run(["git", "init", "-q"], cwd=template, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=template, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=template, check=True)
        subprocess.run(["git", "config", "maintenance.auto", "false"], cwd=template, check=True)
        subprocess.run(["git", "commit", "--allow-empty", "-q", "-m", "init"], cwd=template, check=True)
        _TEMPLATE_DIR = template
    return _TEMPLATE_DIR


def ignore_git_lock_files(directory, names):
    return [name for name in names if name.endswith(".lock")]


@pytest.fixture(scope="session")
def git_repo_template():
    return git_repo_template_dir()


@pytest.fixture
def git_repo(tmp_path, git_repo_template):
    repo = tmp_path / "repo"
    shutil.copytree(git_repo_template, repo, ignore=ignore_git_lock_files)
    return repo
