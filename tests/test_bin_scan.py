import importlib.util
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BIN_WRAPPER = _REPO_ROOT / "bin" / "comment-intent-guard"
_MODULE_PATH = _REPO_ROOT / "comment_intent_guard.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("bin_scan_guard", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load_module()


def _init_repo_with_a_commit(repo_dir):
    subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)
    _commit_a_file(repo_dir)


def _commit_a_file(repo_dir):
    (repo_dir / "committed.py").write_text("def add(a, b):\n    return a + b\n")
    subprocess.run(["git", "add", "committed.py"], cwd=repo_dir, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", "init"],
        cwd=repo_dir,
        check=True,
    )


def test_scan_outside_a_git_repo_exits_2_with_a_message(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    exit_code = guard._scan_main()

    assert exit_code == 2
    assert "git" in capsys.readouterr().err.lower()


def test_scan_on_a_clean_repo_exits_0_with_nothing_uncommitted(git_repo, monkeypatch, capsys):
    _commit_a_file(git_repo)
    monkeypatch.chdir(git_repo)

    exit_code = guard._scan_main()

    assert exit_code == guard._EXIT_CLEAN
    assert "nothing uncommitted" in capsys.readouterr().out


def test_scan_reports_an_untracked_violating_python_file_and_exits_3(git_repo, monkeypatch, capsys):
    _commit_a_file(git_repo)
    (git_repo / "bad.py").write_text('def test_x():\n    """a docstring"""\n')
    monkeypatch.chdir(git_repo)

    exit_code = guard._scan_main()

    out = capsys.readouterr()
    assert exit_code == guard._EXIT_BRIGHT_LINE
    assert "bad.py" in out.out + out.err


def test_scan_does_not_flag_a_pre_existing_advisory_touched_only_by_a_clean_append(
    tmp_path, monkeypatch, capsys
):
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
    monkeypatch.chdir(tmp_path)
    pre_append_exit_code = guard._cli_main(["--all", "config.yaml"])
    capsys.readouterr()
    assert pre_append_exit_code == guard._EXIT_ADVISORY

    with config.open("a") as handle:
        handle.write("new_key: value\n")

    exit_code = guard._scan_main()

    out = capsys.readouterr()
    assert exit_code == guard._EXIT_CLEAN
    assert "config.yaml" not in out.out + out.err


def test_scan_ignores_a_deleted_tracked_file_but_still_reports_an_untracked_violation(
    git_repo, monkeypatch, capsys
):
    _commit_a_file(git_repo)
    (git_repo / "committed.py").unlink()
    (git_repo / "bad.py").write_text('def test_x():\n    """a docstring"""\n')
    monkeypatch.chdir(git_repo)

    exit_code = guard._scan_main()

    out = capsys.readouterr()
    combined = out.out + out.err
    assert exit_code == guard._EXIT_BRIGHT_LINE
    assert "bad.py" in combined
    assert "committed.py" not in combined
    assert "No such file" not in combined


def test_scan_reports_a_violation_nested_in_a_subdirectory_alongside_a_top_level_match(
    tmp_path, monkeypatch, capsys
):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", "init"],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / "top.py").write_text("def add(a, b):\n    return a + b\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "bad.py").write_text('def test_x():\n    """a docstring"""\n')
    monkeypatch.chdir(tmp_path)

    exit_code = guard._scan_main()

    out = capsys.readouterr()
    assert exit_code == guard._EXIT_BRIGHT_LINE
    assert "bad.py" in out.out + out.err


def test_scan_handles_a_non_ascii_untracked_filename(git_repo, monkeypatch, capsys):
    _commit_a_file(git_repo)
    (git_repo / "café.py").write_text('def test_x():\n    """a docstring"""\n')
    monkeypatch.chdir(git_repo)

    exit_code = guard._scan_main()

    out = capsys.readouterr()
    assert exit_code == guard._EXIT_BRIGHT_LINE
    assert "café.py" in out.out + out.err


def test_scan_on_an_unborn_repo_reports_an_untracked_violation_and_exits_3(tmp_path, monkeypatch, capsys):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "bad.py").write_text('def test_x():\n    """a docstring"""\n')
    monkeypatch.chdir(tmp_path)

    exit_code = guard._scan_main()

    out = capsys.readouterr()
    assert exit_code == guard._EXIT_BRIGHT_LINE
    assert "bad.py" in out.out + out.err


def test_scan_on_an_unborn_empty_repo_exits_0_with_nothing_uncommitted(tmp_path, monkeypatch, capsys):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)

    exit_code = guard._scan_main()

    assert exit_code == guard._EXIT_CLEAN
    assert "nothing uncommitted" in capsys.readouterr().out


