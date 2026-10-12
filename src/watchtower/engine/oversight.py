from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

from watchtower.engine.beacon.glass import SECRET
from watchtower.engine.floor import WorkPackage

BANDIT_TIMEOUT = 60
FAILING = {"HIGH", "MEDIUM"}
MAX_FINDINGS = 20


def _bandit(root: Path, files: list[str], run: Callable) -> list[dict]:
    """Bandit only parses the code (it never runs it). Any tool problem becomes an UNKNOWN finding."""
    py = [f for f in files if f.endswith(".py")]
    if not py:
        return []
    try:
        proc = run([sys.executable, "-m", "bandit", "-q", "-f", "json", *[str(root / f) for f in py]],
                   capture_output=True, text=True, timeout=BANDIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as e:
        return [{"tool": "bandit", "id": "-", "severity": "UNKNOWN", "confidence": "-", "file": "-", "line": 0,
                 "text": f"Bandit could not run ({type(e).__name__})"}]
    try:
        results = json.loads(proc.stdout or "")["results"]
        if not isinstance(results, list):
            raise ValueError
        out = []
        for r in results:
            name = Path(str(r["filename"])).resolve()
            out.append({"tool": "bandit", "id": str(r["test_id"])[:10], "severity": str(r["issue_severity"]).upper(),
                        "confidence": str(r["issue_confidence"]).upper(),
                        "file": name.relative_to(root.resolve()).as_posix() if name.is_relative_to(root.resolve())
                        else name.name, "line": int(r["line_number"]), "text": str(r["issue_text"])[:160]})
        return out
    except (ValueError, KeyError, TypeError):
        detail = "Bandit is not installed" if "No module named" in (proc.stderr or "") else "Bandit output unreadable"
        return [{"tool": "bandit", "id": "-", "severity": "UNKNOWN", "confidence": "-", "file": "-", "line": 0,
                 "text": f"{detail}; Bandit could not run properly"}]


def _secrets(root: Path, files: list[str]) -> list[dict]:
    found = []
    for name in files:
        text = (root / name).read_text(errors="replace")
        for no, line in enumerate(text.splitlines(), start=1):
            if SECRET.search(line):  # report where, never the secret itself
                found.append({"tool": "secrets", "id": "SECRET", "severity": "HIGH", "confidence": "HIGH",
                              "file": name, "line": no, "text": "hard-coded secret or key"})
    return found


def security_scan(root: Path, files: list[str], run: Callable = subprocess.run) -> list[dict]:
    """Floor 5 security worker: Bandit on the Python files plus the Beacon's secret patterns on every file."""
    return (_secrets(root, files) + _bandit(root, files, run))[:MAX_FINDINGS * 2]


def _failing(f: dict) -> bool:
    return f["severity"] in FAILING and f["confidence"] in ("HIGH", "MEDIUM")


def security_package(findings: list[dict]) -> WorkPackage:
    failing = [f for f in findings if _failing(f)]
    unknown = [f for f in findings if f["severity"] == "UNKNOWN"]
    lines = [f"- [{f['severity']}] {f['id']} {f['file']}:{f['line']} {f['text']}" for f in findings[:MAX_FINDINGS]]
    summary = (f"Security scan {'FAILED' if failing else 'passed'}: {len(failing)} serious, "
               f"{len(findings) - len(failing) - len(unknown)} minor finding(s)\n" + "\n".join(lines))
    questions = [f"security scan could not run fully: {f['text']}" for f in unknown]
    questions += [f"{len(failing)} serious security finding(s) must be fixed"] if failing else []
    return WorkPackage("f5", summary, [], [], [{"check": "security", "pass": not failing,
                                                "findings": findings[:MAX_FINDINGS]}], questions)
