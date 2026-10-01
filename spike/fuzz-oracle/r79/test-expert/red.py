import sys,time,importlib.util
spec=importlib.util.spec_from_file_location('g',sys.argv[1]); g=importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
print('recursionlimit',sys.getrecursionlimit())
for name,t in [('plain','x = $@"{\n'*3000),('directive','#if x = $@"{\n'*3000)]:
    s=time.time()
    try: r=g._csharp_lex(t); print(name,'OK spans',len(r[0]),round(time.time()-s,2))
    except RecursionError as e: print(name,'RecursionError',round(time.time()-s,2))
