from __future__ import annotations

import json
import subprocess
import sys
import tempfile
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
    try:  # -I and an empty cwd: Python never imports a planted bandit.py/json.py; --ignore-nosec: no opt-outs
        with tempfile.TemporaryDirectory(prefix="wt-bandit-") as cwd:
            proc = run([sys.executable, "-I", "-m", "bandit", "-q", "--ignore-nosec", "-f", "json",
                        *[str(root / f) for f in py]], capture_output=True, text=True, timeout=BANDIT_TIMEOUT, cwd=cwd)
    except (OSError, subprocess.SubprocessError) as e:
        return [{"tool": "bandit", "id": "-", "severity": "UNKNOWN", "confidence": "-", "file": "-", "line": 0,
                 "text": f"Bandit could not run ({type(e).__name__})"}]
    try:
        data = json.loads(proc.stdout or "")
        results, errors = data["results"], data.get("errors") or []
        if not isinstance(results, list) or not isinstance(errors, list):
            raise ValueError
        out = [{"tool": "bandit", "id": "-", "severity": "UNKNOWN", "confidence": "-", "file": "-", "line": 0,
                "text": f"Bandit could not parse a file ({str(e.get('reason', ''))[:80]})"}
               for e in errors[:3] if isinstance(e, dict)]
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
        try:
            text = (root / name).read_text(errors="replace")
        except OSError as e:
            found.append({"tool": "secrets", "id": "-", "severity": "UNKNOWN", "confidence": "-", "file": name,
                          "line": 0, "text": f"could not read file ({type(e).__name__})"})
            continue
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


def _line(f: dict) -> str:
    return f"- [{f['severity']}] {f['id']} {f['file']!r}:{f['line']} {str(f['text'])[:120]}"


def security_package(findings: list[dict]) -> WorkPackage:
    """Serious findings first (they are what the coder must fix), then tool problems, then at most 5 minor."""
    failing = [f for f in findings if _failing(f)]
    unknown = [f for f in findings if f["severity"] == "UNKNOWN"]
    minor = [f for f in findings if f not in failing and f not in unknown]
    lines = [_line(f) for f in failing[:10] + unknown[:3] + minor[:5]]
    lines += [f"(+{len(minor) - 5} more minor)"] if len(minor) > 5 else []
    summary = (f"Security scan {'FAILED' if failing else 'passed'}: {len(failing)} serious, "
               f"{len(minor)} minor finding(s)\n" + "\n".join(lines))
    questions = [f"security scan could not run fully: {f['text']}" for f in unknown]
    questions += [f"{len(failing)} serious security finding(s) must be fixed"] if failing else []
    return WorkPackage("f5", summary, [], [], [{"check": "security", "pass": not failing,
                                                "findings": findings[:MAX_FINDINGS]}], questions)
