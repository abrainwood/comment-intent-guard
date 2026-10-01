import sys, importlib, subprocess
sys.path.insert(0, sys.argv[1])
import comment_intent_guard as g
P="/repo/Tests/T.cs"
def run(attr, sig="public void X()"):
    t=f"/// <summary>x</summary>\n{attr}\n{sig}\n{{\n}}\n"
    v=g.find_csharp_blocking_violations(t,P)
    return [ (x[1][0], x[0].split("`")[1] if "`" in x[0] else x[0][:40]) for x in v]
for a in ["[Artifact]","[Theory]","[NonFact]","[FactAttribute]","[fact]","[Fact()]","[Xunit.Fact]","[Fact(Skip = \"x\")]",
          "[global::Xunit.Fact]","[Xunit.FactAttribute]","[TheoryAttribute]","[UIFactAttribute]","[ConditionalFact]","[WpfFact]",
          "[DataTestMethod]","[TestCaseSource(nameof(S))]","[SkippableFact]","[Fact, Trait(\"a\",\"b\")]","[method: Fact]",
          "[NotAFact]","[NoTheory]","[IsFact]","[Attribute]","[FactAttributeAttribute]","[TestCaseAttribute]",
          "[DataRow(1)]","[TestFixture]","[Fact<int>]","[Test<int>]",
          "[Foo<Bar<int, Fact>>]","[Foo<int>, Fact]","[Range(1 < 2)]","[Range(1 > 2), Fact]","[Range(1 < 2), Fact]",
          "[Trait(\"k\", \"<\")]","[Trait(\"k\", \"<\"), Fact]","[Foo(typeof(List<int>)), Fact]","[Foo(A<B, Fact>C)]","[Foo(a < b), Fact]",
          "[Foo(a > b), Fact]","[Foo(1 << 2), Fact]","[Foo(1 >> 2), Fact]","[Foo(a >= b), Fact]","[Foo(a <= b), Fact]"]:
    print(f"{a:40} {run(a)}")
for s in ["public (int a, (string, int) b) X()","public Task<(int, int)> X()","public void X((int, int) p)",
          "public (int, int)[] X()","public (int, int)? X()","public static (int, int) X<T>()","public async Task<(int a,int b)> X()",
          "public (int, int) X<T>((int,int) p) where T : class","(int, int) X()","public ref (int,int) X()",
          "public void X(int a = (1))", "public int this[(int,int) i] => 0;", "public (int, int) P => (1, 2);",
          "public (int,int) X() => (1,2);","public void X((int a, int b) p, (int, int) q)","public (int, int) X ()",
          "public unsafe (int,int)* X()" ]:
    print(f"{s:45} {run('[Fact]', s)}")
t="/** a */ [Fact] public void A() {} /** b */ [Fact] public void A() {}\n"
print("same-name-same-row", g.find_csharp_blocking_violations(t,P))
t="/** a */ [Fact] public void A(int x) {} /** b */ [Fact] public void A(string y) {}\n"
print("overload-same-row", len(g.find_csharp_blocking_violations(t,P)))
t="/// <summary>x</summary>\n/// <summary>y</summary>\n[Fact]\npublic void X()\n{\n}\n"
print("two-docs", g.find_csharp_blocking_violations(t,P))
