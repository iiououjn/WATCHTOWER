"""9a: `watchtower dashboard` starts the read-only page on loopback and nothing else."""
from cli_kit import *  # noqa: F403 — runner, home fixture

from watchtower.engine.db import connect
from watchtower.interface import dashboard_cmds


class _Fake:
    server_address = ("127.0.0.1", 8765)

    def serve_forever(self):
        raise KeyboardInterrupt

    def server_close(self):
        self.closed = True


def test_it_prints_the_loopback_url_and_stops_on_ctrl_c(home, monkeypatch):
    connect(home / "watchtower.db").close()
    seen = {}
    monkeypatch.setattr(dashboard_cmds, "make_server", lambda db, port: seen.update(port=port) or _Fake())
    out = runner.invoke(cli.app, ["dashboard", "--port", "9999"])
    assert out.exit_code == 0 and "http://127.0.0.1:8765" in out.output and seen["port"] == 9999


def test_there_is_no_way_to_bind_another_host(home):
    connect(home / "watchtower.db").close()
    out = runner.invoke(cli.app, ["dashboard", "--host", "0.0.0.0"])
    assert out.exit_code == 2 and "No such option" in out.output


def test_a_busy_port_is_a_clear_exit_2(home, monkeypatch):
    connect(home / "watchtower.db").close()

    def busy(db, port):
        raise OSError("port 1 is in use; try --port <other>")

    monkeypatch.setattr(dashboard_cmds, "make_server", busy)
    out = runner.invoke(cli.app, ["dashboard"])
    assert out.exit_code == 2 and "in use" in out.output


def test_it_never_creates_a_database(home):
    out = runner.invoke(cli.app, ["dashboard"])
    assert out.exit_code == 2 and "no tower database" in out.output and not (home / "watchtower.db").exists()
