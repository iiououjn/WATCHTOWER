"""8a (audit D-M5): stored and model text reaches the owner's terminal without control or format characters
(OSC title/clipboard/hyperlink sequences, screen rewrites, bidi overrides, zero-width characters)."""
from cli_kit import *  # noqa: F403 — helpers and fixtures

from watchtower.config import load_settings
from watchtower.engine.db import connect
from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.jobs import JobStore
from watchtower.engine.runner import RunOutcome

HOSTILE = "a\x1b]0;pwned\x07b\x1b[2Jc‮d​e⁦f\x9bg\r"
BAD = ("\x1b", "\x07", "‮", "​", "⁦", "\x9b", "\r")


def shown(text):
    return not any(c in text for c in BAD)


def test_clean_strips_control_and_format_characters_but_keeps_text():
    assert cli._clean(HOSTILE + "\nnext\tcol café 中") == "a]0;pwnedb[2Jcdefg\nnext\tcol café 中"


def test_status_cleans_prompt_and_error():
    conn = connect(load_settings().db_path)
    jobs = JobStore(conn)
    job = jobs.create("todo " + HOSTILE)
    jobs.set_status(job.id, "paused", "gate rejected the app: " + HOSTILE)
    out = runner.invoke(cli.app, ["status"]).output
    assert "gate rejected the app" in out and shown(out)


def test_logs_clean_audit_details():  # the detail dict repr escapes these today; _clean keeps it so
    AuditLog(connect(load_settings().db_path)).append("beacon", "glass_reject", {"url": "http://x/" + HOSTILE})
    out = runner.invoke(cli.app, ["logs"]).output
    assert "glass_reject" in out and shown(out)


def test_a_failed_reason_is_cleaned(capsys):
    with pytest.raises(cli.typer.Exit):
        cli._report(RunOutcome("j1", "failed", None, "boom " + HOSTILE), connect(load_settings().db_path))
    err = capsys.readouterr().err
    assert "boom" in err and shown(err)


def test_a_cpo_error_is_cleaned(monkeypatch):
    use_roles(monkeypatch)
    monkeypatch.setattr(cli.JobRunner, "cpo_questions",
                        lambda self, job_id: (_ for _ in ()).throw(RuntimeError("x " + HOSTILE)))
    out = runner.invoke(cli.app, ["research", "compare lighthouse lenses"]).output
    assert "continuing without questions" in out and shown(out)


def test_a_beacon_pause_is_cleaned(monkeypatch):  # review r1: the search error text can carry web content
    class Down:
        def research(self, query, job_id):
            raise cli.SearchUnavailable("down " + HOSTILE)
    monkeypatch.setattr(cli, "make_beacon", lambda settings, conn: Down())
    out = runner.invoke(cli.app, ["beacon", "lenses"]).output
    assert "Beacon paused: down" in out and shown(out)


@pytest.mark.parametrize("args", [["resume", "j1"], ["approve", "j1"]])
def test_a_resume_error_is_cleaned(monkeypatch, args):  # review r1: the error can quote stored job data
    use_roles(monkeypatch)
    monkeypatch.setattr(cli.JobRunner, "resume", lambda self, job_id, **kw: (_ for _ in ()).throw(
        ValueError("stuck " + HOSTILE)))
    if args[0] == "approve":
        conn = connect(load_settings().db_path)
        job = JobStore(conn).create("todo")
        JobStore(conn).set_status(job.id, "paused", "waiting")
        approvals = cli.Approvals(conn)
        approvals.request(job.id, "signoff", "app")
        args = ["approve", job.id]
    out = runner.invoke(cli.app, args).output
    assert "Error: stuck" in out and shown(out)
