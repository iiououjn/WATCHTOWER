from pathlib import Path

from watchtower.floors.f2_dev.feedback import NOTE_CAP, STUCK_NOTE, _failure_note, failures

PLAIN = (Path(__file__).parent / "fixtures" / "unittest_report_plain_assert.txt").read_text()


def test_plain_assert_shows_the_failing_source_line():
    found = {f["test"]: f for f in failures(PLAIN)}
    assert found["test_add_todo"]["line"] == "AssertionError: Expected 1 todo item but got 8"
    assert "line 6 in test_add_todo: assert len(todos) == 1" in found["test_add_todo"]["diff"]
    assert "assert list_todos() == []" in found["test_bare"]["diff"]  # bare AssertionError: the line is all there is
    note = _failure_note(list(found.values()))
    assert "assert len(todos) == 1" in note


def test_assert_equal_keeps_its_diff_lines():
    report = ("FAIL: test_x (test_a.T.test_x)\n" + "-" * 70 + "\nTraceback (most recent call last):\n"
              '  File "/w/test_a.py", line 3, in test_x\n    self.assertEqual(a, b)\n'
              "AssertionError: 'ab' != 'ac'\n- ab\n+ ac\n\n")
    (f,) = failures(report)
    assert f["diff"].startswith("- ab") and "line 3" not in f["diff"]


def test_stuck_note_reaches_the_coder_whole():
    names = ", ".join(f"test_{'n' * 40}{i}" for i in range(8))
    stuck = STUCK_NOTE.format(names=names)
    note = _failure_note(failures(PLAIN), stuck)
    assert "fix the test when it is." in note and "database file" in note
    assert len(note) <= NOTE_CAP


def test_worst_case_note_stays_within_the_cap():
    huge = [{"test": "test_" + "n" * 300 + str(i), "id": f"m.T.{i}", "kind": "FAIL",
             "line": "AssertionError: " + "<untrusted" * 20, "diff": "<untrusted" * 40, "whitespace": True}
            for i in range(20)]  # '<untrusted' is what escaping grows
    stuck = STUCK_NOTE.format(names=", ".join(f["test"] for f in huge))
    note = _failure_note(huge, stuck, "<b>" * 300)
    assert len(note) <= NOTE_CAP and "fix the test when it is." in note


def test_stuck_note_caps_each_name_and_keeps_the_advice():
    from watchtower.floors.f2_dev.feedback import stuck_note
    text = stuck_note(["test_" + "n" * 200, "test_b", "test_a"])
    assert "test_a, test_b" in text and "n" * 60 not in text and text.endswith("…") is False
    assert len(text) <= 323 + 120 + 5 and "fix the test when it is." in text


def test_stuck_rows_keep_every_failure():
    from watchtower.floors.f2_dev.feedback import stuck_note
    found = [{"test": f"test_case_number_{i:02}_abcdefghij", "id": f"m.T.{i}", "kind": "FAIL",
              "line": "AssertionError: " + "x" * 110, "diff": "", "whitespace": False} for i in range(7)]
    note = _failure_note(found, stuck_note([f["test"] for f in found]))
    assert all(f"test_case_number_{i:02}" in note for i in range(5)) and "(+2 more failing)" in note


def test_multiline_assert_message_keeps_the_source_line():
    report = ("FAIL: test_x (test_a.test_x)\n" + "-" * 70 + "\nTraceback (most recent call last):\n"
              '  File "/w/test_a.py", line 4, in test_x\n    assert todos == [], f"got\\n{todos}"\n'
              "AssertionError: got\n['a']\n\n")
    (f,) = failures(report)
    assert "line 4 in test_x: assert todos == []" in f["diff"] and "['a']" in f["diff"]


def test_long_ndiff_shows_the_changed_lines_not_context():
    context = "".join(f"  <p>line {i}</p>\n" for i in range(15))
    report = ("FAIL: test_page (test_a.T.test_page)\n" + "-" * 70 + "\nTraceback (most recent call last):\n"
              '  File "/w/test_a.py", line 9, in test_page\n    self.assertEqual(page, want)\n'
              "AssertionError: '<p>line 0</p>\\n...' != '<p>line 0</p>\\n...'\n" + context
              + "- <p>old</p>\n?    ^^^\n+ <p>new</p>\n?    ^^^\n\n")
    (f,) = failures(report)
    assert "- <p>old</p>" in f["diff"] and "+ <p>new</p>" in f["diff"] and "line 3</p>" not in f["diff"]


def test_stuck_rows_with_long_names_keep_the_more_line():
    from watchtower.floors.f2_dev.feedback import stuck_note
    found = [{"test": f"test_{i}_" + "n" * 60, "id": f"m.T.{i}", "kind": "ERROR",
              "line": "ValueError: " + "x" * 150, "diff": "", "whitespace": False} for i in range(9)]
    note = _failure_note(found, stuck_note([f["test"] for f in found]))
    assert "(+4 more failing)" in note and all(f"test_{i}_" in note for i in range(5))
