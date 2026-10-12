import json
import subprocess

import pytest

from watchtower.floors.f5_oversight.oversight import security_package, security_scan

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


def test_nosec_comments_cannot_switch_bandit_off(tmp_path):
    root = ws(tmp_path, {"app.py": "def f(x):\n    return eval(x)  # nosec\n"})
    assert any(f["id"] == "B307" for f in security_scan(root, ["app.py"]))


def test_bandit_never_imports_code_from_the_current_folder(tmp_path, monkeypatch):
    evil = tmp_path / "cwd"
    evil.mkdir()
    marker = tmp_path / "pwned"
    (evil / "bandit.py").write_text(f"open({str(marker)!r}, 'w').write('x')\n")
    (evil / "json.py").write_text(f"open({str(marker)!r}, 'w').write('x')\n")
    monkeypatch.chdir(evil)
    root = ws(tmp_path / "w", {"app.py": BAD})
    assert any(f["id"] == "B602" for f in security_scan(root, ["app.py"])) and not marker.exists()


def test_unparseable_files_are_unknown_not_silently_clean(tmp_path):
    out = '{"results": [], "errors": [{"filename": "/x/app.py", "reason": "syntax error"}]}'
    found = security_scan(ws(tmp_path, {"app.py": "x = 1\n"}), ["app.py"],
                          run=lambda argv, **kw: subprocess.CompletedProcess(argv, 0, out, ""))
    assert any(f["severity"] == "UNKNOWN" and "could not parse" in f["text"] for f in found)


def test_unreadable_file_is_a_finding_not_a_crash(tmp_path):
    root = ws(tmp_path, {"app.py": "x = 1\n"})
    found = security_scan(root, ["app.py", "gone.html"])
    assert any(f["severity"] == "UNKNOWN" and f["file"] == "gone.html" for f in found)


def test_serious_findings_come_first_and_minor_ones_are_capped():
    low = [{"tool": "bandit", "id": f"B{i:03}", "severity": "LOW", "confidence": "HIGH", "file": "a.py",
            "line": i, "text": "minor " * 20} for i in range(20)]
    high = {"tool": "bandit", "id": "B602", "severity": "HIGH", "confidence": "HIGH", "file": "a.py",
            "line": 99, "text": "shell=True"}
    pkg = security_package(low + [high])
    lines = pkg.summary.splitlines()
    assert "B602" in lines[1] and len(pkg.summary) <= 2500 and "more minor" in pkg.summary


def test_guardrails_choose_which_severities_fail():
    medium = {"tool": "bandit", "id": "B608", "severity": "MEDIUM", "confidence": "MEDIUM", "file": "a.py",
              "line": 1, "text": "sql"}
    assert security_package([medium]).checks_run[-1]["pass"] is False
    assert security_package([medium], fail_on=("HIGH",)).checks_run[-1]["pass"] is True
