import sys; sys.path.insert(0,'.')
import guard_main as M, guard_head as H, oracle3 as O
O.ROSLYN=True; O.JAVADOC=True
cases = [
 "[Fact]\n/** d */ // c\npublic void X()\n{\n}\n",
 "[Fact]\n/** d */ /* b */\npublic void X()\n{\n}\n",
 "/** d */ // c\n[Fact]\npublic void X()\n{\n}\n",
 "[Fact]\n/** d\n e */ // c\npublic void X()\n{\n}\n",
 "[Fact]\n/** d */ [Trait(\"a\",\"b\")] // c\npublic void X()\n{\n}\n",
 "/** d\n[Fact]\n*/ /// x\npublic void X()\n{\n}\n",
 "[Fact] /// x\n/// a\npublic void X()\n{\n}\n",
 "/** d\n*/ [Fact]\n/// a\npublic void X()\n{\n}\n",
 "[Fact]\n/** d */ public void X()\n{\n}\n",
 "[Fact]\n/** d */ public void X() { }\n",
 "/** d */ [Fact] public void X()\n{\n}\n",
 "/** d */ [Fact, Trait(\"k\", \"v\")] public void X()\n{\n}\n",
 "[Fact]\n/**/ /// x\npublic void X()\n{\n}\n",
 "[Fact]\n/**/\n/// x\npublic void X()\n{\n}\n",
 "/*** x */\n[Fact]\npublic void X()\n{\n}\n",
]
for t in cases:
    f=lambda m: sorted(v[1] for v in m.find_csharp_blocking_violations(t,"/repo/Tests/ThingTests.cs"))
    print(repr(t)[:70].ljust(72), "main",f(M),"head",f(H),"oracle",O.expected(t))
