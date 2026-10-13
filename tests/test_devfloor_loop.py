from devfloor_kit import *  # noqa: F403 — helpers and fixtures


def test_failures_are_parsed_from_unittests_own_report():
    found = failures(REAL)
    assert [f["test"] for f in found] == ["test_list_todos", "test_render_todo_form"]
    assert found[0]["line"].startswith("AssertionError: '<ul><li>Buy milk") and not found[0]["whitespace"]
    assert found[1]["whitespace"] is True
    assert failures("garbage\nFAIL: nothing here") == [] and failures("") == []


def test_every_failure_reaches_the_coder_even_with_long_output(tmp_path):
    script = Script({"f2.coder": [{"files": [APP, TEST]}]})
    dev(tmp_path, script, Runner([FAILED]), rounds=2).build(SPEC, PLAN3, [])
    second = script.prompts["f2.coder"][1]
    assert "test_list_todos" in second and "test_render_todo_form" in second
    assert "differ only in spaces" in second


def test_stuck_coder_gets_a_note_and_one_hr_diagnosis(tmp_path):
    script = Script({"f2.coder": [{"files": [APP, TEST]}],
                     "f2.hr": [{"diagnosis": "test_add_todo leaves Buy milk in the shared list; reset it in setUp"}]})
    d = DevFloor(ARCH, CODER, ask=script, workspace=Workspace(tmp_path), run=Runner([FAILED]), max_rounds=4, hr=HR)
    d.build(SPEC, PLAN3, [])
    prompts = script.prompts["f2.coder"]
    assert "same tests failed again" not in prompts[1] and "same tests failed again" in prompts[2]
    assert "reset it in setUp" in prompts[2] and '<untrusted source="f2.hr">' in prompts[2]
    assert len(script.prompts["f2.hr"]) == 1  # once per build, however long it stays stuck


def test_hr_garbage_while_stuck_costs_nothing(tmp_path):
    calls = []

    def ask(role, prompt):
        calls.append(role.id)
        if role.id == "f2.hr":
            raise BadModelOutput("x")
        return {"files": [APP, TEST]}
    d = DevFloor(ARCH, CODER, ask=ask, workspace=Workspace(tmp_path), run=Runner([FAILED]), max_rounds=3, hr=HR)
    assert not d.build(SPEC, PLAN3, []).checks_run[-1]["pass"] and calls.count("f2.hr") == 1


def test_real_314_report_variants_all_surface_with_their_real_cause():
    found = {f["test"]: f for f in failures(PY314)}
    assert set(found) == {"test_chain", "test_custom", "test_b", "test_sub"}
    assert found["test_chain"]["line"] == "ValueError: v"
    assert found["test_custom"]["line"] == "test_a.Boom: x"
    assert found["test_b"]["line"].startswith("ImportError: cannot import name 'nope' from 'app'")
    assert found["test_sub"]["line"] == "AssertionError: 0 != 5"
    assert list(found)[:2] == ["test_b", "test_sub"]  # import errors first (they hide a whole file), then FAILs


def test_failure_note_is_bounded_and_keeps_html_readable(tmp_path):
    from watchtower.floors.f2_dev.devfloor import _failure_note
    many = [{"test": f"test_{i}", "id": f"m.T.test_{i}", "kind": "FAIL",
             "line": "AssertionError: '" + "<li>x</li>" * 30 + "'", "diff": "- <ul>" * 60, "whitespace": False}
            for i in range(5)]
    note = _failure_note(many)
    assert len(note) <= 2200 and "&lt;" not in note and "<li>" in note and "test_4" in note