def test_scan_on_an_unborn_repo_reports_a_staged_violation_and_exits_3(tmp_path, monkeypatch, capsys):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "bad.py").write_text('def test_x():\n    """a docstring"""\n')
    subprocess.run(["git", "add", "bad.py"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)

    exit_code = guard._scan_main()

    out = capsys.readouterr()
    assert exit_code == guard._EXIT_BRIGHT_LINE
    assert "bad.py" in out.out + out.err


def test_scan_reports_an_untracked_violation_in_a_dash_leading_filename(git_repo, monkeypatch, capsys):
    _commit_a_file(git_repo)
    (git_repo / "-x.py").write_text('def test_x():\n    """a docstring"""\n')
    monkeypatch.chdir(git_repo)

    exit_code = guard._scan_main()

    out = capsys.readouterr()
    assert exit_code == guard._EXIT_BRIGHT_LINE
    assert "-x.py" in out.out + out.err


def test_scan_reports_the_higher_of_two_exit_codes_when_both_tracked_and_untracked_have_findings(
    tmp_path, monkeypatch, capsys
):
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
    config.write_text(
        "# first reason for this shape\n"
        "# second reason for this shape\n"
        "# third reason for this shape\n"
        "# fourth reason for this shape\n"
        "# fifth reason for this shape\n"
        "# sixth reason for this shape\n"
        "key: value\n"
    )
    (tmp_path / "bad.py").write_text('def test_x():\n    """a docstring"""\n')
    monkeypatch.chdir(tmp_path)

    exit_code = guard._scan_main()

    out = capsys.readouterr()
    combined = out.out + out.err
    assert exit_code == guard._EXIT_BRIGHT_LINE
    assert "bad.py" in combined
    assert "config.yaml" in combined


def test_scan_exits_4_and_still_prints_blocked_lines_when_a_file_is_unreadable(git_repo, monkeypatch, capsys):
    _commit_a_file(git_repo)
    unreadable = git_repo / "unreadable.py"
    unreadable.write_text("x = 1\n")
    unreadable.chmod(0o000)
    (git_repo / "bad.py").write_text('def test_x():\n    """a docstring"""\n')
    monkeypatch.chdir(git_repo)

    try:
        exit_code = guard._scan_main()
    finally:
        unreadable.chmod(0o644)

    out = capsys.readouterr()
    combined = out.out + out.err
    assert exit_code == guard._EXIT_INTERNAL_ERROR
    assert "BLOCKED" in combined
    assert "bad.py" in combined


def test_scan_reports_an_untracked_violation_in_a_filename_with_a_space(git_repo, monkeypatch, capsys):
    _commit_a_file(git_repo)
    (git_repo / "bad file.py").write_text('def test_x():\n    """a docstring"""\n')
    monkeypatch.chdir(git_repo)

    exit_code = guard._scan_main()

    out = capsys.readouterr()
    assert exit_code == guard._EXIT_BRIGHT_LINE
    assert "bad file.py" in out.out + out.err


def test_scan_reports_a_tracked_violation_in_a_filename_with_a_space(git_repo, monkeypatch, capsys):
    _commit_a_file(git_repo)
    tracked = git_repo / "bad file.py"
    tracked.write_text("x = 1\n")
    subprocess.run(["git", "add", "bad file.py"], cwd=git_repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", "add"],
        cwd=git_repo,
        check=True,
    )
    tracked.write_text('def test_x():\n    """a docstring"""\n')
    monkeypatch.chdir(git_repo)

    exit_code = guard._scan_main()

    out = capsys.readouterr()
    assert exit_code == guard._EXIT_BRIGHT_LINE
    assert "bad file.py" in out.out + out.err


def test_scan_of_a_tracked_violation_never_calls_git_status(git_repo, monkeypatch, capsys):
    _commit_a_file(git_repo)
    tracked = git_repo / "bad.py"
    tracked.write_text("x = 1\n")
    subprocess.run(["git", "add", "bad.py"], cwd=git_repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", "add"],
        cwd=git_repo,
        check=True,
    )
    tracked.write_text('def test_x():\n    """a docstring"""\n')
    monkeypatch.chdir(git_repo)

    real_run = subprocess.run
    calls = []

    def _counting_run(args, **kwargs):
        calls.append(args)
        return real_run(args, **kwargs)

    monkeypatch.setattr(guard.subprocess, "run", _counting_run)

    exit_code = guard._scan_main()

    assert exit_code == guard._EXIT_BRIGHT_LINE
    status_calls = [call for call in calls if "status" in call]
    assert len(status_calls) == 0


def test_scan_reports_a_filename_containing_a_newline_once_and_exits_3(git_repo, monkeypatch, capsys):
    _commit_a_file(git_repo)
    (git_repo / "bad\nname.py").write_text('def test_x():\n    """a docstring"""\n')
    monkeypatch.chdir(git_repo)

    exit_code = guard._scan_main()

    out = capsys.readouterr()
    combined = out.out + out.err
    assert exit_code == guard._EXIT_BRIGHT_LINE
    assert "could not read" not in combined
    assert combined.count("a docstring") == 1


def test_scan_on_an_unborn_repo_skips_a_staged_file_deleted_from_the_worktree(tmp_path, monkeypatch, capsys):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    staged = tmp_path / "bad.py"
    staged.write_text('def test_x():\n    """a docstring"""\n')
    subprocess.run(["git", "add", "bad.py"], cwd=tmp_path, check=True)
    staged.unlink()
    monkeypatch.chdir(tmp_path)

    exit_code = guard._scan_main()

    out = capsys.readouterr()
    assert exit_code == guard._EXIT_CLEAN
    assert "nothing uncommitted" in out.out
    assert "could not read" not in out.out + out.err


def test_scan_from_a_subdirectory_reports_a_repo_relative_path(git_repo, monkeypatch, capsys):
    _commit_a_file(git_repo)
    sub = git_repo / "sub"
    sub.mkdir()
    (sub / "t.py").write_text('def test_x():\n    """a docstring"""\n')
    monkeypatch.chdir(sub)

    exit_code = guard._scan_main()

    out = capsys.readouterr()
    combined = out.out + out.err
    assert exit_code == guard._EXIT_BRIGHT_LINE
    assert "sub/t.py:" in combined
    assert str(git_repo) not in combined


def test_scan_ignores_a_txt_file(git_repo, monkeypatch, capsys):
    _commit_a_file(git_repo)
    (git_repo / "notes.txt").write_text('"""a docstring"""\nnot code, should be ignored\n')
    monkeypatch.chdir(git_repo)

    exit_code = guard._scan_main()

    out = capsys.readouterr()
    assert exit_code == guard._EXIT_CLEAN
    assert "notes.txt" not in out.out + out.err


def test_main_scan_rejects_extra_arguments(monkeypatch, capsys):
    monkeypatch.setattr(guard.sys, "argv", ["comment_intent_guard", "--scan", "junk"])

    with pytest.raises(SystemExit) as exc_info:
        guard.main()

    assert exc_info.value.code == 2
    assert "usage" in capsys.readouterr().err.lower()


def test_scan_delegates_listing_entirely_to_the_python_scan_mode(tmp_path, git_repo):
    plugin_root = tmp_path / "plugin"
    (plugin_root / "bin").mkdir(parents=True)
    wrapper_copy = plugin_root / "bin" / "comment-intent-guard"
    wrapper_copy.write_bytes(_BIN_WRAPPER.read_bytes())
    wrapper_copy.chmod(0o755)
    (plugin_root / "comment_intent_guard.py").write_text(
        "import sys\nprint('ARGV:' + ' '.join(sys.argv[1:]))\nsys.exit(0)\n"
    )

    _commit_a_file(git_repo)

    result = subprocess.run(
        ["sh", str(wrapper_copy), "scan"], cwd=git_repo, capture_output=True, text=True
    )

    assert result.stdout.strip() == "ARGV:--scan"


def test_scan_forwards_its_own_extra_arguments_after_the_internal_scan_flag(tmp_path, git_repo):
    plugin_root = tmp_path / "plugin"
    (plugin_root / "bin").mkdir(parents=True)
    wrapper_copy = plugin_root / "bin" / "comment-intent-guard"
    wrapper_copy.write_bytes(_BIN_WRAPPER.read_bytes())
    wrapper_copy.chmod(0o755)
    (plugin_root / "comment_intent_guard.py").write_text(
        "import sys\nprint('ARGV:' + ' '.join(sys.argv[1:]))\nsys.exit(0)\n"
    )

    _commit_a_file(git_repo)

    result = subprocess.run(
        ["sh", str(wrapper_copy), "scan", "junk"], cwd=git_repo, capture_output=True, text=True
    )

    assert result.stdout.strip() == "ARGV:--scan junk"


def test_check_subcommand_rejects_the_internal_scan_flag(tmp_path):
    result = subprocess.run(
        ["sh", str(_BIN_WRAPPER), "check", "--scan"], cwd=tmp_path, capture_output=True, text=True
    )

    assert result.returncode == 2
    assert "usage" in (result.stdout + result.stderr).lower()
