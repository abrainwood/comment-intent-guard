import subprocess, sys, tempfile, shutil
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.argv = ["x"]; exec(compile(open(HERE / "mutate.py").read().split("only = sys.argv")[0], "m", "exec"))
for name in ["literal_row_overshoot", "close_col_plus1", "close_col_plus2", "close_col_is_end", "S_nonverbatim_ignores_newline",
             "H_nonverbatim_ignores_newline", "char_literal_newline", "doc_merge_end_plus1", "unterminated_block_eats_rest"]:
    old, new = MUTANTS[name]
    d = Path(tempfile.mkdtemp(prefix="r81s-")); (d / "comment_intent_guard.py").write_text(SRC.replace(old, new))
    out = subprocess.run([sys.executable, str(HERE / "stronger.py"), str(d)], capture_output=True, text=True)
    print(name, "->", (out.stdout or out.stderr).strip()[:300].replace(d.name, ""))
    shutil.rmtree(d)
