import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_GATE_YML = _REPO_ROOT / ".github" / "workflows" / "gate.yml"


def _load_gate():
    # YAML parses `on:` as the boolean key True unless quoted; PyYAML's
    # default loader does this for the bare `on` scalar.
    return yaml.safe_load(_GATE_YML.read_text())


def test_gate_yml_is_a_reusable_workflow_with_a_python_version_input_defaulting_to_3_12():
    workflow = _load_gate()

    triggers = workflow.get("on") or workflow.get(True)
    assert "workflow_call" in triggers

    inputs = triggers["workflow_call"]["inputs"]
    assert inputs["python-version"]["default"] == "3.12"
    assert workflow["permissions"] == {"contents": "read"}


def _run_step_script(workflow):
    jobs = workflow["jobs"]
    (job,) = jobs.values()
    (run_step,) = [step for step in job["steps"] if "run" in step]
    return run_step["run"]


def _bash_with_mapfile():
    for candidate in ("/opt/homebrew/bin/bash", "/usr/local/bin/bash", shutil.which("bash")):
        if candidate and Path(candidate).exists() and subprocess.run(
            [candidate, "-c", "type mapfile"], capture_output=True
        ).returncode == 0:
            return candidate
    return None


_BASH = _bash_with_mapfile()


@pytest.fixture(scope="session")
def gate_test_repo_template(tmp_path_factory):
    template = tmp_path_factory.mktemp("gate_test_repo_template")
    subprocess.run(["git", "init", "-q"], cwd=template, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=template, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=template, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=template, check=True)
    subprocess.run(["git", "config", "maintenance.auto", "false"], cwd=template, check=True)
    (template / "base.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "."], cwd=template, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=template, check=True)
    subprocess.run(["git", "branch", "origin/main"], cwd=template, check=True)
    (template / "thing.py").write_text("y = 2\n")
    subprocess.run(["git", "add", "."], cwd=template, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "change"], cwd=template, check=True)
    return template


def _init_gate_test_repo(tmp_path, template):
    repo = tmp_path / "repo"
    shutil.copytree(template, repo)
    checkout_dir = repo / ".comment-intent-guard-checkout"
    checkout_dir.mkdir()
    return repo, checkout_dir / "comment_intent_guard.py"


def _run_gate_step_with_stub_guard(tmp_path, template, stub_body):
    repo, stub_path = _init_gate_test_repo(tmp_path, template)
    stub_path.write_text(stub_body)
    script = _run_step_script(_load_gate())
    env = dict(os.environ, BASE_REF="main", PATHS="*.py")
    return subprocess.run(
        [_BASH, "-c", script], cwd=repo, env=env, capture_output=True, text=True, timeout=30,
    )


def _stub_body_exiting(code):
    return f'import sys\nprint("stub output")\nsys.exit({code})\n'


@pytest.mark.skipif(_BASH is None, reason="no bash with mapfile support found on PATH")
@pytest.mark.parametrize(
    "stub_exit_code, expected_step_exit_code",
    [(0, 0), (1, 0), (3, 1), (4, 1), (2, 1)],
    ids=["clean", "advisory", "bright_line", "internal_error", "unexpected_code"],
)
def test_gate_run_step_maps_guard_exit_code_to_build_result(
    tmp_path, gate_test_repo_template, stub_exit_code, expected_step_exit_code
):
    result = _run_gate_step_with_stub_guard(
        tmp_path, gate_test_repo_template, _stub_body_exiting(stub_exit_code)
    )

    assert result.returncode == expected_step_exit_code
    assert "stub output" in result.stdout


@pytest.mark.skipif(_BASH is None, reason="no bash with mapfile support found on PATH")
def test_gate_run_step_emits_a_warning_annotation_per_advisory_line(tmp_path, gate_test_repo_template):
    result = _run_gate_step_with_stub_guard(
        tmp_path, gate_test_repo_template, 'import sys\nprint("thing.py: msg")\nsys.exit(1)\n'
    )

    assert result.returncode == 0
    assert "::warning file=thing.py::msg" in result.stdout


def test_gate_run_step_disables_globbing_before_word_splitting_paths():
    script = _run_step_script(_load_gate())

    diff_line = next(line for line in script.splitlines() if "git diff --name-only" in line)
    set_f_index = script.index("set -f")
    diff_line_index = script.index(diff_line)

    assert set_f_index < diff_line_index
    assert "${PATHS}" not in diff_line


_TEMPLATE_YML = _REPO_ROOT / "templates" / "comment-guard.yml"


def test_caller_template_uses_gate_yml_pinned_to_a_comment_intent_guard_tag():
    template = yaml.safe_load(_TEMPLATE_YML.read_text())

    jobs = template["jobs"]
    (job,) = jobs.values()
    uses = job["uses"]

    assert uses.startswith("abrainwood/comment-intent-guard/.github/workflows/gate.yml@comment-intent-guard--v")


_CI_YML = _REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_yml_dogfoods_its_own_gate_via_local_workflow_call():
    ci = yaml.safe_load(_CI_YML.read_text())

    jobs = ci["jobs"]
    uses_entries = [job["uses"] for job in jobs.values() if "uses" in job]

    assert "./.github/workflows/gate.yml" in uses_entries

