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
    from watchtower.tower import _evidence
    assert "- coder unit tests (advisory): FAIL" in _evidence([{"check": "tests", "pass": False}])
