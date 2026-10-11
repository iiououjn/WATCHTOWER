import subprocess
from types import SimpleNamespace

from watchtower.engine.system import free_ram_pct


def test_parses_memory_pressure():
    out = "The system has 8589934592 (2097152 pages)...\nSystem-wide memory free percentage: 41%\n"
    assert free_ram_pct(run=lambda *a, **k: SimpleNamespace(stdout=out)) == 41


def test_unreadable_output_is_none():
    assert free_ram_pct(run=lambda *a, **k: SimpleNamespace(stdout="garbage")) is None


def test_missing_tool_is_none():
    def missing(*a, **k):
        raise FileNotFoundError("memory_pressure")

    assert free_ram_pct(run=missing) is None


def test_timeout_is_none():
    def slow(*a, **k):
        raise subprocess.TimeoutExpired("memory_pressure", 10)

    assert free_ram_pct(run=slow) is None
