import os

import pytest

from watchtower.engine.workspace import MAX_FILES, Workspace, WorkspaceError


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    return Workspace(root)


def test_write_and_list_nested(ws):
    assert ws.write("app.py", "print(1)") == "app.py"
    assert ws.write(" static/style.css ", "body{}") == "static/style.css"
    assert ws.files() == ["app.py", "static/style.css"]
    assert ws.read("app.py") == "print(1)"


@pytest.mark.parametrize("bad", ["../../.zshrc", "/etc/x.py", ".env", "a/.hidden/x.py", "", "  ", "x.exe",
                                 "x.sh", "a/../../b.py", "C:\\x.py"])
def test_rejects_unsafe_paths(ws, bad):
    with pytest.raises(WorkspaceError):
        ws.write(bad, "x")


def test_rejects_symlink_escape(ws, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, ws.root / "link")
    with pytest.raises(WorkspaceError):
        ws.write("link/evil.py", "x")
    assert list(outside.iterdir()) == []


def test_rejects_huge_file(ws):
    with pytest.raises(WorkspaceError, match="100 KB"):
        ws.write("big.py", "x" * 100_001)


def test_file_count_cap_allows_overwrites(ws):
    for i in range(MAX_FILES):
        ws.write(f"f{i}.py", "x")
    ws.write("f0.py", "y")
    with pytest.raises(WorkspaceError, match="files"):
        ws.write("one_more.py", "x")


def test_files_ignores_caches_and_dotfiles(ws):
    ws.write("app.py", "x")
    (ws.root / "__pycache__").mkdir()
    (ws.root / "__pycache__" / "app.cpython-312.pyc").write_bytes(b"x")
    (ws.root / ".DS_Store").write_text("x")
    assert ws.files() == ["app.py"]


def test_snapshot_is_truncated(ws):
    ws.write("a.py", "a" * 5000)
    ws.write("b.py", "b" * 5000)
    snap = ws.snapshot(max_chars=3000)
    assert "### a.py" in snap and len(snap) <= 3200 and "(truncated)" in snap


def test_delete_is_validated(ws):
    ws.write("old_test.py", "x")
    ws.delete("old_test.py")
    assert ws.files() == []
    with pytest.raises(WorkspaceError):
        ws.delete("../x.py")


@pytest.mark.parametrize("bad", ["a\x00.py", "x" * 300 + ".py"])
def test_os_level_bad_names_are_workspace_errors(ws, bad):
    with pytest.raises(WorkspaceError):
        ws.write(bad, "x")


@pytest.mark.parametrize("name", ["a\nb.py", "a\rb.py", "a\x1bb.py", "a\tb.py"])
def test_control_characters_in_names_are_refused(tmp_path, name):
    with pytest.raises(WorkspaceError):
        Workspace(tmp_path).write(name, "x = 1\n")
