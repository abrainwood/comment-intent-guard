from diff_fuzz import M, B, full
cases = ['"abc\\', 'x = "abc\\', "'\\", "'", '$"abc\\', '$"{x}\\',
         '@"ab\\\n// c\n"', '@"ab\\\r\n// c\r\n"', '$@"ab\\\n// c\n"', '$@"ab\\\r\n// c\r\n"', '@$"a{"\\\n// c\n"}"',
         "var c = '\r'; // x\n", "'\\\r'// c\n", '"a\\\r"// c\n', '$"a\\\r"// c\n']
for t in cases:
    m, b = full(M, t), full(B, t)
    print("SAME" if m == b else "DIFF", repr(t), "" if m == b else f"\n   main={m}\n   brch={b}")
