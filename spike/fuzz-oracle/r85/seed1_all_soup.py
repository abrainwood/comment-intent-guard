import sys
import time
sys.path.insert(0, "tests")
import test_csharp_analyser as t

names = [n for n in dir(t) if n.startswith("test_csharp_lex_") and "soup" in (getattr(t, n).__code__.co_names and " ".join(getattr(t, n).__code__.co_names))]
for count in (20000, 200000):
    for seed in (t._CSHARP_SOUP_SEED, 1):
        t._CSHARP_SOUP_SEED_2, t._CSHARP_SOUP_CASE_COUNT_2 = 1, 0
        orig_seed = 20261005
        t._CSHARP_SOUP_SEED, t._CSHARP_SOUP_CASE_COUNT = seed, count
        for n in names:
            t0 = time.perf_counter()
            try:
                getattr(t, n)()
                res = "pass"
            except BaseException as e:
                res = "FAIL " + str(e)[:100]
            print(f"n={count} seed={seed} {n[:70]:70} {time.perf_counter()-t0:.2f}s {res}")
        t._CSHARP_SOUP_SEED = orig_seed
