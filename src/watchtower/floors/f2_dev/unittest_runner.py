"""The unittest runner F2 sends into the sandbox, and how its summary line is read."""
from __future__ import annotations

import json
import re


TEST_RUNNER = """\
import fnmatch, inspect, json, os, sys, unittest
class Fn(unittest.FunctionTestCase):  # pytest-style 'def test_x(): assert ...' runs too, named like a method
    def __str__(self):
        f = self._testFunc
        name = getattr(f, "__name__", str(f))
        return f"{name} ({getattr(f, '__module__', '?')}.{name})"
def plain(fn):
    if inspect.iscoroutinefunction(fn) or inspect.isgeneratorfunction(fn):
        def refuse():
            raise AssertionError("async/generator test functions are not run: use a plain def, or "
                                 "unittest.IsolatedAsyncioTestCase")
        refuse.__name__, refuse.__module__ = fn.__name__, fn.__module__
        return refuse
    return fn
def no_args(fn):
    try:  # mock.patch injects its own arguments: judge the wrapper, not the wrapped function
        sig = inspect.signature(fn, follow_wrapped=not hasattr(fn, "patchings"))
    except (ValueError, TypeError):
        return False
    return all(p.default is not p.empty or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD) for p in sig.parameters.values())
def hook(fn, arg):  # pytest's setup_module(module) / setup_function(function): the argument is optional
    try:
        inspect.signature(fn).bind(arg)
    except (ValueError, TypeError):
        return fn()
    return fn(arg)
class Loader(unittest.TestLoader):
    def loadTestsFromModule(self, module, *args, **kwargs):
        suite = super().loadTestsFromModule(module, *args, **kwargs)
        if not fnmatch.fnmatch(os.path.basename(getattr(module, "__file__", None) or ""), "test*.py"):
            return suite  # app packages are not test files, even when discovery walks them
        for py, ut in (("setup_module", "setUpModule"), ("teardown_module", "tearDownModule")):
            if callable(getattr(module, py, None)) and not hasattr(module, ut):  # pytest's names run too
                setattr(module, ut, lambda f=getattr(module, py), m=module: hook(f, m))
        up, down = getattr(module, "setup_function", None), getattr(module, "teardown_function", None)
        case = type("Fn", (Fn,), {"__module__": module.__name__})  # module fixtures wrap these tests too
        for name, fn in sorted(vars(module).items()):
            if (name.startswith("test") and name != "test_main" and inspect.isfunction(fn)  # test_main: legacy
                    and fn.__name__ != "<lambda>" and fn.__module__ == module.__name__
                    and no_args(fn)):  # a helper that takes arguments is not a test
                suite.addTest(case(plain(fn), setUp=(lambda f=fn: hook(up, f)) if callable(up) else None,
                                   tearDown=(lambda f=fn: hook(down, f)) if callable(down) else None))
        return suite
suite = Loader().discover(".", pattern="test*.py")
result = unittest.TextTestRunner(stream=sys.stderr, verbosity=1).run(suite)
print("WATCHTOWER_TESTS " + json.dumps({"run": result.testsRun, "skipped": len(result.skipped),
      "failures": len(result.failures), "errors": len(result.errors)}), flush=True)
sys.exit(0 if result.wasSuccessful() else 1)
"""
TEST_COMMAND = ["python", "-I", "-c", TEST_RUNNER]  # -I: app files cannot shadow json/unittest
_SUMMARY = re.compile(r"^WATCHTOWER_TESTS (\{.*\})$", re.MULTILINE)


def test_summary(stdout: str) -> dict | None:
    """The runner's own summary line; printed text like 'Ran 2 tests OK' or an early exit never counts."""
    match = _SUMMARY.search(stdout or "")
    try:
        data = json.loads(match.group(1)) if match else None
    except ValueError:
        return None
    return data if isinstance(data, dict) else None
