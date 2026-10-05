import pathlib, sys
src = pathlib.Path(sys.argv[1]).read_text()
out = pathlib.Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
G = ' and text[i + 1] not in "\\r\\n"'
mutants = {
    "m1_string": ('if text[i] == "\\\\" and i + 1 < n' + G + ':\n            i += 2\n            continue\n        if text[i] == \'"\'',
                  'if text[i] == "\\\\" and i + 1 < n:\n            i += 2\n            continue\n        if text[i] == \'"\''),
    "m2_sframe": ('if not verbatim and ch == "\\\\" and i + 1 < n' + G + ':',
                  'if not verbatim and ch == "\\\\" and i + 1 < n:'),
    "m3a_char_nl_early_return": ('    if i < n and text[i] in "\\r\\n":\n        return start + 1\n', ''),
    "m3b_char_backslash": ('if i < n and text[i] == "\\\\" and i + 1 < n' + G + ':',
                           'if i < n and text[i] == "\\\\" and i + 1 < n:'),
    "m4_char_nl_lf_only": ('    if i < n and text[i] in "\\r\\n":\n        return start + 1\n',
                           '    if i < n and text[i] == "\\n":\n        return start + 1\n'),
    "m5_string_lf_only": ('if text[i] == "\\\\" and i + 1 < n' + G + ':\n            i += 2\n            continue\n        if text[i] == \'"\'',
                          'if text[i] == "\\\\" and i + 1 < n and text[i + 1] != "\\n":\n            i += 2\n            continue\n        if text[i] == \'"\''),
    "m6_sframe_lf_only": ('if not verbatim and ch == "\\\\" and i + 1 < n' + G + ':',
                          'if not verbatim and ch == "\\\\" and i + 1 < n and text[i + 1] != "\\n":'),
}
mutants["m3_char_both"] = None
for name, pair in mutants.items():
    if pair is None:
        a = mutants["m3a_char_nl_early_return"]; b = mutants["m3b_char_backslash"]
        assert src.count(a[0]) == 1 and src.count(b[0]) == 1
        m = src.replace(a[0], a[1]).replace(b[0], b[1])
    else:
        assert src.count(pair[0]) == 1, (name, src.count(pair[0]))
        m = src.replace(pair[0], pair[1])
    (out / f"{name}.py").write_text(m)
    print(name)
