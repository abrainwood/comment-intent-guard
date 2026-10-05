#!/bin/bash
cd ~/src/cig-rev-83a
O=spike/fuzz-oracle/r83/branch_guard.py
run(){ python - "$1" "$2" <<'PY'
import sys
src=open("spike/fuzz-oracle/r83/branch_guard.py").read()
old,new=sys.argv[1],sys.argv[2]
assert src.count(old)==1,(old,src.count(old))
open("comment_intent_guard.py","w").write(src.replace(old,new))
PY
echo "== $3"; python -m pytest -q tests/test_csharp_analyser.py 2>&1 | tail -1; }
run '    if i < n and text[i] in "\r\n":
        return start + 1
' '' "M1 drop char newline early-return"
run 'if i < n and text[i] == "\\" and i + 1 < n and text[i + 1] not in "\r\n":' 'if i < n and text[i] == "\\" and i + 1 < n:' "M2 drop char escape guard"
run 'if text[i] == "\\" and i + 1 < n and text[i + 1] not in "\r\n":' 'if text[i] == "\\" and i + 1 < n:' "M3 drop string guard"
run 'if not verbatim and ch == "\\" and i + 1 < n and text[i + 1] not in "\r\n":' 'if not verbatim and ch == "\\" and i + 1 < n:' "M4 drop S-frame guard"
run 'if text[i] == "\\" and i + 1 < n and text[i + 1] not in "\r\n":' 'if text[i] == "\\" and i + 1 < n and text[i + 1] != "\n":' "M5 string guard LF only"
run 'if not verbatim and ch == "\\" and i + 1 < n and text[i + 1] not in "\r\n":' 'if not verbatim and ch == "\\" and i + 1 < n and text[i + 1] != "\n":' "M6 S-frame guard LF only"
run '    if i < n and text[i] in "\r\n":
        return start + 1' '    if i < n and text[i] == "\n":
        return start + 1' "M7 char early-return LF only"
cp $O comment_intent_guard.py
git status --short
