import ast,sys,re
def funcs(path, prefix):
    src=open(path).read(); tree=ast.parse(src); out={}
    for n in tree.body:
        if isinstance(n,ast.FunctionDef) and n.name.startswith(prefix):
            out[n.name[len(prefix):]]=ast.get_source_segment(src,n)
    return out
m=funcs('main_guard.py','_csharp_'); t=funcs('../../../tests/test_csharp_analyser.py','_old_csharp_')
for k,v in t.items():
    mv=m.get(k)
    if mv is None: print('MISSING in main',k); continue
    norm=lambda s: re.sub(r'\bguard\.','',s).replace('_old_csharp_','_csharp_')
    a=norm(v).replace('def _old','def ').splitlines(); b=mv.splitlines()
    a=[l for l in norm(v).splitlines()]; 
    import difflib
    d=list(difflib.unified_diff(b,a,lineterm='',n=0))
    print(k, 'IDENTICAL' if not d else '\n'.join(d))
