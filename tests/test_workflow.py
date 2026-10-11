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
