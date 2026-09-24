from pathlib import Path

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


def _run_step_script(workflow):
    jobs = workflow["jobs"]
    (job,) = jobs.values()
    (run_step,) = [step for step in job["steps"] if "run" in step]
    return run_step["run"]


def test_gate_run_step_handles_exit_codes_0_1_3_and_4():
    script = _run_step_script(_load_gate())

    # 0: clean, no findings - the build passes without comment.
    # 1: advisory findings only - annotate but still pass.
    # 3/4: bright-line or internal-error findings - fail the build.
    assert "0)" in script
    assert "1)" in script
    assert "3)" in script or "3|4)" in script
    assert "4)" in script or "3|4)" in script
    assert "::warning" in script


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

