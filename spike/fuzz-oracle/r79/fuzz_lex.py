import importlib.util, random, sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

main = load("main_guard", os.path.join(HERE, "main_guard.py"))
branch = load("branch_guard", os.path.join(ROOT, "comment_intent_guard.py"))

ATOMS = ['$', '$$', '@', '"', '"""', '{', '}', '{{', '}}', '\\', "'", '\n', '\r\n', '//', '/*', '*/',
         '#', 'a', ' ', 'x', ';', '///', '$@"', '@$"', '$"', '$$"""', '$"""', "'\\''", '"\\""']

def gen(rng):
    return "".join(rng.choice(ATOMS) for _ in range(rng.randint(1, 40)))

def main_run():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
    rng = random.Random(seed)
    diffs = 0
    crashes = 0
    for k in range(count):
        t = gen(rng)
        try:
            a = main._csharp_lex(t)
        except RecursionError:
            crashes += 1
            continue
        b = branch._csharp_lex(t)
        if a != b:
            diffs += 1
            if diffs <= 5:
                print("DIFF", repr(t)); print(" main  ", a); print(" branch", b)
        for j in range(len(t)):
            try:
                x = main._csharp_try_skip_literal(t, j)
            except RecursionError:
                continue
            y = branch._csharp_try_skip_literal(t, j)
            if x != y:
                diffs += 1
                if diffs <= 5:
                    print("DIFF try_skip", repr(t), j, x, y)
    print(f"seed={seed} cases={count} diffs={diffs} main_recursion_crashes={crashes}")

main_run()
