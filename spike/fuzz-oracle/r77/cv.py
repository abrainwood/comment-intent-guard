def make(H):
    def cvalid(t):
        i=0
        while i<len(t):
            e=H._csharp_try_skip_literal(t,i)
            if e is not None: i=e; continue
            if t.startswith("//",i):
                j=t.find("\n",i); i=len(t) if j==-1 else j; continue
            if t.startswith("/*",i):
                j=t.find("*/",i+2)
                if j==-1: return False
                i=j+2; continue
            i+=1
        return True
    return cvalid
