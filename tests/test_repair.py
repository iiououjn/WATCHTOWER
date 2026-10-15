from watchtower.floors.f2_dev.repair import repair_imports


def test_adds_missing_stdlib_import_used_as_module():
    src = "import unittest\n\nclass T(unittest.TestCase):\n    def setUp(self):\n        if os.path.exists('x'):\n            os.remove('x')\n"
    fixed, added = repair_imports(src)
    assert added == ["os"]
    assert fixed == "import os\n" + src
    compile(fixed, "t.py", "exec")


def test_import_goes_after_docstring_and_future():
    src = '"""Doc."""\nfrom __future__ import annotations\nx = json.dumps({})\n'
    fixed, added = repair_imports(src)
    assert added == ["json"]
    assert fixed == '"""Doc."""\nfrom __future__ import annotations\nimport json\nx = json.dumps({})\n'


def test_dotted_submodule_imported():
    fixed, added = repair_imports("q = urllib.parse.quote('a b')\n")
    assert added == ["urllib.parse"] and fixed.startswith("import urllib.parse\n")


def test_bound_names_left_alone():
    for src in ("import os\nos.getcwd()\n", "def f(os):\n    return os.x\n", "from os import path as os\nos.x\n",
                "for re in []:\n    re.x\n", "with open('f') as io:\n    io.read()\n", "[json.x for json in []]\n",
                "try:\n    pass\nexcept Exception as time:\n    time.x\n", "def f():\n    global math\n    math.x\n",
                "random = 1\nrandom.x\n", "class html:\n    pass\nhtml.x\n", "from os import *\nsys.x\n"):
        assert repair_imports(src) == (src, []), src


def test_names_not_on_the_allow_list_left_alone():
    for src in ("code.strip()\n", "string.lower()\n", "types.x\n", "foo.bar()\n", "x = os\n"):
        assert repair_imports(src) == (src, []), src


def test_unparsable_source_left_alone():
    src = "def f(:\n    os.x\n"
    assert repair_imports(src) == (src, [])


def test_several_modules_once_each_sorted():
    fixed, added = repair_imports("os.getcwd()\njson.dumps(1)\nos.sep\n")
    assert added == ["json", "os"] and fixed.startswith("import json\nimport os\n")


def test_crlf_file_keeps_crlf():
    fixed, added = repair_imports("x = os.getcwd()\r\n")
    assert added == ["os"] and fixed == "import os\r\nx = os.getcwd()\r\n"


def test_odd_line_separators_inside_docstring_keep_placement():
    src = '"""a b\x0cc"""\nx = os.getcwd()\n'
    fixed, added = repair_imports(src)
    assert added == ["os"] and fixed == '"""a b\x0cc"""\nimport os\nx = os.getcwd()\n'


def test_class_style_use_is_not_a_missing_module_import():
    for src in ("x = datetime.now()\n", "d = datetime.strptime('1', '%d')\n", "os.nothing_like_this()\n"):
        assert repair_imports(src) == (src, []), src


def test_unittest_mock_imports_the_submodule():
    fixed, added = repair_imports("@unittest.mock.patch('app.x')\ndef test_a(m):\n    pass\n")
    assert added == ["unittest.mock"] and fixed.startswith("import unittest.mock\n")


def test_submodule_slips_are_repaired_even_when_the_package_is_imported():
    src = "import unittest\n\n@unittest.mock.patch('app.x')\ndef test_a(m):\n    pass\n"
    fixed, added = repair_imports(src)
    assert added == ["unittest.mock"] and "import unittest.mock\n" in fixed
    covered = "import unittest.mock\n\n@unittest.mock.patch('app.x')\ndef test_a(m):\n    pass\n"
    assert repair_imports(covered) == (covered, [])
    fixed, added = repair_imports("p = html.parser.HTMLParser()\n")
    assert added == ["html.parser"]


def test_attribute_check_never_imports_at_repair_time(monkeypatch):
    import importlib
    from watchtower.floors.f2_dev import repair
    monkeypatch.setattr(importlib, "import_module", lambda *a, **k: (_ for _ in ()).throw(AssertionError("import")))
    assert repair.repair_imports("u = uuid.uuid4()\n")[1] == ["uuid"]


SERVES = '''import os
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = int(os.getenv("PORT", 8000))

class H(BaseHTTPRequestHandler):
    pass

def run(server_class=HTTPServer, handler_class=H):
    httpd = server_class(("127.0.0.1", PORT), handler_class)
    httpd.serve_forever()
'''


def test_repair_main_adds_the_missing_start():
    from watchtower.floors.f2_dev.repair import repair_main
    text, name = repair_main(SERVES)
    assert name == "run" and text.endswith('\n\nif __name__ == "__main__":\n    run()\n')
    compile(text, "app.py", "exec")