def test_stuck_round_keeps_the_failure_rows_and_the_diagnosis_survives_a_garbled_reply(tmp_path):
    replies = [{"files": [APP, TEST]}, {"files": [APP, TEST]}, "garbled", {"files": [APP, TEST]}]
    calls = []

    def ask(role, prompt):
        calls.append((role.id, prompt))
        if role.id == "f2.hr":
            return {"diagnosis": "reset the shared list in setUp"}
        r = replies.pop(0) if len(replies) > 1 else replies[0]
        if r == "garbled":
            raise BadModelOutput("x")
        return r
    d = DevFloor(ARCH, CODER, ask=ask, workspace=Workspace(tmp_path), run=Runner([FAILED]), max_rounds=4, hr=HR)
    d.build(SPEC, PLAN3, [])
    coder = [p for r, p in calls if r == "f2.coder"]
    assert "reset the shared list in setUp" in coder[3] and "test_list_todos" in coder[3]
    hr = [p for r, p in calls if r == "f2.hr"]
    assert len(hr) == 1 and "test_list_todos" in hr[0] and "x" * 200 not in hr[0]


def test_failing_set_resets_after_a_passing_round(tmp_path):
    seq = [FAILED, OK, FAILED]
    script = Script({"f2.coder": [{"files": [APP, TEST]}], "f2.hr": [{"pass": False, "reason": "add more"}]})
    d = DevFloor(ARCH, CODER, ask=script, workspace=Workspace(tmp_path), run=Runner(seq), max_rounds=4, hr=HR)
    d.build(SPEC, PLAN3, [])
    assert not any("same tests failed again" in p for p in script.prompts["f2.coder"])


def test_docstring_tests_chained_and_multiline_causes():
    found = {f["test"]: f for f in failures(PY314B)}
    assert set(found) == {"test_chain", "test_err_doc", "test_dash", "test_doc", "test_msg", "test_none"}
    assert found["test_chain"]["line"] == "ValueError: outer"
    assert found["test_msg"]["line"] == "AssertionError: 1 != 2 : custom"
    assert found["test_err_doc"]["line"] == "KeyError: 'k'"


def test_error_rows_say_where_the_app_raised():
    from watchtower.floors.f2_dev.devfloor import _failure_rows
    rows = _failure_rows(failures(APP_ERROR))
    assert "KeyError: 'default'" in rows and "app.py" in rows and "line 42" in rows and "TODOS[kind]" in rows


def test_more_than_five_failures_says_so_and_import_errors_come_first():
    from watchtower.floors.f2_dev.devfloor import _failure_rows
    found = failures(PY314B + PY314)
    rows = _failure_rows(found)
    assert rows.startswith("- test_b (ERROR): ImportError") and "more failing" in rows


def test_a_diagnosis_is_only_shown_for_the_failures_it_was_made_for(tmp_path):
    other = SandboxResult(1, 'WATCHTOWER_TESTS {"run": 1, "skipped": 0, "failures": 0, "errors": 1}\n', APP_ERROR, False)
    calls = []

    def ask(role, prompt):
        calls.append((role.id, prompt))
        if role.id == "f2.hr":
            return {"diagnosis": f"diagnosis number {sum(r == 'f2.hr' for r, _ in calls)}"}
        return {"files": [APP, TEST]}
    d = DevFloor(ARCH, CODER, ask=ask, workspace=Workspace(tmp_path),
                 run=Runner([FAILED, FAILED, other, other, other]), max_rounds=5, hr=HR)
    d.build(SPEC, PLAN3, [])
    coder = [p for r, p in calls if r == "f2.coder"]
    assert "diagnosis number 1" in coder[2] and "diagnosis number 1" not in coder[3]
    assert "diagnosis number 1" not in coder[4] and "diagnosis number 2" in coder[4]


def test_hr_change_request_survives_a_garbled_reply(tmp_path):
    replies = [{"files": [APP, TEST]}, "garbled", {"files": [APP, TEST]}]
    calls = []

    def ask(role, prompt):
        calls.append((role.id, prompt))
        if role.id == "f2.hr":
            return {"pass": False, "reason": "add a delete route"}
        r = replies.pop(0) if len(replies) > 1 else replies[0]
        if r == "garbled":
            raise BadModelOutput("x")
        return r
    DevFloor(ARCH, CODER, ask=ask, workspace=Workspace(tmp_path), run=Runner([OK]), max_rounds=3, hr=HR).build(
        SPEC, PLAN3, [])
    coder = [p for r, p in calls if r == "f2.coder"]
    assert "add a delete route" in coder[2]


