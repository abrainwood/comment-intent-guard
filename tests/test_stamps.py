import importlib.util
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_STAMPS_PATH = _REPO_ROOT / "hooks" / "stamps.py"


def _import_stamps():
    spec = importlib.util.spec_from_file_location("stamps", _STAMPS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_restamping_the_oldest_session_protects_it_from_eviction(tmp_path):
    module = _import_stamps()
    path = str(tmp_path / "bash_backstop_stamps.json")
    stamps = {}
    for n in range(module.guard.MAX_TRACKED_SESSIONS):
        module.save_stamps(path, f"session-{n}", n, stamps)

    module.save_stamps(path, "session-0", 1_000, stamps)
    module.save_stamps(path, "session-extra", 1_001, stamps)

    assert "session-0" in stamps
    assert "session-1" not in stamps


def test_load_stamps_warns_with_the_bash_backstop_prefix_on_a_corrupt_file(tmp_path, capsys):
    module = _import_stamps()
    corrupt = tmp_path / "bash_backstop_stamps.json"
    corrupt.write_text("not json")

    result = module.load_stamps(str(corrupt))

    assert result == {}
    err = capsys.readouterr().err
    assert "bash_backstop:" in err
    assert "comment_intent_guard:" not in err
