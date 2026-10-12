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
