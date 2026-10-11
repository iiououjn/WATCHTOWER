from watchtower.engine.memory import ContextStore


def test_load_missing_returns_none(conn):
    assert ContextStore(conn).load("f1.worker", "job1") is None


def test_save_then_load(conn):
    store = ContextStore(conn)
    data = {"messages": [{"role": "user", "content": "hi 🗼"}], "step": 2}
    store.save("f1.worker", "job1", data)
    assert store.load("f1.worker", "job1") == data


def test_save_overwrites(conn):
    store = ContextStore(conn)
    store.save("a", "j", {"v": 1})
    store.save("a", "j", {"v": 2})
    assert store.load("a", "j") == {"v": 2}


def test_contexts_are_isolated_per_agent_and_job(conn):
    store = ContextStore(conn)
    store.save("a", "j1", {"v": 1})
    store.save("b", "j1", {"v": 2})
    store.save("a", "j2", {"v": 3})
    assert store.load("a", "j1") == {"v": 1}
    assert store.load("b", "j1") == {"v": 2}
    assert store.load("a", "j2") == {"v": 3}


def test_context_survives_reconnect(settings, conn):
    from watchtower.engine.db import connect
    ContextStore(conn).save("a", "j", {"keep": True})
    fresh = connect(settings.db_path)
    assert ContextStore(fresh).load("a", "j") == {"keep": True}
    fresh.close()
