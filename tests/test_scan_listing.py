import importlib.util
import os
import subprocess
import time
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parent.parent / "comment_intent_guard.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("scan_listing_guard", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load_module()


def _init_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=t",
         "commit", "-q", "--allow-empty", "-m", "init"],
        cwd=path, check=True,
    )


def _write(path, relpath, content):
    target = path / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return target


_HANGING_SLEEP_SECONDS = 5


def _write_hanging_fake_git(bin_dir):
    fake_git = bin_dir / "git"
    fake_git.write_text(f"#!/bin/sh\nexec sleep {_HANGING_SLEEP_SECONDS}\n")
    fake_git.chmod(0o755)


def _write_diff_hanging_fake_git(bin_dir):
    real_git = subprocess.run(["which", "git"], capture_output=True, text=True, check=True).stdout.strip()
    fake_git = bin_dir / "git"
    fake_git.write_text(
        "#!/bin/sh\n"
        "case \" $* \" in\n"
        f"  *' diff '*) exec sleep {_HANGING_SLEEP_SECONDS} ;;\n"
        f"  *) exec {real_git} \"$@\" ;;\n"
        "esac\n"
    )
    fake_git.chmod(0o755)


def _write_status_hanging_fake_git(bin_dir):
    real_git = subprocess.run(["which", "git"], capture_output=True, text=True, check=True).stdout.strip()
    fake_git = bin_dir / "git"
    fake_git.write_text(
        "#!/bin/sh\n"
        "case \" $* \" in\n"
        f"  *' status '*) exec sleep {_HANGING_SLEEP_SECONDS} ;;\n"
        f"  *) exec {real_git} \"$@\" ;;\n"
        "esac\n"
    )
    fake_git.chmod(0o755)


def _write_failing_fake_git(bin_dir, message="fake git failure", exit_code=128):
    fake_git = bin_dir / "git"
    fake_git.write_text(f"#!/bin/sh\necho '{message}' >&2\nexit {exit_code}\n")
    fake_git.chmod(0o755)


def _prepend_to_path(monkeypatch, bin_dir):
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def test_scan_head_sha_raises_on_git_timeout(tmp_path, monkeypatch, capsys):
    _write_hanging_fake_git(tmp_path)
    _prepend_to_path(monkeypatch, tmp_path)
    monkeypatch.setattr(guard, "_SCAN_GIT_TIMEOUT_SECONDS", 0.05)

    with pytest.raises(guard._ScanGitError):
        guard._scan_head_sha(str(tmp_path))

    assert "timed out" in capsys.readouterr().err.lower()


def test_scan_list_tracked_raises_on_git_timeout(tmp_path, monkeypatch, capsys):
    _write_hanging_fake_git(tmp_path)
    _prepend_to_path(monkeypatch, tmp_path)
    monkeypatch.setattr(guard, "_SCAN_GIT_TIMEOUT_SECONDS", 0.05)

    with pytest.raises(guard._ScanGitError):
        guard._scan_list_tracked(str(tmp_path), "HEAD")

    assert "timed out" in capsys.readouterr().err.lower()


def test_scan_list_untracked_raises_on_git_timeout(tmp_path, monkeypatch, capsys):
    _write_hanging_fake_git(tmp_path)
    _prepend_to_path(monkeypatch, tmp_path)
    monkeypatch.setattr(guard, "_SCAN_GIT_TIMEOUT_SECONDS", 0.05)

    with pytest.raises(guard._ScanGitError):
        guard._scan_list_untracked(str(tmp_path))

    assert "timed out" in capsys.readouterr().err.lower()


def test_scan_list_tracked_raises_when_git_exits_non_zero(tmp_path, monkeypatch, capsys):
    _write_failing_fake_git(tmp_path)
    _prepend_to_path(monkeypatch, tmp_path)

    with pytest.raises(guard._ScanGitError):
        guard._scan_list_tracked(str(tmp_path), "HEAD")

    assert "fake git failure" in capsys.readouterr().err


