import random
import sys
from pathlib import Path

sys.argv = [sys.argv[0], "0"]
here = Path(__file__).resolve().parent
src = (here / "mutants.py").read_text().replace("\n\nmain()\n", "\n")
ns = {"__file__": str(here / "mutants.py"), "__name__": "mh"}
exec(compile(src, "mutants.py", "exec"), ns)

ATOMS = ["/** a */", "/** bc */", "/** d\n */", "/**e\n*f */", "///x", "/// y", "\n", " junk", "z;", " ", "/*q*/"]
rng = random.Random(7)
corpus = ["".join(rng.choice(ATOMS) for _ in range(rng.randint(2, 12))) for _ in range(20000)]
base = ns["load"](ns["ROOT"] / "comment_intent_guard.py")
base_merges = sum(any(s[4] is None and s[0] == "doc" and s[2] > s[1] for s in base._csharp_lex(t)[0]) for t in corpus)
base_new_fp = sum(not ns["new_ok"](t.split("\n"), base._csharp_lex(t)[0]) for t in corpus)
print(f"corpus cases with a multi-row open doc span: {base_merges}; new-oracle false positives on unmutated lexer: {base_new_fp}")
import tempfile, shutil, os
for name, (old, new) in ns["MUTANTS"].items():
    tmp = Path(tempfile.mkdtemp(dir=os.environ.get("TMPDIR")))
    (tmp / "comment_intent_guard.py").write_text(ns["SRC"].replace(old, new))
    m = ns["load"](tmp / "comment_intent_guard.py")
    differs = sum(m._csharp_lex(t)[0] != base._csharp_lex(t)[0] for t in corpus)
    killed = sum(not ns["new_ok"](t.split("\n"), m._csharp_lex(t)[0]) for t in corpus)
    print(f"{name:28} outputs-differ={differs:6} new-oracle-kills={killed:6}")
    shutil.rmtree(tmp)
