from watchtower.engine.buildfloor import SMOKE_SCRIPT, smoke_test
from watchtower.engine.sandbox import SandboxResult


def runner(result):
    calls = []

    def run(cmd):
        calls.append(cmd)
        return result

    return run, calls


def test_http_200_passes():
    run, calls = runner(SandboxResult(0, "SMOKE_STATUS 200\nserving\n", "", False))
    pkg = smoke_test(run, "app.py")
    assert calls == [["python", "-c", SMOKE_SCRIPT, "app.py"]]
    assert pkg.floor == "f3" and pkg.checks_run == [{"check": "http", "pass": True, "status": "200"}]
    assert pkg.validate() == []


def test_no_answer_fails_with_app_output():
    run, _ = runner(SandboxResult(0, "SMOKE_STATUS None\nTraceback: NameError\n", "", False))
    pkg = smoke_test(run, "app.py")
    assert not pkg.checks_run[0]["pass"] and "NameError" in pkg.summary
    assert pkg.validate()


def test_non_200_fails():
    run, _ = runner(SandboxResult(0, "SMOKE_STATUS 500\n", "", False))
    assert not smoke_test(run, "app.py").checks_run[0]["pass"]


def test_script_waits_then_kills_the_app():
    assert "PORT" in SMOKE_SCRIPT and "kill()" in SMOKE_SCRIPT and "127.0.0.1:8000" in SMOKE_SCRIPT


def test_expected_home_text_is_a_soft_check():
    run, calls = runner(SandboxResult(0, "SMOKE_STATUS 200\nSMOKE_TEXT no\n", "", False))
    pkg = smoke_test(run, "app.py", expect="Todo list")
    assert calls == [["python", "-c", SMOKE_SCRIPT, "app.py", "Todo list"]]
    assert pkg.checks_run[-1]["pass"] is True and any("Todo list" in q for q in pkg.open_questions)
    run, _ = runner(SandboxResult(0, "SMOKE_STATUS 200\nSMOKE_TEXT yes\n", "", False))
    assert smoke_test(run, "app.py", expect="Todo list").open_questions == []
