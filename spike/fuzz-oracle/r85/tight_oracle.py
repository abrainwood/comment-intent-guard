import random
import sys
import os
import shutil
import tempfile
from pathlib import Path

here = Path(__file__).resolve().parent
src = (here / "mutants.py").read_text().replace("\n\nmain()\n", "\n")
ns = {"__file__": str(here / "mutants.py"), "__name__": "mh"}
exec(compile(src, "mutants.py", "exec"), ns)
sys.path.insert(0, str(ns["ROOT"] / "tests"))
import test_csharp_analyser as t


def tight_ok(lines, spans):
    for _k, s, e, content, cc in spans:
        if not 0 <= s <= e < len(lines):
            return False
        parts = content.split("\n")
        if cc is not None:
            if not ns["new_ok"](lines, [(_k, s, e, content, cc)]):
                return False
            continue
        if len(parts) != e - s + 1:
            return False
        for k, p in enumerate(parts):
            line = lines[s + k]
            if not (line.endswith(p) or ("/*" + p + "*/") in line or line.startswith(p + "*/")):
                return False
    return True


base = ns["load"](ns["ROOT"] / "comment_intent_guard.py")
n = int(sys.argv[1]) if len(sys.argv) > 1 else 200000
fp = 0
for seed in (t._CSHARP_SOUP_SEED, 1):
    for x in t._csharp_soup_cases(seed, n):
        fp += not tight_ok(x.split("\n"), base._csharp_lex(x)[0])
print("tight-oracle false positives on soup seeds 20261005+1 x", n, "=", fp)
ATOMS = ["/** a */", "/** bc */", "/** d\n */", "/**e\n*f */", "///x", "/// y", "\n", " junk", "z;", " ", "/*q*/"]
rng = random.Random(7)
corpus = ["".join(rng.choice(ATOMS) for _ in range(rng.randint(2, 12))) for _ in range(20000)]
print("tight FP merge-heavy:", sum(not tight_ok(c.split("\n"), base._csharp_lex(c)[0]) for c in corpus))
for name in ("drop_first_char_prev", "drop_first_char_new_row", "prev_content_plus_close"):
    old, new = ns["MUTANTS"][name]
    tmp = Path(tempfile.mkdtemp(dir=os.environ.get("TMPDIR")))
    (tmp / "comment_intent_guard.py").write_text(ns["SRC"].replace(old, new))
    m = ns["load"](tmp / "comment_intent_guard.py")
    print(name, "tight kills:", sum(not tight_ok(c.split("\n"), m._csharp_lex(c)[0]) for c in corpus),
          "new kills:", sum(not ns["new_ok"](c.split("\n"), m._csharp_lex(c)[0]) for c in corpus))
    shutil.rmtree(tmp)
