import pytest

from watchtower.engine.jobs import JobStore


def test_create_and_get(conn):
    store = JobStore(conn)
    job = store.create("  build a todo app  ")
    assert job.prompt == "build a todo app"
    assert job.status == "queued"
    assert store.get(job.id) == job


@pytest.mark.parametrize("bad", ["", "   ", "\n\t"])
def test_create_rejects_empty_prompt(conn, bad):
    with pytest.raises(ValueError, match="empty"):
        JobStore(conn).create(bad)


def test_set_status_and_error(conn):
    store = JobStore(conn)
    job = store.create("x")
    store.set_status(job.id, "failed", "boom")
    got = store.get(job.id)
    assert got.status == "failed" and got.error == "boom"


def test_set_status_rejects_unknown_status(conn):
    store = JobStore(conn)
    job = store.create("x")
    with pytest.raises(ValueError):
        store.set_status(job.id, "exploded")


def test_set_status_missing_job(conn):
    with pytest.raises(KeyError):
        JobStore(conn).set_status("nope", "done")


def test_list_newest_first_and_scoped(conn):
    mine = JobStore(conn)
    other = JobStore(conn, user_id="someone-else")
    a = mine.create("a")
    b = mine.create("b")
    other.create("c")
    assert [j.id for j in mine.list()] == [b.id, a.id]


def test_unicode_prompt_roundtrip(conn):
    store = JobStore(conn)
    job = store.create("बनाओ 🗼 app")
    assert store.get(job.id).prompt == "बनाओ 🗼 app"


def test_paused_status_allowed(conn):
    store = JobStore(conn)
    job = store.create("x")
    store.set_status(job.id, "paused", "low memory")
    assert store.get(job.id).status == "paused"


def test_pause_flag_roundtrip(conn):
    store = JobStore(conn)
    job = store.create("x")
    assert store.pause_requested(job.id) is False
    store.request_pause(job.id)
    assert store.pause_requested(job.id) is True
    store.clear_pause(job.id)
    assert store.pause_requested(job.id) is False


def test_pause_flag_unknown_job(conn):
    store = JobStore(conn)
    with pytest.raises(KeyError):
        store.request_pause("nope")
    with pytest.raises(KeyError):
        store.pause_requested("nope")
