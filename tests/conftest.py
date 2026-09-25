import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_INIT_SH = _REPO_ROOT / "init.sh"


@pytest.fixture(scope="session")
def git_repo_template(tmp_path_factory):
    template = tmp_path_factory.mktemp("git_template")
    subprocess.run(["git", "init", "-q"], cwd=template, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=template, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=template, check=True)
    subprocess.run(["git", "config", "maintenance.auto", "false"], cwd=template, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-q", "-m", "init"], cwd=template, check=True)
    return template


@pytest.fixture
def git_repo(tmp_path, git_repo_template):
    repo = tmp_path / "repo"
    shutil.copytree(git_repo_template, repo)
    return repo


@pytest.fixture(scope="session")
def initialised_repo_template(tmp_path_factory, git_repo_template):
    template = tmp_path_factory.mktemp("initialised_repo_template") / "repo"
    shutil.copytree(git_repo_template, template)
    subprocess.run(["bash", str(_INIT_SH)], cwd=template, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=template, check=True)
    guard_env = {**os.environ, "COMMENT_INTENT_GUARD": str(_REPO_ROOT / "comment_intent_guard.py")}
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=template, check=True, env=guard_env)
    return template


@pytest.fixture
def initialised_repo(tmp_path, initialised_repo_template):
    repo = tmp_path / "repo"
    shutil.copytree(initialised_repo_template, repo)
    return repo
