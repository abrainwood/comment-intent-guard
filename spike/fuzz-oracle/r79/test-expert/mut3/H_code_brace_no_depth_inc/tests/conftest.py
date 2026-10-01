import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_INIT_SH = _REPO_ROOT / "init.sh"


def _run(args, cwd, env=None):
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True)
    assert result.returncode == 0, f"{' '.join(args)} failed: {result.stderr}"
    return result


def _copy_template(template, tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(template, repo)
    return repo


@pytest.fixture(scope="session")
def git_repo_template(tmp_path_factory):
    template = tmp_path_factory.mktemp("git_template")
    _run(["git", "init", "-q"], cwd=template)
    _run(["git", "config", "user.email", "test@example.com"], cwd=template)
    _run(["git", "config", "user.name", "Test"], cwd=template)
    _run(["git", "config", "maintenance.auto", "false"], cwd=template)
    _run(["git", "config", "commit.gpgsign", "false"], cwd=template)
    _run(["git", "commit", "--allow-empty", "-q", "-m", "init"], cwd=template)
    return template


@pytest.fixture
def git_repo(tmp_path, git_repo_template):
    return _copy_template(git_repo_template, tmp_path)


@pytest.fixture(scope="session")
def initialised_repo_template(tmp_path_factory, git_repo_template):
    template = _copy_template(git_repo_template, tmp_path_factory.mktemp("initialised_repo_template"))
    _run(["bash", str(_INIT_SH)], cwd=template)
    _run(["git", "add", "."], cwd=template)
    guard_env = {**os.environ, "COMMENT_INTENT_GUARD": str(_REPO_ROOT / "comment_intent_guard.py")}
    _run(["git", "commit", "-q", "-m", "init"], cwd=template, env=guard_env)
    return template


@pytest.fixture
def initialised_repo(tmp_path, initialised_repo_template):
    return _copy_template(initialised_repo_template, tmp_path)