def test_scan_list_untracked_raises_when_git_exits_non_zero(tmp_path, monkeypatch, capsys):
    _write_failing_fake_git(tmp_path)
    _prepend_to_path(monkeypatch, tmp_path)

    with pytest.raises(guard._ScanGitError):
        guard._scan_list_untracked(str(tmp_path))

    assert "fake git failure" in capsys.readouterr().err


def test_scan_git_toplevel_raises_on_git_timeout(tmp_path, monkeypatch, capsys):
    _write_hanging_fake_git(tmp_path)
    _prepend_to_path(monkeypatch, tmp_path)
    monkeypatch.setattr(guard, "_SCAN_GIT_TIMEOUT_SECONDS", 0.05)

    with pytest.raises(guard._ScanGitError):
        guard._scan_git_toplevel()

    assert "timed out" in capsys.readouterr().err.lower()


def test_scan_git_toplevel_returns_none_for_a_real_non_git_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert guard._scan_git_toplevel() is None


def test_scan_head_sha_on_an_unborn_repo_returns_none_without_raising(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    assert guard._scan_head_sha(str(tmp_path)) is None


def test_scan_main_returns_4_when_tracked_listing_raises_scan_git_error(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    monkeypatch.setattr(guard, "_scan_git_toplevel", lambda: str(tmp_path))
    monkeypatch.setattr(guard, "_scan_head_sha", lambda repo_root: "deadbeef")

    def _raise(*_args, **_kwargs):
        raise guard._ScanGitError

    monkeypatch.setattr(guard, "_scan_list_tracked", _raise)
    monkeypatch.chdir(tmp_path)

    assert guard._scan_main() == 4


def test_scan_list_untracked_only_returns_pathspec_matching_files(tmp_path):
    _init_repo(tmp_path)
    _write(tmp_path, "checked.py", "x\n")
    _write(tmp_path, "notes.txt", "x\n")

    assert guard._scan_list_untracked(str(tmp_path)) == ["checked.py"]


def test_scan_list_tracked_only_returns_pathspec_matching_files(tmp_path):
    _init_repo(tmp_path)
    _write(tmp_path, "checked.py", "x\n")
    _write(tmp_path, "notes.txt", "x\n")
    subprocess.run(["git", "add", "checked.py", "notes.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", "add"],
        cwd=tmp_path, check=True,
    )
    (tmp_path / "checked.py").write_text("y\n")
    (tmp_path / "notes.txt").write_text("y\n")

    head_sha = guard._scan_head_sha(str(tmp_path))

    assert guard._scan_list_tracked(str(tmp_path), head_sha) == ["checked.py"]


def test_scan_list_tracked_excludes_a_file_dropped_from_the_index_but_still_on_disk(tmp_path):
    _init_repo(tmp_path)
    _write(tmp_path, "a.py", "x\n")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", "add"],
        cwd=tmp_path, check=True,
    )
    subprocess.run(["git", "rm", "--cached", "-q", "a.py"], cwd=tmp_path, check=True)

    head_sha = guard._scan_head_sha(str(tmp_path))

    assert guard._scan_list_tracked(str(tmp_path), head_sha) == []
    assert guard._scan_list_untracked(str(tmp_path)) == ["a.py"]


def test_check_files_with_base_batches_git_calls_and_filters_a_preexisting_finding(tmp_path, monkeypatch, capsys):
    _init_repo(tmp_path)
    preexisting_comment_run = "# one\n# two\n# three\n# four\n# five\n"
    filenames = ["a.py", "b.py", "c.py", "d.py"]
    for name in filenames:
        _write(tmp_path, name, preexisting_comment_run + "x = 1\n")
    subprocess.run(["git", "add", *filenames], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", "add"],
        cwd=tmp_path, check=True,
    )
    for name in filenames:
        _write(tmp_path, name, preexisting_comment_run + "x = 1\ny = 2\n")

    monkeypatch.chdir(tmp_path)

    real_run = subprocess.run
    calls = []

    def _counting_run(args, **kwargs):
        calls.append(args)
        return real_run(args, **kwargs)

    monkeypatch.setattr(guard.subprocess, "run", _counting_run)

    files = [str(tmp_path / name) for name in filenames]
    exit_code = guard._check_files(files, base="HEAD")

    status_calls = [call for call in calls if "status" in call]
    diff_calls = [call for call in calls if "diff" in call]
    assert len(status_calls) == 1
    assert len(diff_calls) == 1

    stdout = capsys.readouterr().out
    assert "Comment run of" not in stdout
    assert exit_code == guard._EXIT_CLEAN


def test_added_line_numbers_map_bounds_the_diff_call_by_the_configured_timeout(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    target = _write(tmp_path, "a.py", "x = 1\n")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", "add"],
        cwd=tmp_path, check=True,
    )
    _write_diff_hanging_fake_git(tmp_path)
    _prepend_to_path(monkeypatch, tmp_path)
    monkeypatch.setattr(guard, "_SCAN_GIT_TIMEOUT_SECONDS", 0.5)

    started_at = time.monotonic()
    result = guard._added_line_numbers_map("HEAD", [str(target)])
    elapsed = time.monotonic() - started_at

    assert result == {str(target): None}
    assert elapsed < _HANGING_SLEEP_SECONDS


def test_added_line_numbers_map_degrades_every_file_in_the_group_on_diff_timeout(tmp_path, monkeypatch, capsys):
    _init_repo(tmp_path)
    filenames = ["a.py", "b.py", "c.py"]
    targets = [_write(tmp_path, name, "x = 1\n") for name in filenames]
    subprocess.run(["git", "add", *filenames], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", "add"],
        cwd=tmp_path, check=True,
    )
    _write_diff_hanging_fake_git(tmp_path)
    _prepend_to_path(monkeypatch, tmp_path)
    monkeypatch.setattr(guard, "_SCAN_GIT_TIMEOUT_SECONDS", 0.5)

    result = guard._added_line_numbers_map("HEAD", [str(target) for target in targets])

    assert result == {str(target): None for target in targets}
    stderr = capsys.readouterr().err
    assert "not filtering findings" in stderr.lower()
    assert "git diff" in stderr.lower()
    for target in targets:
        assert str(target) in stderr


def test_added_line_numbers_map_degrades_every_file_when_status_times_out_before_any_diff(
    tmp_path, monkeypatch, capsys
):
    _init_repo(tmp_path)
    filenames = ["a.py", "b.py", "c.py"]
    targets = [_write(tmp_path, name, "x = 1\n") for name in filenames]
    subprocess.run(["git", "add", *filenames], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", "add"],
        cwd=tmp_path, check=True,
    )
    _write_status_hanging_fake_git(tmp_path)
    _prepend_to_path(monkeypatch, tmp_path)
    monkeypatch.setattr(guard, "_SCAN_GIT_TIMEOUT_SECONDS", 0.5)

    started_at = time.monotonic()
    result = guard._added_line_numbers_map("HEAD", [str(target) for target in targets])
    elapsed = time.monotonic() - started_at

    assert result == {str(target): None for target in targets}
    assert elapsed < _HANGING_SLEEP_SECONDS
    stderr = capsys.readouterr().err
    assert "not filtering findings" in stderr.lower()
    assert "git status" in stderr.lower()
    assert "git diff" not in stderr.lower()


def test_added_line_numbers_map_degrades_every_file_when_git_toplevel_resolution_times_out(
    tmp_path, monkeypatch, capsys
):
    _init_repo(tmp_path)
    filenames = ["a.py", "b.py", "c.py"]
    targets = [_write(tmp_path, name, "x = 1\n") for name in filenames]
    subprocess.run(["git", "add", *filenames], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", "add"],
        cwd=tmp_path, check=True,
    )
    _write_hanging_fake_git(tmp_path)
    _prepend_to_path(monkeypatch, tmp_path)
    monkeypatch.setattr(guard, "_SCAN_GIT_TIMEOUT_SECONDS", 0.05)

    result = guard._added_line_numbers_map("HEAD", [str(target) for target in targets])

    assert result == {str(target): None for target in targets}
    stderr = capsys.readouterr().err
    assert "not filtering findings" in stderr.lower()
    assert "rev-parse" in stderr.lower()
    assert str(tmp_path) in stderr
