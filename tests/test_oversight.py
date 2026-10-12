import json
import subprocess

import pytest

from watchtower.engine.oversight import security_package, security_scan

BAD = ('import os, subprocess\ndef run(c):\n    os.system(c)\n    subprocess.call(c, shell=True)\n    eval(c)\n'
       'def q(db, n):\n    db.execute("SELECT * FROM t WHERE n = \'%s\'" % n)\n')


def ws(tmp_path, files):
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    return tmp_path


def test_real_bandit_finds_shell_eval_and_sql(tmp_path):
    root = ws(tmp_path, {"app.py": BAD})
    ids = {f["id"] for f in security_scan(root, ["app.py"])}
    assert {"B605", "B602", "B307", "B608"} <= ids


def test_secrets_are_found_in_any_file(tmp_path):
    root = ws(tmp_path, {"app.py": "print('hi')\n", "templates/index.html": "<!-- sk-live-abcdefghijklmnop1234 -->"})
    found = security_scan(root, ["app.py", "templates/index.html"])
    assert [(f["tool"], f["file"], f["severity"]) for f in found] == [("secrets", "templates/index.html", "HIGH")]
    assert "sk-live" not in json.dumps(found)  # the secret itself is never copied into reports


def test_clean_code_passes_and_low_findings_are_notes(tmp_path):
    root = ws(tmp_path, {"app.py": "import subprocess\nprint('ok')\n"})
    pkg = security_package(security_scan(root, ["app.py"]))
    assert pkg.checks_run[-1]["check"] == "security" and pkg.checks_run[-1]["pass"] is True
    assert "B404" in pkg.summary and pkg.validate() == []


def test_high_or_medium_fails(tmp_path):
    pkg = security_package(security_scan(ws(tmp_path, {"app.py": BAD}), ["app.py"]))
    assert pkg.checks_run[-1]["pass"] is False and "B602" in pkg.summary and pkg.validate()


@pytest.mark.parametrize("out", ["not json", '{"results": "x"}', '{"results": [{"test_id": 5}]}'])
def test_garbled_bandit_output_is_a_finding_not_a_crash(tmp_path, out):
    def run(argv, **kw):
        return subprocess.CompletedProcess(argv, 1, out, "")
    found = security_scan(ws(tmp_path, {"app.py": "x = 1\n"}), ["app.py"], run=run)
    assert any(f["tool"] == "bandit" and f["severity"] == "UNKNOWN" for f in found)


def test_bandit_timeout_or_missing_is_an_open_question(tmp_path):
    def hang(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 60)
    pkg = security_package(security_scan(ws(tmp_path, {"app.py": "x = 1\n"}), ["app.py"], run=hang))
    assert pkg.checks_run[-1]["pass"] is True and any("could not run" in q for q in pkg.open_questions)


def test_only_listed_files_are_scanned(tmp_path):
    root = ws(tmp_path, {"app.py": "x = 1\n", "stray.py": BAD})
    assert security_scan(root, ["app.py"]) == []
