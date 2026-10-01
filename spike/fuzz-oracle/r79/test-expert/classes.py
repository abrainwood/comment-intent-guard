import sys,random,re
sys.path.insert(0,'../../..'); sys.path.insert(0,'../../../tests')
import test_csharp_analyser as T
rng=random.Random(20261002); texts=[]
for _ in range(2000):
    texts.append("".join(T._random_interpolation_corpus_line(rng) for _ in range(rng.randint(1,3))))
def depth(t):
    d=m=0
    for c in t:
        if c=='{': d+=1; m=max(m,d)
        elif c=='}': d=max(0,d-1)
    return m
cls={
 'interp $"':lambda t:re.search(r'(?<![$@])\$"',t),
 'interp $@"':lambda t:'$@"' in t,
 'interp @$" (alt order)':lambda t:'@$"' in t,
 'raw $"""':lambda t:re.search(r'(?<!\$)\$"""',t),
 'raw $$"""':lambda t:'$$"""' in t,
 'raw quote_run>3':lambda t:'""""' in t.replace('"""','',0) and re.search(r'\$+"{4}',t),
 'escaped {{ in $"':lambda t:re.search(r'(?<!\$)\$@?"[^"\n]*\{\{',t),
 'nested hole (literal with hole inside a hole)':lambda t:re.search(r'\{[^{}"\n]*\$+@?"+[^"\n]*\{',t),
 'brace depth>=3 chars':lambda t:depth(t)>=3,
 'char literal in hole':lambda t:re.search(r"\{[^}\n]*'",t),
 'plain string in hole':lambda t:re.search(r'\{[^}\n]*[^$@]"[^"]',t),
 'comment // inside hole':lambda t:re.search(r'\{[^}\n]*//',t),
 'comment /* anywhere':lambda t:'/*' in t,
 'bare { or } in hole code (not literal)':lambda t:False,
 'unterminated at EOL':lambda t:any(l.count('"')%2 for l in t.split('\n')),
 'newline inside a literal':lambda t:False,
 '#directive line':lambda t:'#' in t,
 'doc comment ///':lambda t:'///' in t,
}
for k,f in cls.items(): print(f'{k:50s}',sum(1 for t in texts if f(t)))
print('distinct texts',len(set(texts)))
