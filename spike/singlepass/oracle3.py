JAVADOC = False
ROSLYN = False
import re
TEST = {"Fact","Theory","Test","TestCase","TestMethod"}
def expected(text):
    code = []  # (char, line)
    docs = []  # (code_index_at_start, line)
    i, line, n = 0, 0, len(text)
    while i < n:
        c = text[i]
        if c == "\n": line += 1; i += 1; continue
        if text.startswith("///", i) and not text.startswith("////", i) and (ROSLYN or text[text.rfind("\n",0,i)+1:i].strip()==""):
            docs.append((len(code), line)); j = text.find("\n", i); i = n if j==-1 else j; continue
        if text.startswith("//", i):
            j = text.find("\n", i); i = n if j==-1 else j; continue
        if text.startswith("/*", i):
            if JAVADOC and text[i+2:i+3]=="*" and text[i+3:i+4] not in ("*","/"): docs.append((len(code), line))
            j = text.find("*/", i+2)
            if j == -1: i = n; continue
            line += text.count("\n", i, j); i = j+2; code.append((" ", line)); continue
        if c == '"':
            j = text.find('"', i+1); j = n-1 if j==-1 else j
            for k in range(i, j+1): code.append((text[k] if text[k]!="\n" else " ", line))
            i = j+1; continue
        code.append((c, line)); i += 1
    s = "".join(ch for ch,_ in code)
    global_ms = None
    ms = list(re.finditer(r"public void (A|X)\(\)", s))
    if not any(m.group(1)=="X" for m in ms): return None
    out = []
    for m in ms:
        r = one(s, code, docs, m.start())
        if r and r[0] not in out: out.append(r[0])
    return sorted(out)
def one(s, code, docs, p):
    row = code[p][1] + 1
    k = p; attrs = []
    while True:
        while k > 0 and s[k-1].isspace(): k -= 1
        if k > 0 and s[k-1] == "]":
            d = 0; j = k-1
            while j >= 0:
                if s[j] == "]": d += 1
                elif s[j] == "[": d -= 1
                if d == 0: break
                j -= 1
            if j < 0: break
            attrs.append(s[j:k]); k = j
        else: break
    start = k
    names = re.findall(r"\[\s*([A-Za-z_][\w.]*)", " ".join(attrs)) + re.findall(r",\s*([A-Za-z_][\w.]*)", " ".join(attrs))
    is_test = any(nm.split(".")[-1].removesuffix("Attribute") in TEST for nm in names)
    has_doc = any(start <= ci <= p for ci,_ in docs)
    return [(row,row)] if is_test and has_doc else []