def test_repair_main_leaves_alone_what_it_cannot_be_sure_of():
    from watchtower.floors.f2_dev.repair import repair_main
    cases = [
        SERVES + 'if __name__ == "__main__":\n    run()\n',          # already starts
        SERVES + "run()\n",                                        # top-level call
        SERVES.replace("def run(server_class", "def run(port, server_class"),  # needs an argument
        SERVES + "\ndef main():\n    HTTPServer(('', 1), H).serve_forever()\n",  # two candidates
        SERVES.replace("    httpd.serve_forever()", "    pass"),   # nothing serves
        "def run(:\n",                                             # does not parse
        SERVES + "while True:\n    pass\n",                        # top-level loop runs code
    ]
    for source in cases:
        assert repair_main(source) == (source, None), source[-60:]


def test_repair_main_starts_the_root_that_reaches_the_server():
    from watchtower.floors.f2_dev.repair import repair_main
    source = SERVES.replace("def run(server_class", "def run(port, server_class") + (
        "\ndef init_db():\n    pass\n\ndef main():\n    init_db()\n    run(8000)\n")
    text, name = repair_main(source)
    assert name == "main" and text.rstrip().endswith("main()")


def test_repair_main_more_unsure_cases_are_left_alone():
    from watchtower.floors.f2_dev.repair import repair_main
    cases = [
        SERVES + "\nrun = None\n",                                         # rebound after its def
        SERVES + "\ndef a():\n    run()\n\ndef b():\n    run()\n",         # two roots
        SERVES.replace("def run(", "async def run("),                      # async: not ours to start
        SERVES.replace("def run(", "class S:\n  def run(self, ") .replace("handler_class=H):", "handler_class=H):"),
        SERVES + 'if True:\n    pass\n',                                   # top-level if
        "x = '" + "a" * 200_000 + "'\n" + SERVES,                          # too big to repair
    ]
    for source in cases:
        assert repair_main(source) == (source, None), source[-60:]


def test_repair_main_keeps_windows_newlines():
    from watchtower.floors.f2_dev.repair import repair_main
    text, name = repair_main(SERVES.replace("\n", "\r\n"))
    assert name == "run" and text.endswith('\r\n\r\nif __name__ == "__main__":\r\n    run()\r\n') and "\n\n" not in text.replace("\r\n", "")


def test_repair_main_counts_a_function_passed_as_a_value():
    from watchtower.floors.f2_dev.repair import repair_main
    source = SERVES + ("\ndef init_db():\n    pass\n\ndef main():\n    init_db()\n"
                       "    threading.Thread(target=run).start()\n")
    assert repair_main(source)[1] == "main"


def test_repair_main_sees_an_import_rebinding_the_name():
    from watchtower.floors.f2_dev.repair import repair_main
    source = SERVES + "from helpers import run\n"
    assert repair_main(source) == (source, None)


def test_repair_main_never_grows_a_file_past_the_limit():
    from watchtower.floors.f2_dev.repair import MAX_REPAIR_BYTES, repair_main
    source = SERVES + "X = '" + "a" * (MAX_REPAIR_BYTES - len(SERVES) - 10) + "'\n"
    assert repair_main(source) == (source, None)


MAIN_USES = ("from http.server import BaseHTTPRequestHandler\n\nclass H(BaseHTTPRequestHandler):\n"
             "    def do_GET(self):\n        for item in list_items():\n            print(item)\n"
             "    def do_POST(self):\n        add_item('x')\n")
TODO = "def add_item(item):\n    pass\n\ndef list_items():\n    return []\n"


def test_repair_names_imports_what_one_sibling_defines():
    from watchtower.floors.f2_dev.repair import repair_names
    text, added = repair_names(MAIN_USES, "__main__", {"todo": TODO, "test_todo": "def list_items(): pass\n"})
    assert added == ["from todo import add_item, list_items"]
    assert text.startswith("from todo import add_item, list_items\n") and text.endswith(MAIN_USES)


def test_repair_names_leaves_alone_what_it_cannot_be_sure_of():
    from watchtower.floors.f2_dev.repair import repair_names
    cases = [
        (MAIN_USES, {"todo": TODO, "store": "def add_item(): pass\n"}),           # two owners
        (MAIN_USES, {"todo": "def add_item(): pass\n"}),                           # list_items owned by none
        (MAIN_USES, {"todo": TODO + "import __main__\n"}),                         # would import back
        (MAIN_USES, {"json": TODO}),                                               # shadows the standard library
        ("from x import *\n" + MAIN_USES, {"todo": TODO}),                        # star import binds anything
        ("def f(:\n", {"todo": TODO}),                                             # does not parse
        ("print(len([]))\n", {"todo": TODO}),                                      # nothing missing
    ]
    for source, siblings in cases:
        assert repair_names(source, "__main__", siblings) == (source, []), (source[:30], list(siblings))