def test_when_only_a_syntax_error_remains_the_coder_is_told_exactly_that(tmp_path):
    ws = Workspace(tmp_path)
    for name, body in (("todo.py", "items = []\n"), ("__main__.py", BROKEN_MAIN),
                       ("test_todo.py", "import unittest\nimport todo\n")):
        ws.write(name, body)
    script = Script({"f2.coder": [{"files": []}]})
    plan = {"entry": "app.py", "routes": [], "files": [{"path": "todo.py", "purpose": "t"}]}
    d = DevFloor(ARCH, CODER, ask=script, workspace=ws, run=Runner([OK]), max_rounds=2)
    assert not d.build(SPEC, plan, []).checks_run[-1]["pass"]
    second = script.prompts["f2.coder"][1]
    note = second[second.index("only thing left"):]
    assert "__main__.py" in note and "line 4" in note and "html += '<form>" in note


def test_the_problem_note_survives_trimming_in_a_big_prompt(tmp_path):
    ws = Workspace(tmp_path)
    ws.write("__main__.py", BROKEN_MAIN)
    for name, body in (("todo.py", "items = []\n"),
                       ("test_todo.py", "import unittest\nimport todo\nclass T(unittest.TestCase):\n    pass\n")):
        ws.write(name, body)
    spec = {**SPEC, "acceptance": ["a" * 190 for _ in range(6)]}
    plan = {"entry": "app.py", "routes": [], "files": [{"path": f"m{i}/" + "p" * 80 + ".py", "purpose": "q" * 78}
                                                       for i in range(15)]}
    qa = [{"name": f"c{i}", "method": "GET", "path": "/" + "z" * 60, "form": {}, "expect_status": 200,
           "expect_text": "t" * 70} for i in range(8)]
    script = Script({"f2.coder": [{"files": [{"path": "x.txt", "content": "y"}] * 3 + [{"path": "../bad", "content": ""}]}]})
    d = DevFloor(ARCH, CODER, ask=script, workspace=ws, run=Runner([OK]), max_rounds=2)
    d.build(spec, plan, [], qa)
    second = script.prompts["f2.coder"][1]
    assert "only thing left" in second and "html += '<form>" in second
    assert len(second) <= 9_000 + 2_000  # the prompt stays bounded (+ system/brief elsewhere)


def test_only_thing_left_is_never_claimed_while_the_test_bar_is_unmet(tmp_path):
    ws = Workspace(tmp_path)
    ws.write("__main__.py", BROKEN_MAIN)
    ws.write("test_todo.py", "import unittest\n")  # imports nothing from the app
    one = SandboxResult(0, 'WATCHTOWER_TESTS {"run": 1, "skipped": 0, "failures": 0, "errors": 0}\n', "", False)
    script = Script({"f2.coder": [{"files": []}]})
    DevFloor(ARCH, CODER, ask=script, workspace=ws, run=Runner([one]), max_rounds=2).build(
        SPEC, {"entry": "app.py", "routes": [], "files": []}, [])
    second = script.prompts["f2.coder"][1]
    assert "only thing left" not in second and "syntax error" in second and "import nothing" in second


def test_excerpt_always_shows_the_error_line(tmp_path):
    from watchtower.floors.f2_dev.devfloor import _problem_note
    ws = Workspace(tmp_path)
    ws.write("my app.py", ("x = '" + "h" * 300 + "'\n") * 3 + "if (\n")
    note = _problem_note(["my app.py has a syntax error on line 4: '(' was never closed"], ws, True)
    assert "   4| if (" in note and len(note) < 1700 and note.count("<untrusted") == note.count("</untrusted>")


