import importlib.util, os, random, subprocess, sys, shutil, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SRC = open(os.path.join(ROOT, "comment_intent_guard.py")).read()

MUTANTS = {
    "H_no_eol_stop": ('            if not verbatim and text[i] == "\\n":\n                stack.pop()\n                continue\n            opened', '            opened'),
    "S_no_eol_stop": ('            if not verbatim and ch == "\\n":\n                stack.pop()\n                continue\n', ''),
    "S_no_double_open": ('            if ch == "{" and i + 1 < n and text[i + 1] == "{":\n                i += 2\n                continue\n', ''),
    "RH_no_depth_inc": ('                frame[1] += 1\n            elif text[i] == "}":\n                frame[1] -= 1', '                pass\n            elif text[i] == "}":\n                frame[1] -= 1'),
    "S_no_backslash": ('            if not verbatim and ch == "\\\\" and i + 1 < n:\n                i += 2\n                continue\n', ''),
    "S_verbatim_dq": ('if verbatim and i + 1 < n and text[i + 1] == \'"\':', 'if False:'),
    "H_no_depth": ('            if text[i] == "{":\n                frame[2] += 1\n            elif text[i] == "}":\n                frame[2] -= 1\n                if frame[2] == 0:\n                    i += 1', '            if text[i] == "}":\n                frame[2] -= 1\n                if frame[2] == 0:\n                    i += 1'),
    "H_inherit_verbatim_false": ('stack.append(["H", verbatim, 1])', 'stack.append(["H", False, 1])'),
    "RH_close_run_1": ('while close_run < brace_count and i + close_run', 'while False and i + close_run'),
    "R_brace_ge": ('if brace_run >= dollar_run:', 'if brace_run > dollar_run:'),
    "R_quote_ge": ('if close_run >= quote_run:\n                    i += close_run\n                    stack.pop()', 'if close_run > quote_run:\n                    i += close_run\n                    stack.pop()'),
    "eof_no_pop_advance": ('        if i >= n:\n            stack.pop()\n            continue', '        if i >= n:\n            return n'),
    "S_no_double_close": ('            if ch == "}" and i + 1 < n and text[i + 1] == "}":\n                i += 2\n                continue\n', ''),
    "nested_verbatim_flag_lost": ('return ("S", True, q + 2)', 'return ("S", False, q + 2)'),
    "nested_raw_dollar_1": ('return ("R", quote_run, dollar_run, q + quote_run)', 'return ("R", quote_run, 1, q + quote_run)'),
}

def load_src(name, src):
    d = tempfile.mkdtemp()
    p = os.path.join(d, name + ".py")
    open(p, "w").write(src)
    spec = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m, d

sys.setrecursionlimit(5000)
spec = importlib.util.spec_from_file_location("main_guard", os.path.join(HERE, "main_guard.py"))
main = importlib.util.module_from_spec(spec); spec.loader.exec_module(main)
ATOMS = ['$', '$$', '@', '"', '"""', '{', '}', '{{', '}}', '\\', "'", '\n', '\r\n', '//', '/*', '*/',
         '#', 'a', ' ', 'x', ';', '///', '$@"', '@$"', '$"', '$$"""', '$"""', "'\\''", '"\\""']
only = sys.argv[1:]
FULL = True
K = os.environ.get("K", "not directive_lines_do_not_recurse")
for name, (old, new) in MUTANTS.items():
    if only and name not in only: continue
    if SRC.count(old) != 1:
        print(f"{name:28s} INAPPLICABLE (target code deleted)"); continue
    msrc = SRC.replace(old, new)
    m, d = load_src("mut_" + name, msrc)
    rng = random.Random(7)
    killed_fuzz = False
    for _ in range(5000):
        t = "".join(rng.choice(ATOMS) for _ in range(rng.randint(1, 40)))
        try:
            a = main._csharp_lex(t)
        except RecursionError:
            continue
        try:
            b = m._csharp_lex(t)
        except Exception:
            killed_fuzz = True; break
        if a != b:
            killed_fuzz = True; break
    work = os.path.join(tempfile.mkdtemp(), "repo")
    shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(".git", "spike", "__pycache__"))
    open(os.path.join(work, "comment_intent_guard.py"), "w").write(msrc)
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider",
                        "tests/test_csharp_analyser.py", "-k", K] if FULL else [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", "tests/test_csharp_analyser.py", "-k",
                        "recurse or interpolat or raw or verbatim"],
                       capture_output=True, text=True, cwd=work)
    print(f"{name:28s} fuzz_killed={killed_fuzz} suite_killed={r.returncode != 0}")