def test_repair_names_links_only_functions_and_classes_from_safe_modules():
    from watchtower.floors.f2_dev.repair import repair_names
    uses_items = "def f():\n    return items + list_items()\n"
    cases = [
        (MAIN_USES, {"class": TODO}),                                             # keyword: `from class import` breaks
        (uses_items, {"todo": TODO + "items = []\n"}),                            # a variable: a stale copy
        (uses_items, {"todo": TODO + "items: list\n"}),                           # annotation only: not defined
    ]
    for source, siblings in cases:
        assert repair_names(source, "__main__", siblings) == (source, []), list(siblings)


def test_repair_names_never_imports_a_sibling_that_does_things_at_import():
    from watchtower.floors.f2_dev.repair import repair_names
    quiet_main = '\nif __name__ == "__main__":\n    run()\n'
    loud = [
        TODO + "httpd = HTTPServer(('', 8000), H)\n",        # binds the port at import
        TODO + "HTTPServer(('', 8000), H).serve_forever()\n",  # serves at import
        TODO + "unittest.main()\n",                            # a harness: runs and exits
        TODO + "for i in range(3):\n    print(i)\n",          # runs code
    ]
    for sibling in loud:
        assert repair_names(MAIN_USES, "__main__", {"todo": sibling}) == (MAIN_USES, []), sibling[-40:]
    ok = TODO + "import os\nPORT = int(os.getenv('PORT', 8000))\n" + quiet_main
    assert repair_names(MAIN_USES, "__main__", {"todo": ok})[1] == ["from todo import add_item, list_items"]


def test_bare_stdlib_function_gets_its_from_import():
    """Run 26: parse_qs used bare, never imported: NameError in all 4 attempts."""
    src = "def do_POST(self):\n    data = parse_qs(self.rfile.read(5).decode())\n"
    fixed, added = repair_imports(src)
    assert added == ["from urllib.parse import parse_qs"]
    assert fixed == "from urllib.parse import parse_qs\n" + src
    compile(fixed, "t.py", "exec")


def test_bare_names_group_per_module_and_skip_bound():
    src = "class H(BaseHTTPRequestHandler):\n    pass\nsrv = HTTPServer(('', 1), H)\nx = escape('<')\n"
    fixed, added = repair_imports(src)
    assert added == ["from html import escape", "from http.server import BaseHTTPRequestHandler, HTTPServer"]
    for src in ("from urllib.parse import parse_qs\nparse_qs('a')\n", "def parse_qs(x):\n    return x\nparse_qs(1)\n",
                "from urllib.parse import *\nparse_qs('a')\n", "import urllib.parse as parse_qs\nparse_qs.x\n"):
        assert repair_imports(src)[1] == []


def test_bare_name_that_is_an_attribute_or_keyword_is_left_alone():
    assert repair_imports("self.escape = 1\nx = obj.parse_qs\nf(escape=1)\n")[1] == []


def test_module_use_that_is_not_a_module_still_gets_bare_imports():
    fixed, added = repair_imports("x = datetime.now()\nq = parse_qs(s)\n")
    assert added == ["from urllib.parse import parse_qs"] and fixed.startswith("from urllib.parse import parse_qs\n")


def test_name_a_sibling_defines_is_not_imported_from_the_stdlib():
    src = "print(escape('<'))\n"
    assert repair_imports(src, frozenset({"escape"})) == (src, [])


def test_shebang_and_coding_cookie_stay_first():
    src = "#!/usr/bin/env python3\n# -*- coding: latin-1 -*-\nx = parse_qs('a')\n"
    fixed, _ = repair_imports(src)
    assert fixed == "#!/usr/bin/env python3\n# -*- coding: latin-1 -*-\nfrom urllib.parse import parse_qs\nx = parse_qs('a')\n"


def test_one_non_module_use_drops_only_that_module():
    fixed, added = repair_imports("urllib.parse.quote(x)\ndatetime.now()\nparse_qs(y)\n")
    assert added == ["urllib.parse", "from urllib.parse import parse_qs"]


def test_bare_name_bound_by_any_construct_is_left_alone():
    for src in ("[escape for escape in 'ab']\nescape\n", "with open('f') as escape:\n    escape\n",
                "for escape in 'ab':\n    escape\n", "if (escape := 1):\n    escape\n",
                "try:\n    pass\nexcept OSError as escape:\n    escape\n"):
        assert repair_imports(src)[1] == []


def test_mixed_repair_is_ordered_and_idempotent():
    src = '"""Doc."""\nfrom __future__ import annotations\nos.getcwd()\nparse_qs(1)\n'
    fixed, added = repair_imports(src)
    assert added == ["os", "from urllib.parse import parse_qs"]
    assert fixed == ('"""Doc."""\nfrom __future__ import annotations\nimport os\n'
                     'from urllib.parse import parse_qs\nos.getcwd()\nparse_qs(1)\n')
    assert repair_imports(fixed)[1] == []