def test_every_note_kind_is_bounded_after_escaping():
    from watchtower.floors.f2_dev.devfloor import NOTE_CAP, _capped, _failure_note
    huge = [{"test": "test_" + "n" * 300 + str(i), "id": f"m.T.{i}", "kind": "FAIL", "line": "AssertionError: " + "<" * 200,
             "diff": "<" * 400, "whitespace": True} for i in range(20)]
    stuck = "names " + ", ".join(f["test"] for f in huge)
    assert len(_failure_note(huge, stuck, "<b>" * 300)) <= NOTE_CAP
    assert len(_capped("gate", "<" * 600)) <= NOTE_CAP // 2


def test_failures_and_problems_share_one_note(tmp_path):
    ws = Workspace(tmp_path)
    ws.write("__main__.py", BROKEN_MAIN)
    ws.write("test_todo.py", "import unittest\nimport todo\n")
    ws.write("todo.py", "x = 1\n")
    script = Script({"f2.coder": [{"files": []}]})
    DevFloor(ARCH, CODER, ask=script, workspace=ws, run=Runner([FAILED]), max_rounds=2).build(
        SPEC, {"entry": "app.py", "routes": [], "files": []}, [])
    second = script.prompts["f2.coder"][1]
    fail_at, prob_at = second.index("Failing tests"), second.index("Also fix these problems")
    assert fail_at < prob_at and "\n\n" not in second[fail_at:prob_at].split("Failing tests")[0]


def test_syntax_error_first_marked_and_counted_right(tmp_path):
    from watchtower.floors.f2_dev.devfloor import _problem_note
    ws = Workspace(tmp_path)
    ws.write("z.py", "a = 1\x0c\nb = 2\nif (\n")
    probs = [f"m{i}.py imports flask (not in the Python standard library)" for i in range(4)]
    note = _problem_note(probs + ["z.py has a syntax error on line 3: '(' was never closed"], ws, True)
    assert note.index("z.py has a syntax error") < note.index("m0.py") and "(+2 more)" in note
    assert ">   3| if (" in note


def test_a_line_break_lost_inside_a_string_is_repaired():
    src = "html = f'<body>\n{x}</body>'\nprint(f'Starting...\n')\n"
    fixed, lines = repair_strings(src)
    compile(fixed, "a.py", "exec")
    assert lines == [1, 3] and "f'<body>\\n{x}</body>'" in fixed


def test_repair_keeps_progress_but_never_invents_a_close():
    src = "a = f'one\ntwo'\nb = bytes(a, \"utf8')\nc = 1\n"
    fixed, lines = repair_strings(src)
    assert lines == [1] and "f'one\\ntwo'" in fixed and "\"utf8')" in fixed  # the quote mismatch is the coder's job
    assert repair_strings("x = 1\n") == ("x = 1\n", [])
    assert repair_strings("s = '''never\nclosed\n")[1] == []  # triple-quoted: not this repair


def test_written_python_files_are_repaired_with_a_note(tmp_path):
    script = Script({"f2.coder": [{"files": [{"path": "app.py", "content": "x = 'a\nb'\n"}, TEST]}]})
    d = dev(tmp_path, script, Runner([OK]), rounds=2)
    d.build(SPEC, PLAN3, [])
    assert Workspace(tmp_path).read("app.py") == "x = 'a\\nb'\n"


def test_runner_accepts_pytest_style_test_functions(tmp_path):
    import subprocess
    import sys
    from watchtower.floors.f2_dev.devfloor import TEST_RUNNER, failures, test_summary
    (tmp_path / "app.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "test_app.py").write_text("from app import add\n\ndef test_ok():\n    assert add(1, 2) == 3\n\n"
                                         "def test_bad():\n    assert add(1, 1) == 3\n")
    out = subprocess.run([sys.executable, "-I", "-c", TEST_RUNNER], cwd=tmp_path, capture_output=True, text=True,
                         timeout=60)
    summary = test_summary(out.stdout)
    assert summary["run"] == 2 and summary["failures"] == 1
    assert [f["test"] for f in failures(out.stderr)] == ["test_bad"]


