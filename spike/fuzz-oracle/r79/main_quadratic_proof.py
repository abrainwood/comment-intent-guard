import importlib.util, os, sys, threading, time
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("main_guard", os.path.join(HERE, "main_guard.py"))
main = importlib.util.module_from_spec(spec); spec.loader.exec_module(main)
sys.setrecursionlimit(1_000_000)
threading.stack_size(1024 * 1024 * 1024)
def run():
    for N in (250, 500, 1000, 2000):
        t = '#if x = $@"{\n' * N
        t0 = time.perf_counter(); main._csharp_lex(t)
        print("main (recursion unbounded)", N, f"{time.perf_counter()-t0:.2f}s")
th = threading.Thread(target=run); th.start(); th.join()
