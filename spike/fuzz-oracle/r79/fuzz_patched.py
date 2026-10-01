import importlib.util, os, random, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
b = load("branch_guard", os.path.join(ROOT, "comment_intent_guard.py"))
p = load("patched_guard", os.path.join(HERE, "patched_guard.py"))
ATOMS = ['$', '$$', '@', '"', '"""', '{', '}', '{{', '}}', '\\', "'", '\n', '\r\n', '//', '/*', '*/',
         '#', '\n#', '\n #if ', 'a', ' ', 'x', ';', '///', '$@"', '@$"', '$"', '$$"""', '$"""', "'\\''", '"\\""']
diffs = 0
for seed in range(1, 5):
    rng = random.Random(seed)
    for _ in range(5000):
        t = "".join(rng.choice(ATOMS) for _ in range(rng.randint(1, 40)))
        if b._csharp_lex(t) != p._csharp_lex(t):
            diffs += 1
            if diffs < 5: print("DIFF", repr(t))
print("patched vs branch diffs:", diffs)