@pytest.mark.parametrize("src", ['def render(page="home):\n    """Render\n    one page."""\n    return page\n',
                                 'NAME = "app\nHELP = """\nusage\n"""\n',
                                 'color = "#ff0000\nbg = "#000000"\n', "h = '# Title\nsub = '## Sub'\n",
                                 "name = 'abc\n# keep the users'\nx = 1\n", "name = 'abc\n# the users', so\n"])
def test_a_genuinely_missing_quote_is_never_repaired(src):
    assert repair_strings(src) == (src, [])


def test_strings_split_over_several_lines_and_crlf_are_repaired():
    fixed, lines = repair_strings('print("Usage:\n  foo\n")\nx = 1\n')
    compile(fixed, "a.py", "exec")
    assert lines == [1] and 'print("Usage:\\n  foo\\n")' in fixed
    fixed, lines = repair_strings('r = "HTTP/1.1 200 OK\r\n\r\n"\r\ny = 2\r\n')
    compile(fixed, "a.py", "exec")
    assert lines == [1] and '"HTTP/1.1 200 OK\\r\\n\\r\\n"' in fixed


def test_repair_survives_absurd_sources_quietly(capfd):
    deep = "x = " + "+".join(["1"] * 20000) + "\n"
    assert repair_strings(deep) == (deep, [])
    noisy = 'import re\np = re.compile("\\d+")\n'
    assert repair_strings(noisy) == (noisy, []) and "SyntaxWarning" not in capfd.readouterr().err


def test_runner_skips_helpers_and_package_functions(tmp_path):
    summary, err = _run_runner(tmp_path, {
        "app.py": "def add(a, b):\n    return a + b\n",
        "pkg/__init__.py": "def test_connection(dsn):\n    raise RuntimeError('not a test')\n",
        "test_app.py": "import unittest\nfrom app import add\n\ndef test_request(path):\n    return add(1, 2)\n\n"
                       "class T(unittest.TestCase):\n    def test_a(self):\n        self.assertEqual(test_request('/'), 3)\n"})
    assert summary == {"run": 1, "skipped": 0, "failures": 0, "errors": 0}, err


def test_function_tests_see_setupmodule_and_async_or_generator_tests_fail(tmp_path):
    summary, err = _run_runner(tmp_path, {
        "test_app.py": "STATE = {}\n\ndef setUpModule():\n    STATE['ready'] = True\n\n"
                       "def test_state():\n    assert STATE.get('ready')\n\n"
                       "async def test_async():\n    assert False\n\n"
                       "def test_gen():\n    yield\n    assert False\n"})
    assert summary["run"] == 3 and summary["failures"] + summary["errors"] == 2, err
    assert "IsolatedAsyncioTestCase" in err or "not run" in err


def test_runner_ignores_the_legacy_test_main_idiom_and_odd_functions(tmp_path):
    summary, err = _run_runner(tmp_path, {
        "app.py": "def add(a, b):\n    return a + b\n",
        "test_app.py": "import unittest\nfrom unittest import mock\nfrom app import add\n\n"
                       "class T(unittest.TestCase):\n    def test_a(self):\n        self.assertEqual(add(1, 2), 3)\n\n"
                       "def test_main():\n    unittest.main()\n\n"
                       "test_lam = lambda: None\n\n"
                       "def test_sig():\n    pass\ntest_sig.__signature__ = 'nope'\n\n"
                       "@mock.patch('app.add', return_value=5)\ndef test_patched(m):\n    import app\n"
                       "    assert app.add(1, 1) == 5\n"})
    assert summary == {"run": 2, "skipped": 0, "failures": 0, "errors": 0}, err


