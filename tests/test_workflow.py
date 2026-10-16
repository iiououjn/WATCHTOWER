import pytest

from watchtower.engine.workflow import Step, Workflow


@pytest.fixture
def db(tmp_path):
    return tmp_path / "checkpoints.db"


def counting_steps(calls, fail_b=None):
    def a(data):
        calls["a"] += 1
        return {"a": data["x"] + 1}

    def b(data):
        calls["b"] += 1
        if fail_b and fail_b["on"]:
            raise fail_b["exc"]("boom")
        return {"b": data["a"] + 1}

    return [Step("a", a), Step("b", b)]


def test_runs_steps_in_order_and_merges_data(db):
    calls = {"a": 0, "b": 0}
    wf = Workflow(counting_steps(calls), db)
    result = wf.run("j", {"x": 0})
    assert (result.status, result.data) == ("done", {"x": 0, "a": 1, "b": 2})


@pytest.mark.parametrize("exc", [RuntimeError, KeyboardInterrupt])
def test_crash_then_resume_skips_finished_steps(db, exc):
    calls = {"a": 0, "b": 0}
    fail = {"on": True, "exc": exc}
    wf = Workflow(counting_steps(calls, fail), db)
    with pytest.raises(exc):
        wf.run("j", {"x": 0})
    fail["on"] = False
    result = wf.resume("j")
    assert result.status == "done" and result.data["b"] == 2
    assert calls == {"a": 1, "b": 2}


def test_resume_in_a_new_process_uses_checkpoint(db):
    calls = {"a": 0, "b": 0}
    fail = {"on": True, "exc": RuntimeError}
    first = Workflow(counting_steps(calls, fail), db)
    with pytest.raises(RuntimeError):
        first.run("j", {"x": 5})
    first.close()
    fail["on"] = False
    second = Workflow(counting_steps(calls, fail), db)
    assert second.resume("j").data == {"x": 5, "a": 6, "b": 7}
    assert calls["a"] == 1


def test_pause_between_steps_then_resume(db):
    calls = {"a": 0, "b": 0}
    flag = {"pause": False}

    def a(data):
        calls["a"] += 1
        flag["pause"] = True
        return {"a": 1}

    def b(data):
        calls["b"] += 1
        return {"b": 2}

    wf = Workflow([Step("a", a), Step("b", b)], db, should_pause=lambda job_id: flag["pause"])
    paused = wf.run("j", {})
    assert (paused.status, paused.data, paused.reason) == ("paused", {"a": 1}, "pause requested by owner")
    assert calls == {"a": 1, "b": 0}
    flag["pause"] = False
    assert wf.resume("j").data == {"a": 1, "b": 2}
    assert calls == {"a": 1, "b": 1}


def test_jobs_are_isolated(db):
    calls = {"a": 0, "b": 0}
    wf = Workflow(counting_steps(calls), db)
    assert wf.run("one", {"x": 1}).data["b"] == 3
    assert wf.run("two", {"x": 10}).data["b"] == 12


def test_resume_unknown_job(db):
    wf = Workflow(counting_steps({"a": 0, "b": 0}), db)
    with pytest.raises(KeyError):
        wf.resume("never-ran")


@pytest.mark.parametrize("steps", [[], [Step("a", dict), Step("a", dict)]])
def test_rejects_bad_step_lists(db, steps):
    with pytest.raises(ValueError):
        Workflow(steps, db)


def test_checkpoints_are_written_synchronously(db):
    wf = Workflow(counting_steps({"a": 0, "b": 0}), db)
    seen = {}
    real = wf._graph

    class Spy:
        def invoke(self, payload, config, **kw):
            seen.update(kw)
            return real.invoke(payload, config, **kw)

        def get_state(self, config):
            return real.get_state(config)

    wf._graph = Spy()
    wf.run("j", {"x": 0})
    assert seen.get("durability") == "sync"


def looping_step(log, crash_at=None):
    """A resumable step: three rounds, each saved, like the dev floor's attempts (8b)."""
    def loop(data, progress):
        state = dict(progress.state) or {"round": 0, "seen": []}
        log.append(("enter", dict(progress.state)))
        for r in range(state["round"], 3):
            if crash_at is not None and crash_at["at"] == r:
                raise RuntimeError("killed mid-round")
            state = {"round": r + 1, "seen": state["seen"] + [r]}
            progress.save(state)
        return {"rounds": state["seen"]}
    return Step("loop", loop, resumable=True)


def test_resumable_step_keeps_finished_rounds_after_a_crash(db):
    log, crash = [], {"at": 2}
    first = Workflow([Step("a", lambda d: {"a": 1}), looping_step(log, crash)], db)
    with pytest.raises(RuntimeError):
        first.run("j", {})
    first.close()
    crash["at"] = None
    second = Workflow([Step("a", lambda d: {"a": 1}), looping_step(log, crash)], db)  # a new process
    assert second.resume("j").data == {"a": 1, "rounds": [0, 1, 2]}
    assert log[-1] == ("enter", {"round": 2, "seen": [0, 1]})


def test_progress_is_cleared_when_the_step_finishes_and_on_a_fresh_run(db):
    log, crash = [], {"at": 1}
    wf = Workflow([looping_step(log, crash)], db)
    with pytest.raises(RuntimeError):
        wf.run("j", {})
    crash["at"] = None
    wf.run("j", {})  # a fresh run never inherits an old run's rounds
    assert log[-1] == ("enter", {})
    wf.run("k", {})
    assert wf.run("k", {}).data == {"rounds": [0, 1, 2]} and log[-1] == ("enter", {})


def test_owner_pause_acts_at_the_next_save_inside_a_step(db):
    log, flag = [], {"pause": False}

    def loop(data, progress):
        state = dict(progress.state) or {"round": 0}
        log.append(state["round"])
        for r in range(state["round"], 3):
            flag["pause"] = r == 0 and not progress.state
            progress.save({"round": r + 1})
        return {"done": True}

    wf = Workflow([Step("loop", loop, resumable=True)], db, should_pause=lambda job_id: flag["pause"])
    paused = wf.run("j", {})
    assert paused.status == "paused" and paused.reason == "pause requested by owner"
    flag["pause"] = False
    assert wf.resume("j").data == {"done": True}
    assert log == [0, 1]  # resumed after the saved round, not from the start


def test_clear_drops_saved_progress(db):
    seen = []

    def loop(data, progress):
        seen.append(dict(progress.state))
        if not progress.state:
            progress.save({"round": 1})
            progress.clear()
            raise RuntimeError("out of rounds")
        return {}

    wf = Workflow([Step("loop", loop, resumable=True)], db)
    with pytest.raises(RuntimeError):
        wf.run("j", {})
    with pytest.raises(RuntimeError):
        wf.resume("j")
    assert seen == [{}, {}]


def test_a_finished_step_leaves_no_progress_behind(db):
    import sqlite3
    log, crash = [], {"at": 1}
    wf = Workflow([looping_step(log, crash)], db)
    with pytest.raises(RuntimeError):
        wf.run("j", {})
    crash["at"] = None
    wf.resume("j")
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM step_progress").fetchone() == (0,)
