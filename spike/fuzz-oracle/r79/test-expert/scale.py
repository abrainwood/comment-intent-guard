import sys,time,importlib.util
def load(p):
    spec=importlib.util.spec_from_file_location('g'+str(abs(hash(p))),p); g=importlib.util.module_from_spec(spec); spec.loader.exec_module(g); return g
m=load('main_guard.py'); h=load('../../../comment_intent_guard.py')
for line in ['x = $@"{\n','#if x = $@"{\n']:
    lo=None
    for k in range(50,3001,25):
        try: m._csharp_lex(line*k)
        except RecursionError: lo=k; break
    print(repr(line),'main first RecursionError at lines',lo)
for k in [250,500,1000,2000]:
    s=time.time(); h._csharp_lex('#if x = $@"{\n'*k); print('head directive',k,round(time.time()-s,2))