def test_repair_note_says_the_lines_are_in_what_the_coder_sent(tmp_path):
    script = Script({"f2.coder": [{"files": [{"path": "app.py", "content": "x = 'a\nb'\n"}, TEST]}]})
    dev(tmp_path, script, Runner([FAILED]), rounds=2).build(SPEC, PLAN3, [])
    assert "line(s) 1 of what you sent" in script.prompts["f2.coder"][1]


def test_parse_notes_reach_the_coder_and_the_repair_note_never_mentions_json(tmp_path):
    script = Script({"f2.coder": [{"files": [{"path": "app.py", "content": "x = 'a\nb'\n"}, TEST],
                                   "notes": ["File b.py was cut off (no closing fence); send it again, shorter"]}]})
    dev(tmp_path, script, Runner([FAILED]), rounds=2).build(SPEC, PLAN3, [])
    second = script.prompts["f2.coder"][1]
    assert "b.py was cut off" in second and "Auto-repaired" in second and "JSON" not in second


def test_deletes_do_not_use_up_the_file_cap(tmp_path):
    Workspace(tmp_path).write("old.py", "x = 1\n")
    files = [{"path": "old.py", "delete": True}, APP, TEST, {"path": "store.py", "content": "S = 1\n"}]
    script = Script({"f2.coder": [{"files": files}]})
    dev(tmp_path, script, Runner([OK]), rounds=1).build(SPEC, PLAN3, [])
    assert sorted(Workspace(tmp_path).files()) == ["app.py", "store.py", "test_app.py"]


def test_missing_standard_import_is_added_and_the_coder_told(tmp_path):
    body = "import unittest\nfrom app import f\n\nclass T(unittest.TestCase):\n    def test_a(self):\n" \
           "        self.assertTrue(os.getcwd())\n"
    script = Script({"f2.coder": [{"files": [APP, {"path": "test_app.py", "content": body}]}]})
    dev(tmp_path, script, Runner([FAILED]), rounds=2).build(SPEC, PLAN3, [])
    assert Workspace(tmp_path).read("test_app.py") == "import os\n" + body
    assert "added the missing import os to test_app.py" in script.prompts["f2.coder"][1]


def test_a_reply_that_changes_nothing_is_called_out(tmp_path):
    ws = Workspace(tmp_path)
    ws.write(APP["path"], APP["content"])
    ws.write(TEST["path"], TEST["content"])
    script = Script({"f2.coder": [{"files": [APP, TEST]}, {"files": [APP, TEST]}]})
    dev(tmp_path, script, Runner([FAILED, FAILED]), rounds=2).build(SPEC, PLAN3, [])
    second = script.prompts["f2.coder"][1]
    assert "sent app.py, test_app.py back unchanged" in second


def test_a_reply_that_changes_one_file_is_not_called_unchanged(tmp_path):
    ws = Workspace(tmp_path)
    ws.write(APP["path"], APP["content"])
    script = Script({"f2.coder": [{"files": [APP, TEST]}, {"files": [APP]}]})
    dev(tmp_path, script, Runner([FAILED, FAILED]), rounds=2).build(SPEC, PLAN3, [])
    assert "unchanged" not in script.prompts["f2.coder"][1]


def test_crlf_resend_is_still_unchanged_and_a_missing_delete_is_no_change(tmp_path):
    ws = Workspace(tmp_path)
    ws.write(APP["path"], APP["content"])
    crlf = {"path": APP["path"], "content": APP["content"].replace("\n", "\r\n")}
    script = Script({"f2.coder": [{"files": [APP]}, {"files": [crlf, {"path": "nope.py", "delete": True}]}]})
    dev(tmp_path, script, Runner([FAILED, FAILED, FAILED]), rounds=3).build(SPEC, PLAN3, [])
    assert "back unchanged" in script.prompts["f2.coder"][2]


