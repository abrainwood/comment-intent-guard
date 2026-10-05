import sys
import time
sys.path.insert(0, "tests")
import test_csharp_analyser as t

n = int(sys.argv[1])
for seed in (1, t._CSHARP_SOUP_SEED):
    t0 = time.perf_counter()
    fails = []
    for i, text in enumerate(t._csharp_soup_cases(seed, n)):
        try:
            t._assert_csharp_lex_span_shape(text, f"s{seed} i{i}")
        except AssertionError as e:
            fails.append(str(e)[:120])
    print(f"seed {seed} n={n} failures={len(fails)} {time.perf_counter()-t0:.1f}s", fails[:3])
