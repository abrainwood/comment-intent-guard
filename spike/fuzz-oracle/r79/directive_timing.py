import importlib.util, os, time, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
mods = {"main": load("main_guard", os.path.join(HERE, "main_guard.py")),
        "branch": load("branch_guard", os.path.join(ROOT, "comment_intent_guard.py"))}
if len(sys.argv) > 1:
    mods["patched"] = load("patched_guard", sys.argv[1])
shapes = {
    "directive verbatim @\"": '#if x = @"\n',
    "directive raw \"\"\"": '#if x = """\n',
    "directive $@\"{ (issue 78)": '#if x = $@"{\n',
    "code $@\"{ (issue 78)": 'x = $@"{\n',
}
for label, line in shapes.items():
    for N in (1000, 2000):
        row = []
        for name, m in mods.items():
            t0 = time.perf_counter()
            try:
                m._csharp_lex(line * N); r = f"{time.perf_counter()-t0:6.2f}s"
            except RecursionError:
                r = " RecErr"
            row.append(f"{name}={r}")
        print(f"{label:28s} N={N:5d} " + "  ".join(row))
