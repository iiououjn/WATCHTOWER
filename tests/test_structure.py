"""8d (audit E-S2, E-A3, A-F19): components nothing used are removed, with their dependencies, and stay removed."""
import ast
import dataclasses
import importlib.util
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from watchtower.roles import ROLES_DIR, Role

ROOT = Path(__file__).resolve().parents[1]
REMOVED_MODULES = ["watchtower.engine.tools.hub", "watchtower.engine.tools", "watchtower.engine.governor.secrets",
                   "watchtower.engine.memory"]
REMOVED_DEPS = ["mcp", "keyring"]


@pytest.mark.parametrize("name", REMOVED_MODULES)
def test_removed_modules_stay_removed(name):
    try:
        assert importlib.util.find_spec(name) is None
    except ModuleNotFoundError:  # its parent package is gone too
        pass


@pytest.mark.parametrize("dep", REMOVED_DEPS)
def test_removed_dependencies_stay_removed(dep):
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    assert not [d for d in deps if d.split(">")[0].split("<")[0].split("=")[0].split("[")[0].strip() == dep]
    assert f'\nname = "{dep}"\n' not in (ROOT / "uv.lock").read_text()


def test_roles_carry_no_tool_permissions():  # the Tool Hub is deferred: a role has no tools to grant
    assert "tools" not in {f.name for f in dataclasses.fields(Role)}
    assert not [p.name for p in ROLES_DIR.rglob("*.yaml") if "\ntools:" in p.read_text()]


def test_every_model_tier_is_used_by_a_role():  # A-F19: a tier no role uses is config nobody reads
    from watchtower.config import DEFAULT_TIERS
    from watchtower.roles import load_roles
    used = {r.tier for r in load_roles(tiers=DEFAULT_TIERS).values()}
    assert set(DEFAULT_TIERS) == used


SRC = ROOT / "src" / "watchtower"
SPLIT = ("tower/", "interface/", "floors/f2_dev/devfloor.py", "floors/f2_dev/planner.py",  # 8d: the god objects'
         "floors/f2_dev/writer.py", "floors/f2_dev/app_tests.py")  # new homes keep their lines readable too


def _rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix()


@pytest.mark.parametrize("path", sorted(SRC.rglob("*.py")), ids=_rel)
def test_files_stay_under_500_lines_without_squeezing(path):
    """E-A1: the limit was met by deleting blank lines; a top-level def or class needs two blank lines before it
    (comments directly above count as part of it), and so does the first statement after one."""
    lines = path.read_text().splitlines()
    assert len(lines) < 500
    body = ast.parse(path.read_text()).body
    defs = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for prev, node in zip(body, body[1:]):
        if isinstance(node, defs) or isinstance(prev, defs):
            k = min([d.lineno for d in getattr(node, "decorator_list", [])] + [node.lineno]) - 2
            while k >= 0 and lines[k].lstrip().startswith("#"):
                k -= 1
            assert k >= 1 and not lines[k].strip() and not lines[k - 1].strip(), f"{_rel(path)}:{node.lineno}"
    if _rel(path).startswith(SPLIT):
        assert not [n for n, line in enumerate(lines, 1) if len(line) > 120]


def test_ci_lints_with_ruff_before_the_tests():  # E-S6: CI checked only "pytest passes"
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text()
    assert "uv run ruff check" in workflow and workflow.index("uv run ruff check") < workflow.index("uv run pytest")
    assert "ruff" in tomllib.loads((ROOT / "pyproject.toml").read_text()).get("tool", {})


def test_ruff_finds_nothing():
    pytest.importorskip("ruff")  # a dev dependency; the CI step runs it too
    out = subprocess.run([sys.executable, "-m", "ruff", "check", "--no-cache", "src", "tests"], cwd=ROOT,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stdout[-3000:]


def test_docs_do_not_describe_removed_components_as_built():  # E-D1, E-D2, E-A3
    readme = (ROOT / "README.md").read_text()
    for gone in ("LiteLLM", "MCP", "Keyring", "`review`", "memory.py", "secrets.py", "tower.py "):
        assert gone not in readme, gone
    assert "qwen2.5-coder:7b" in (ROOT / "CONTRIBUTING.md").read_text()
    spec = (ROOT / "docs" / "superpowers" / "specs" / "2026-10-12-watchtower-design.md").read_text()
    assert "### Built and deferred" in spec and "LiteLLM" not in spec
    for part in ("Tool Hub", "Governor secrets", "Memory", "tier-review"):
        assert f"- **{part}**" in spec.split("### Built and deferred")[1].split("## 1.")[0], part
