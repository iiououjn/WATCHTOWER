from watchtower.floors.f2_dev.handoff import f2_handoff

FILES = ["app.py", "test_app.py"]


def test_failing_coder_tests_do_not_block_the_tower_checks():  # run 17: attempts 3-4 never reached F3/F4
    go, reasons = f2_handoff([{"check": "tests", "pass": False, "problems": []}], "app.py", FILES)
    assert go and reasons == ["coder's own unit tests fail (advisory: F3/F4 decide)"]


def test_passing_tests_hand_off_cleanly():
    assert f2_handoff([{"check": "tests", "pass": True, "problems": []}], "app.py", FILES) == (True, [])


def test_tower_problems_still_block():  # stdlib-only and handler-state lint are the tower's own checks
    go, reasons = f2_handoff([{"check": "tests", "pass": False, "problems": ["imports requests"]}], "app.py", FILES)
    assert not go and reasons == ["imports requests"]


def test_missing_entry_blocks():
    go, reasons = f2_handoff([{"check": "tests", "pass": True, "problems": []}], "main.py", FILES)
    assert not go and reasons == ["planned entry file main.py missing"]


def test_garbled_last_round_still_hands_off_the_files_on_disk():
    assert f2_handoff([{"check": "tests", "pass": False, "output": "coder reply had no usable files"}],
                      "app.py", FILES)[0]


def test_no_round_ran_blocks():
    assert f2_handoff([], "app.py", FILES) == (False, ["no F2 test round ran"])


def test_sign_off_evidence_marks_coder_tests_advisory():
    from watchtower.evidence import _evidence
    assert "- coder unit tests (advisory): FAIL" in _evidence([{"check": "tests", "pass": False}])


def test_missing_entry_reaches_the_coder():  # 6s review r2 #3: the gate's verdict replaced the entry message
    from watchtower.floors.f2_dev.handoff import static_feedback
    assert static_feedback(False, ["planned entry file app.py missing"], "app.py", ["main.py"]) == [
        "the planned entry file app.py does not exist; create it"]


def test_static_feedback_fits_one_feedback_item():  # 6s review r2 #6
    from watchtower.floors.f2_dev.devfloor import FEEDBACK_ITEM
    from watchtower.floors.f2_dev.handoff import static_feedback
    (item,) = static_feedback(False, ["x" * 200] * 5, "app.py", ["app.py"])
    assert len(item) <= FEEDBACK_ITEM


def test_board_line_tells_tests_apart_from_static_problems():  # 6s review r2 #4
    from watchtower.floors.f2_dev.handoff import board_line
    checks = [{"check": "tests", "pass": False, "clean": True, "problems": ["imports requests"]}]
    line = board_line(checks, 0, False, ["imports requests"])
    assert line.startswith("unit tests pass after 1 round(s) (attempt 1)") and "blocked: imports requests" in line
    assert board_line([{"check": "tests", "pass": False, "problems": []}], 1, True, ["x"]).startswith(
        "unit tests still fail after 1 round(s) (attempt 2)")
