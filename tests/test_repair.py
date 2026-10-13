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
