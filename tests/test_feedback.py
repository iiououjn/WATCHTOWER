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
    huge = [{"test": "test_" + "n" * 300 + str(i), "id": f"m.T.{i}", "kind": "FAIL", "line": "AssertionError: " + "<" * 200,
             "diff": "<" * 400, "whitespace": True} for i in range(20)]
    stuck = STUCK_NOTE.format(names=", ".join(f["test"] for f in huge))
    note = _failure_note(huge, stuck, "<b>" * 300)
    assert len(note) <= NOTE_CAP and "fix the test when it is." in note
