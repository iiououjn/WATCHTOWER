import pytest

from watchtower.floors.f4_qa_deploy.releases import Releases


@pytest.fixture
def ws(tmp_path):
    tmp_path = tmp_path / "ws"
    tmp_path.mkdir()
    (tmp_path / "app.py").write_text("print('hi')\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "util.py").write_text("X = 1\n")
    return tmp_path


def test_record_then_verify_clean(conn, ws):
    rel = Releases(conn)
    rel.record("job1", "app.py", ws, ["app.py", "pkg/util.py"])
    got = rel.get("job1")
    assert got.entry == "app.py" and set(got.manifest) == {"app.py", "pkg/util.py"}
    assert rel.verify("job1", ws) == []


def test_verify_reports_changed_missing_and_extra_files(conn, ws):
    rel = Releases(conn)
    rel.record("job1", "app.py", ws, ["app.py", "pkg/util.py"])
    (ws / "app.py").write_text("print('changed')\n")
    (ws / "pkg" / "util.py").unlink()
    (ws / "evil.py").write_text("x")
    problems = rel.verify("job1", ws)
    assert any("app.py" in p and "changed" in p for p in problems)
    assert any("pkg/util.py" in p and "missing" in p for p in problems)
    assert not any("evil.py" in p for p in problems)  # extras never ship: deploy copies manifest files only


def test_rerecord_replaces_and_unknown_job_is_none(conn, ws):
    rel = Releases(conn)
    rel.record("job1", "app.py", ws, ["app.py"])
    rel.record("job1", "app.py", ws, ["app.py", "pkg/util.py"])
    assert len(rel.get("job1").manifest) == 2 and rel.get("nope") is None
    assert rel.verify("nope", ws) == ["job nope has no release"]
