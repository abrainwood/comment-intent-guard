import subprocess, shutil, sys
src=open("comment_intent_guard.py").read()
M={
 "angle_no_max": ("angle_depth = max(0, angle_depth - 1)","angle_depth = angle_depth - 1"),
 "angle_no_close": ("elif text == \">\":\n                angle_depth = max(0, angle_depth - 1)","elif False:\n                pass"),
 "angle_check_off": ("and angle_depth == 0\n","and True\n"),
 "tuple_drop_paren": ("        and tokens[close_k + 2].text == \"(\"\n",""),
 "tuple_drop_ident": ("        and _csharp_is_identifier_start(tokens[close_k + 1].text[0])\n",""),
 "tuple_le": ("close_k + 2 < len(tokens)","close_k + 2 <= len(tokens)"),
 "tuple_none": ("close_k is not None\n        and ","True\n        and "),
 "dedupe_name_only": ("(name.row, name.text) in seen","name.text in seen"),
 "dedupe_off": ("if name is None or (name.row, name.text) in seen:","if name is None:"),
 "suffix_theory_off": ("or name.endswith(\"Theory\")",""),
 "suffix_startswith": ("return name.endswith(\"Fact\") or name.endswith(\"Theory\")","return \"Fact\" in name or \"Theory\" in name"),
 "suffix_lower": ("return name.endswith(\"Fact\") or name.endswith(\"Theory\")","return name.lower().endswith(\"fact\") or name.endswith(\"Theory\")"),
 "no_removesuffix": (".rpartition(\".\")[2].removesuffix(\"Attribute\")",".rpartition(\".\")[2]"),
 "no_rpartition": ("name = name.rpartition(\".\")[2].removesuffix","name = name.removesuffix"),
 "vocab_drop_DTM": ("\"DataTestMethod\", ",""),
 "brackets_noreverse": ("brackets if step > 0 else brackets[::-1]","brackets"),
}
for n,(a,b) in M.items():
    assert src.count(a)==1,(n,src.count(a))
    open("comment_intent_guard.py","w").write(src.replace(a,b))
    r=subprocess.run([sys.executable,"-m","pytest","-q","-x","-p","no:cacheprovider","-n","auto","tests"],capture_output=True,text=True)
    print(n, "KILLED" if r.returncode else "SURVIVED", r.stdout.strip().splitlines()[-1][:80])
open("comment_intent_guard.py","w").write(src)
