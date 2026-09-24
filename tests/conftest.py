import shutil
import subprocess

import pytest


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
