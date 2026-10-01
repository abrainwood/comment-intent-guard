import sys,subprocess,shutil
sys.path.insert(0,sys.argv[1]); from mutants import M
S=sys.argv[1]; orig=open(f"{S}/head/comment_intent_guard.py").read()
sel=sys.argv[2:] or list(M)
for name in sel:
    a,b=M[name]
    c=orig.count(a)
    if c!=1: print(name,"PATTERN COUNT",c); continue
    open(f"{S}/mut/comment_intent_guard.py","w").write(orig.replace(a,b))
    r=subprocess.run([sys.executable,"-m","pytest","-q","-x","-n","4","--timeout=30","-p","no:cacheprovider","tests/test_csharp_analyser.py"],cwd=f"{S}/mut",capture_output=True,text=True)
    tail=[l for l in r.stdout.splitlines() if l.startswith("FAILED") or " passed" in l or " failed" in l]
    print(("KILLED " if r.returncode else "SURVIVED ")+name, "|", (tail[0][:140] if tail else r.stdout[-200:]),flush=True)
open(f"{S}/mut/comment_intent_guard.py","w").write(orig)
