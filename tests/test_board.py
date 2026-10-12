from watchtower.engine.board import Board
from watchtower.engine.bus import Bus
from watchtower.engine.governor.audit import AuditLog


def board(conn):
    return Board(Bus(AuditLog(conn)))


def test_empty_board_gives_empty_brief(conn):
    assert board(conn).brief("job1", "f2") == ""


def test_brief_shows_done_upstream_this_floor_and_whats_next(conn):
    b = board(conn)
    b.note("job1", "f1", "done", "research: use sqlite3 for storage")
    b.note("job1", "f2", "doing", "plan: app.py, todo.py, test_todo.py")
    b.note("job1", "f2", "doing", "tests pass in round 2")
    b.note("job1", "f4", "plan", "QA will check: add item, list items")
    brief = b.brief("job1", "f2")
    assert "F1" in brief and "sqlite3" in brief
    assert "tests pass in round 2" in brief and "plan: app.py" in brief
    assert "add item, list items" in brief and "F3" in brief
    assert b.brief("job2", "f2") == ""


def test_brief_is_capped_and_notes_are_cleaned(conn):
    b = board(conn)
    for i in range(50):
        b.note("job1", "f1", "done", f"note {i} " + "x" * 400 + "\x1b[31m")
    brief = b.brief("job1", "f2")
    assert len(brief) <= 600 and "\x1b" not in brief
    assert all(len(n["text"]) <= 300 for n in b.notes("job1"))


def test_memo_answers_appear_for_everyone(conn):
    b = board(conn)
    b.note("job1", "f2", "memo", "F2 asked F1: which storage? → sqlite3 file")
    assert "which storage" in b.brief("job1", "f4")


def test_unknown_floor_or_kind_is_rejected(conn):
    import pytest
    with pytest.raises(ValueError):
        board(conn).note("job1", "f9", "done", "x")
    with pytest.raises(ValueError):
        board(conn).note("job1", "f1", "gossip", "x")


def test_brief_stays_fresh_after_hundreds_of_other_bus_events(conn):
    bus = Bus(AuditLog(conn))
    b = Board(bus)
    for i in range(600):
        bus.publish("agent.wake", {"agent": "x"}, "job1")
    b.note("job1", "f1", "done", "late research note")
    assert "late research note" in b.brief("job1", "f2") and len(b.notes("job1")) == 1


def test_latest_issue_replaces_earlier_done_and_plans_keep_latest(conn):
    b = board(conn)
    b.note("job1", "f3", "done", "app answered 200")
    b.note("job1", "f3", "issue", "app crashed: NameError")
    b.note("job1", "f4", "plan", "QA will check: old")
    b.note("job1", "f4", "plan", "QA will check: new")
    brief = b.brief("job1", "f2")
    assert "crashed" in brief and "answered 200" not in brief
    assert "new" in brief and "old" not in brief


def test_memo_answers_and_whats_next_survive_long_notes(conn):
    b = board(conn)
    for floor in ("f1", "f3", "f4", "f5"):
        b.note("job1", floor, "done", floor + " " + "y" * 290)
    b.note("job1", "f2", "doing", "z" * 290)
    b.note("job1", "f2", "doing", "w" * 290)
    b.note("job1", "f4", "plan", "p" * 290)
    b.note("job1", "f2", "memo", "F2 asked F1: storage? → sqlite3")
    brief = b.brief("job1", "f2")
    assert len(brief) <= 600 and "sqlite3" in brief and "Coming next" in brief


def test_long_memo_questions_never_cut_the_answer(conn):
    b = board(conn)
    b.note("job1", "f2", "memo", "F2 Dev asked F1 Research: " + "q" * 50 + " → " + "A" * 149 + "Z")
    b.note("job1", "f3", "done", "app answered 200")
    brief = b.brief("job1", "f2")
    assert "A" * 149 + "Z" in brief and "F3 Build" in brief


def test_a_floor_keeps_its_own_memo_answer_and_sees_other_floors(conn):
    b = board(conn)
    b.note("job1", "f2", "memo", "F2 Dev asked F4 QA: what? → mine")
    b.note("job1", "f4", "memo", "F4 QA asked F1 Research: x → " + "o" * 150)
    b.note("job1", "f4", "memo", "F4 QA asked F3 Build: y → " + "p" * 150)
    for t in ("a" * 120, "b" * 120):
        b.note("job1", "f5", "issue", t)
    b.note("job1", "f3", "issue", "app crashed")
    brief = b.brief("job1", "f2")
    assert "→ mine" in brief and "crashed" in brief
