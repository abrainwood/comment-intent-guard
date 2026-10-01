import importlib.util,random
def load(p,n):
    spec=importlib.util.spec_from_file_location(n,p); g=importlib.util.module_from_spec(spec); spec.loader.exec_module(g); return g
head=load('../../../comment_intent_guard.py','head')
TOK=['{','}','{{','}}','"','""','"""','$"','$@"','@"','$$"""','\\','\n','// c','x',' ','new { a }']
for m in ['R_open_needs_more_braces','RH_code_brace_no_depth_inc','H_only_nested_verbatim_flip']:
    mut=load(f'mut2/{m}/comment_intent_guard.py',m); rng=random.Random(5); best=None
    for _ in range(300000):
        t='x = '+''.join(rng.choice(TOK) for _ in range(rng.randint(1,7)))+'; // c\n'
        a=list(head._csharp_comment_spans(t)); b=list(mut._csharp_comment_spans(t))
        if a!=b and (best is None or len(t)<len(best[0])): best=(t,a,b)
    print(m, repr(best[0]) if best else None, best[1:] if best else '')
