import sys,random,importlib.util,pathlib,time
sys.path.insert(0,'../../../tests')
def load(p,n):
    spec=importlib.util.spec_from_file_location(n,p); g=importlib.util.module_from_spec(spec); spec.loader.exec_module(g); return g
oracle=load('main_guard.py','oracle')
target=load(sys.argv[1],'target')
TOK=['{','}','{{','}}','"','""','"""','$"','$@"','@$"','$$"""','@"',"'a'","'\\''",'\\"','\\','\n','#if ','// c','/* c */','///','new { a = 1 }','x',' ','(',')',',']
rng=random.Random(int(sys.argv[2]) if len(sys.argv)>2 else 1)
s=time.time(); bad=0
for k in range(int(sys.argv[3]) if len(sys.argv)>3 else 20000):
    t=''.join(rng.choice(TOK) for _ in range(rng.randint(1,25)))
    try: a=target._csharp_lex(t)
    except RecursionError: a='RecErr'
    try: b=oracle._csharp_lex(t)
    except RecursionError: b='RecErr'
    if a!=b:
        bad+=1
        if bad<=1: print('DIVERGE',repr(t))
print(sys.argv[1].split('/')[-2] if 'mut' in sys.argv[1] else 'HEAD','divergences',bad,'time',round(time.time()-s,1))
