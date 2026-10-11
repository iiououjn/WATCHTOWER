import sys
from pathlib import Path

import pytest

from watchtower.engine.governor.audit import AuditLog
from watchtower.engine.tools.hub import ServerSpec, ToolDenied, ToolError, ToolHub

ECHO = ServerSpec(sys.executable, (str(Path(__file__).parent / "fixtures" / "echo_mcp_server.py"),))


def hub(conn, policy=None, servers=None, timeout=30.0):
    return ToolHub(AuditLog(conn), servers or {"echo": ECHO},
                   policy if policy is not None else {"f1.worker": ["echo.echo"]}, timeout=timeout)


def test_allowed_call_returns_text(conn):
    result = hub(conn).call("f1.worker", "j", "echo", "echo", {"text": "hi 🗼"})
    assert (result.ok, result.text) == (True, "hi 🗼")


def test_list_tools(conn):
    assert set(hub(conn).list_tools("echo")) == {"echo", "fail", "sleep"}


def test_denied_before_server_starts(conn):
    never = {"echo": ServerSpec("/definitely/not/a/binary")}
    with pytest.raises(ToolDenied, match="may not call echo.echo"):
        hub(conn, servers=never).call("f2.worker", "j", "echo", "echo", {"text": "x"})


def test_default_deny_for_unknown_role(conn):
    assert hub(conn).allowed("nobody", "echo", "echo") is False


def test_wildcard_policy(conn):
    h = hub(conn, policy={"f5.reviewer": ["echo.*"]})
    assert h.allowed("f5.reviewer", "echo", "fail") is True
    assert h.allowed("f5.reviewer", "files", "read") is False


def test_tool_error_result_is_not_ok(conn):
    result = hub(conn, policy={"r": ["echo.*"]}).call("r", "j", "echo", "fail", {})
    assert result.ok is False


def test_broken_server_raises_tool_error(conn):
    broken = {"echo": ServerSpec("/definitely/not/a/binary")}
    with pytest.raises(ToolError):
        hub(conn, servers=broken).call("f1.worker", "j", "echo", "echo", {"text": "x"})


def test_unknown_server(conn):
    with pytest.raises(ToolError, match="unknown tool server"):
        hub(conn, policy={"r": ["*"]}).call("r", "j", "nope", "x", {})


def test_hanging_tool_times_out(conn):
    with pytest.raises(ToolError, match="TimeoutError"):
        hub(conn, policy={"r": ["echo.*"]}, timeout=2).call("r", "j", "echo", "sleep", {"seconds": 30})


def test_audit_never_contains_argument_values(conn):
    audit = AuditLog(conn)
    ToolHub(audit, {"echo": ECHO}, {"r": ["echo.*"]}).call("r", "j", "echo", "echo", {"text": "sk-secret-123"})
    assert [e.action for e in audit.entries(job_id="j")] == ["tool_call", "tool_result"]
    raw = " ".join(r[0] for r in conn.execute("SELECT detail FROM audit_log"))
    assert "sk-secret-123" not in raw
    assert "text" in raw
