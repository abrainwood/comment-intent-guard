import importlib.util
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_STAMPS_PATH = _REPO_ROOT / "hooks" / "stamps.py"


def _import_stamps():
    spec = importlib.util.spec_from_file_location("stamps", _STAMPS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_stamps_warns_with_the_bash_backstop_prefix_on_a_corrupt_file(tmp_path, capsys):
    module = _import_stamps()
    corrupt = tmp_path / "bash_backstop_stamps.json"
    corrupt.write_text("not json")

    result = module.load_stamps(str(corrupt))

    assert result == {}
    err = capsys.readouterr().err
    assert "bash_backstop:" in err
    assert "comment_intent_guard:" not in err