def test_no_unchanged_note_when_writes_were_dropped_by_the_cap(tmp_path):
    ws = Workspace(tmp_path)
    ws.write(APP["path"], APP["content"])
    extra = [{"path": f"m{i}.py", "content": f"X = {i}\n"} for i in range(3)]
    script = Script({"f2.coder": [{"files": [APP]}, {"files": [APP, APP, APP] + extra}]})
    dev(tmp_path, script, Runner([FAILED, FAILED, FAILED]), rounds=3).build(SPEC, PLAN3, [])
    assert "back unchanged" not in script.prompts["f2.coder"][2]


def test_a_normalised_delete_path_counts_as_a_change(tmp_path):
    ws = Workspace(tmp_path)
    ws.write(APP["path"], APP["content"])
    ws.write("old.py", "x = 1\n")
    script = Script({"f2.coder": [{"files": [APP]}, {"files": [APP, {"path": "./old.py", "delete": True}]}]})
    dev(tmp_path, script, Runner([FAILED, FAILED, FAILED]), rounds=3).build(SPEC, PLAN3, [])
    assert "old.py" not in ws.files() and "back unchanged" not in script.prompts["f2.coder"][2]


def test_entry_that_never_starts_its_server_is_repaired_and_the_coder_told(tmp_path):
    body = ("from http.server import HTTPServer, BaseHTTPRequestHandler\n\n"
            "def run():\n    HTTPServer(('127.0.0.1', 8000), BaseHTTPRequestHandler).serve_forever()\n")
    script = Script({"f2.coder": [{"files": [{"path": "./app.py", "content": body},  # normalised path
                                             {"path": "test_app.py", "content": body}]}]})
    dev(tmp_path, script, Runner([FAILED]), rounds=2).build(SPEC, PLAN3, [])
    ws = Workspace(tmp_path)
    assert ws.read("app.py").endswith('if __name__ == "__main__":\n    run()\n')
    assert ws.read("test_app.py") == body  # only the plan's entry file starts a server
    assert "app.py never started its server" in script.prompts["f2.coder"][1]


def test_entry_missing_its_own_modules_import_is_linked_before_the_tests(tmp_path):
    entry = "def run():\n    return list_items()\n"
    script = Script({"f2.coder": [{"files": [{"path": "app.py", "content": entry},
                                             {"path": "todo.py", "content": "def list_items():\n    return []\n"},
                                             TEST]}]})
    dev(tmp_path, script, Runner([FAILED]), rounds=2).build(SPEC, PLAN3, [])
    assert Workspace(tmp_path).read("app.py") == "from todo import list_items\n" + entry
    assert "added `from todo import list_items` to app.py" in script.prompts["f2.coder"][1]


def test_runner_honours_pytest_setup_and_teardown_names(tmp_path):
    summary, err = _run_runner(tmp_path, {
        "test_app.py": "LOG = []\n\ndef setup_module(module):\n    LOG.append('m')\n\n"
                       "def teardown_module():\n    pass\n\ndef setup_function(function):\n    LOG.append(function.__name__)\n\n"
                       "def teardown_function():\n    LOG.append('down')\n\n"
                       "def test_a():\n    assert LOG == ['m', 'test_a']\n\n"
                       "def test_b():\n    assert LOG == ['m', 'test_a', 'down', 'test_b']\n"})
    assert summary == {"run": 2, "skipped": 0, "failures": 0, "errors": 0}, err


def test_runner_pytest_hooks_edge_cases(tmp_path):
    summary, err = _run_runner(tmp_path, {
        "test_a.py": "LOG = []\n\ndef setUpModule():\n    LOG.append('ut')\n\ndef setup_module():\n    LOG.append('py')\n\n"
                     "def test_only_unittest_name_ran():\n    assert LOG == ['ut']\n",
        "test_b.py": "def setup_module(*, verbose=False):\n    raise RuntimeError('boom')\n\ndef test_never():\n    pass\n"})
    assert summary is not None and summary["run"] >= 1 and summary["errors"] == 1 and summary["failures"] == 0, err
    assert "boom" in err
