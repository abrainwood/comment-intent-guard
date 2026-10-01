import sys,subprocess
S=sys.argv[1]; orig=open(f"{S}/head/comment_intent_guard.py").read()
M={
"L01 # anywhere":('if ch == "#" and line_start:','if ch == "#":'),
"L02 line_start never cleared":('        line_start = False\n\n        literal_end','        literal_end'),
"L03 # line not skipped":('if ch == "#" and line_start:','if False:'),
"L04 \\r\\f\\v not ws":('if ch in " \\t\\r\\f\\v":','if ch in " \\t":'),
"L05 unterminated /* to EOF":('text[i + 2:end], None))\n                i = end','text[i + 2:end], None))\n                i = n'),
"L06 literal rows not counted":('            row += text.count("\\n", i, literal_end)\n',''),
"L07 literal no token":("            tokens.append(_CSharpToken('\"', row))\n",''),
"L08 literal not code":('            line_has_code = True\n            i = literal_end','            i = literal_end'),
"L09 /// no anchor":('            if is_doc:\n                doc_anchors.append(len(tokens))\n',''),
"L10 /** no anchor":('            if is_doc_opener:\n                doc_anchors.append(len(tokens))\n',''),
"L11 block row not advanced":('            row = end_li\n',''),
"L12 multiline block keeps line_has_code":('            if end_li != start_li:\n                line_has_code = False\n',''),
"L13 ident not code":('            tokens.append(_CSharpToken(text[i:j], row))\n            line_has_code = True','            tokens.append(_CSharpToken(text[i:j], row))'),
"L14 punct not code":('        tokens.append(_CSharpToken(ch, row))\n        line_has_code = True','        tokens.append(_CSharpToken(ch, row))'),
"L15 @ not ident start":('if ch.isalnum() or ch in "_@":','if ch.isalnum() or ch in "_":'),
"L16 newline keeps line_has_code":('            line_start = True\n            line_has_code = False\n','            line_start = True\n'),
"L17 newline keeps line_start":('            row += 1\n            line_start = True\n','            row += 1\n'),
"L18 always leading":('is_leading = not line_has_code','is_leading = True'),
"L19 merge ignores adjacency":('spans[-1][2] + 1 == li','spans[-1][2] < li'),
"L20 unterminated spans lines":('spans.append((block_kind, start_li, start_li, text[i + 2:end], None))','spans.append((block_kind, start_li, start_li + text.count("\\n", i, end), text[i + 2:end], None))'),
"L21 close_col off by one":('close_col = close - (text.rfind("\\n", 0, close) + 1)','close_col = close - text.rfind("\\n", 0, close)'),
"L22 unterminated content to EOF":('text[i + 2:end], None))','text[i + 2:], None))'),
"L23 # line skip to EOF":('            i = n if eol == -1 else eol\n            continue\n\n        line_start = False','            i = n\n            continue\n\n        line_start = False'),
"L24 block close +1":('            i = close + 2\n','            i = close + 1\n'),
"L25 ident stops at digit":('while j < n and (text[j].isalnum() or text[j] == "_"):','while j < n and (text[j].isalpha() or text[j] == "_"):'),
"L26 /* doc kind ignored":('block_kind = "doc" if is_doc_opener else "block"','block_kind = "block"'),
"L27 merge allows non-leading":('if is_doc and is_leading and spans','if is_doc and spans'),
"L28 line doc anchors any //":('            if is_doc:\n                doc_anchors.append(len(tokens))\n','            doc_anchors.append(len(tokens))\n'),
}
sel=sys.argv[2:] or list(M)
for name in sel:
    a,b=M[name]; c=orig.count(a)
    if c!=1: print(name,"PATTERN COUNT",c,flush=True); continue
    open(f"{S}/mut/comment_intent_guard.py","w").write(orig.replace(a,b))
    r=subprocess.run([sys.executable,"-m","pytest","-q","-x","-n","4","--timeout=30","-p","no:cacheprovider","tests"],cwd=f"{S}/mut",capture_output=True,text=True)
    tail=[l for l in r.stdout.splitlines() if l.startswith("FAILED") or " passed" in l or " failed" in l]
    print(("KILLED " if r.returncode else "SURVIVED ")+name,"|",(tail[0][:150] if tail else r.stdout[-200:]),flush=True)
open(f"{S}/mut/comment_intent_guard.py","w").write(orig)
