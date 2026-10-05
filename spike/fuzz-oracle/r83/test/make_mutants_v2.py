import pathlib, sys
src = pathlib.Path(sys.argv[1]).read_text()
out = pathlib.Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
G = ' and text[i + 1] != "\\n"'
NL = '    if i < n and text[i] == "\\n":\n        return start + 1\n'
STR = 'if text[i] == "\\\\" and i + 1 < n'
TAIL = ':\n            i += 2\n            continue\n        if text[i] == \'"\''
SF = 'if not verbatim and ch == "\\\\" and i + 1 < n'
CH = 'if i < n and text[i] == "\\\\" and i + 1 < n'
mutants = {
    "m1_string": [(STR + G + TAIL, STR + TAIL)],
    "m2_sframe": [(SF + G + ":", SF + ":")],
    "m3a_char_nl_early_return": [(NL, "")],
    "m3b_char_backslash": [(CH + G + ":", CH + ":")],
}
mutants["m3_char_both"] = mutants["m3a_char_nl_early_return"] + mutants["m3b_char_backslash"]
for name, pairs in mutants.items():
    m = src
    for a, b in pairs:
        assert m.count(a) == 1, (name, a, m.count(a)); m = m.replace(a, b)
    (out / f"{name}.py").write_text(m); print(name)
