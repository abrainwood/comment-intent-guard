import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = (ROOT / "comment_intent_guard.py").read_text()
MERGE = 'spans[-1] = (prev_kind, prev_start, li, f"{prev_content}\\n{content}", None)'
COND = 'if is_doc and is_leading and spans and spans[-1][0] == "doc" and spans[-1][2] + 1 == li:'
MUTANTS = {
    "drop_first_char_prev": (MERGE, MERGE.replace("{prev_content}", "{prev_content[1:]}")),
    "drop_last_char_prev": (MERGE, MERGE.replace("{prev_content}", "{prev_content[:-1]}")),
    "drop_first_char_new_row": (MERGE, MERGE.replace("{content}", "{content[1:]}")),
    "keep_close_col": (MERGE, MERGE.replace("None)", "_prev_close_col)")),
    "start_row_is_prev_end": (MERGE, MERGE.replace("prev_start, li", "_prev_end, li")),
    "start_row_plus_one": (MERGE, MERGE.replace("prev_start, li", "prev_start + 1, li")),
    "end_row_plus_one": (MERGE, MERGE.replace("prev_start, li", "prev_start, li + 1")),
    "extra_space_in_join": (MERGE, MERGE.replace("\\n{content}", "\\n {content}")),
    "prev_content_stripped": (MERGE, MERGE.replace("{prev_content}", "{prev_content.strip()}")),
    "prev_content_plus_close": (MERGE, MERGE.replace("{prev_content}", "{prev_content}*/")),
    "merge_on_prev_start_row": (COND, COND.replace("spans[-1][2] + 1", "spans[-1][1] + 1")),
    "never_merge_after_block": (COND, COND.replace("== li:", "== li and spans[-1][4] is None:")),
    "drop_is_leading": (COND, COND.replace("is_doc and is_leading", "is_doc")),
}

DIRECT = {
    "/** a */\n///x\n": [("doc", 0, 1, "* a \nx", None)],
    "/** a */ junk\n///x\n": [("doc", 0, 1, "* a \nx", None)],
    "/** d\n */\n/// doc\n": [("doc", 0, 2, "* d\n \n doc", None)],
}


def load(path):
    spec = importlib.util.spec_from_file_location("cig_mut_" + path.parent.name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def old_ok(lines, spans):
    for _k, s, e, content, cc in spans:
        if not 0 <= s <= e < len(lines):
            return False
        parts = content.split("\n")
        if cc is not None:
            if not (0 <= cc <= len(lines[e]) and lines[e].startswith("*/", cc) and lines[e][:cc].endswith(parts[-1])):
                return False
            if len(parts) > 1 and not lines[s].endswith(parts[0]):
                return False
        else:
            if len(parts) != e - s + 1 or not all(lines[s + k].endswith(p) for k, p in enumerate(parts)):
                return False
    return True


def new_ok(lines, spans):
    for _k, s, e, content, cc in spans:
        if not 0 <= s <= e < len(lines):
            return False
        parts = content.split("\n")
        if cc is not None:
            if not (0 <= cc <= len(lines[e]) and lines[e].startswith("*/", cc) and lines[e][:cc].endswith(parts[-1])):
                return False
            if len(parts) > 1 and not lines[s].endswith(parts[0]):
                return False
        else:
            if len(parts) != e - s + 1:
                return False
            for k, p in enumerate(parts):
                line = lines[s + k]
                if not (line.endswith(p) or (p + "*/") in line):
                    return False
    return True


def main():
    sys.path.insert(0, str(ROOT / "tests"))
    import test_csharp_analyser as t
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    corpus = [x for seed in (t._CSHARP_SOUP_SEED, 1) for x in t._csharp_soup_cases(seed, n)]
    print(f"{'mutant':28} oldSoup newSoup direct fullSuite")
    for name, (old, new) in MUTANTS.items():
        assert SRC.count(old) == 1, name
        tmp = Path(tempfile.mkdtemp(dir=os.environ.get("TMPDIR")))
        shutil.copytree(ROOT / "tests", tmp / "tests", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(ROOT / "pytest.ini", tmp / "pytest.ini")
        (tmp / "comment_intent_guard.py").write_text(SRC.replace(old, new))
        m = load(tmp / "comment_intent_guard.py")
        old_k = new_k = 0
        for text in corpus:
            try:
                spans = m._csharp_lex(text)[0]
            except Exception:
                old_k += 1
                new_k += 1
                continue
            lines = text.split("\n")
            old_k += not old_ok(lines, spans)
            new_k += not new_ok(lines, spans)
        direct_k = sum(m._csharp_lex(x)[0] != exp or not new_ok(x.split("\n"), m._csharp_lex(x)[0]) for x, exp in DIRECT.items())
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_csharp_analyser.py",
             "tests/test_csharp_golden_fixtures.py", "tests/test_comment_intent_guard.py"],
            cwd=tmp, capture_output=True, text=True)
        summary = r.stdout.strip().splitlines()[-1]
        print(f"{name:28} {old_k:7} {new_k:7} {direct_k:6}/3  {summary}")
        shutil.rmtree(tmp)


main()
