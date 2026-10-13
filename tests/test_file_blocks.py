import pytest

from watchtower.engine.model_socket import BadModelOutput, parse_files

TWO = """Here you go.
### FILE: app.py
```python
html = f"<p>{x}</p>\\n"
print("a\\tb")
```
### FILE: test_app.py
```
import unittest
import app
```
### DELETE: old.py
"""


def test_file_blocks_carry_code_without_any_escaping():
    out = parse_files(TWO)
    assert out["files"][0] == {"path": "app.py", "content": 'html = f"<p>{x}</p>\\n"\nprint("a\\tb")\n'}
    assert out["files"][1]["path"] == "test_app.py" and out["files"][2] == {"path": "old.py", "delete": True}
    compile(out["files"][0]["content"], "app.py", "exec")


def test_a_longer_fence_lets_code_contain_backticks():
    text = "### FILE: notes.md\n````markdown\nuse ```python blocks```\n````\n"
    assert parse_files(text)["files"][0]["content"] == "use ```python blocks```\n"


@pytest.mark.parametrize("text", ["no blocks here", "### FILE: app.py\nprint(1)\n", "### FILE: \n```\nx\n```\n"])
def test_no_usable_blocks_means_none(text):
    assert parse_files(text) == {"files": []}


def test_crlf_replies_are_normalised():
    assert parse_files("### FILE: a.py\r\n```python\r\nx = 1\r\n```\r\n")["files"][0]["content"] == "x = 1\n"


def test_ask_files_reads_blocks_falls_back_to_json_and_retries(parts):
    from conftest import fake_response
    from watchtower.engine.model_socket import ModelSocket
    settings, budget, audit = parts

    def sock_with(replies, seen):
        def completion(**kw):
            seen.append(kw)
            return fake_response(replies.pop(0) if len(replies) > 1 else replies[0], 1, 1)
        return ModelSocket(settings, budget, audit, completion_fn=completion, unload_fn=lambda m: None,
                           resident_fn=lambda: [], free_ram_fn=lambda: 100)
    msgs = [{"role": "user", "content": "write it"}]
    seen = []
    assert sock_with([TWO], seen).ask_files("work", msgs, "j")["files"][0]["path"] == "app.py"
    assert "response_format" not in seen[0]  # plain text, not JSON mode
    assert sock_with(['{"files": [{"path": "a.py", "content": "x = 1\\n"}]}'], []).ask_files("work", msgs, "j") \
        == {"files": [{"path": "a.py", "content": "x = 1\n"}]}
    seen = []
    with pytest.raises(BadModelOutput):
        sock_with(["nothing useful"], seen).ask_files("work", msgs, "j")
    assert len(seen) == 2 and "### FILE:" in seen[1]["messages"][-1]["content"]


@pytest.fixture
def parts(conn, settings):
    from watchtower.engine.governor.audit import AuditLog
    from watchtower.engine.governor.budget import Budget
    budget = Budget(conn)
    budget.open("j", 100_000, 3600, 0.0)
    return settings, budget, AuditLog(conn)


def test_the_coder_role_replies_in_file_blocks():
    from watchtower.roles import load_roles
    roles = load_roles()
    assert roles["f2.coder"].reply == "files" and roles["f2.architect"].reply == "json"
    assert "### FILE:" in roles["f2.coder"].prompt and "JSON" not in roles["f2.coder"].prompt


def test_bad_reply_kind_in_a_role_file_is_refused(tmp_path):
    from watchtower.roles import load_roles
    (tmp_path / "r.yaml").write_text("id: x\ntitle: X\nfloor: f2\ntier: work\nprompt: p\nreply: xml\n")
    with pytest.raises(ValueError):
        load_roles(tmp_path)


def test_a_memo_line_travels_with_the_files():
    out = parse_files("### MEMO f3: which port does the sandbox use?\n### FILE: a.py\n```\nx = 1\n```\n")
    assert out["memo"] == {"to": "f3", "question": "which port does the sandbox use?"}
