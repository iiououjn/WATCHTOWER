"""9c: the watchtower scene. A canvas picture of the tower with its staff; same safety rules as the rest of the page."""
import json
import re

from watchtower.dashboard.page import render_page
from watchtower.roles import load_roles

BANNED = ("innerHTML", "outerHTML", "document.write", "eval(", "insertAdjacentHTML", "new Function", "setAttribute('style'",
          "<a ", ".href", "<img", "<iframe", "src=")


def _roster(html: str) -> list[dict]:
    return json.loads(re.search(r"const ROSTER = (\[.*?\]);\n", html, re.S).group(1))


def test_the_page_has_one_full_window_canvas_for_the_scene():
    html = render_page("n")
    assert html.count('<canvas id="scene"') == 1 and 'id="ledger"' in html


def test_the_roster_is_every_role_in_the_org_chart_grouped_by_floor():
    roster = _roster(render_page("n"))
    roles = load_roles()
    assert {r["id"] for r in roster} == set(roles)
    assert all(r["floor"] in ("csuite", "f1", "f2", "f3", "f4", "f5", "glass") for r in roster)
    assert {r["id"]: r["title"] for r in roster} == {i: r.title for i, r in roles.items()}


def test_the_embedded_roster_cannot_break_out_of_the_script_tag(monkeypatch):
    from watchtower import roles
    evil = roles.Role("x.evil", "</script><script>alert(1)</script><!--", "f1", "small", "p")
    monkeypatch.setattr(roles, "load_roles", lambda: {"x.evil": evil})
    html = render_page("n")
    assert "</script><script>alert" not in html and "<!--" not in html.split("const ROSTER")[1].split(";\n")[0]
    assert _roster(html)[0]["title"] == evil.title


def test_the_scene_code_never_writes_html_or_loads_anything():
    html = render_page("n")
    for banned in BANNED:
        assert banned not in html
    assert "fillText" in html and "requestAnimationFrame" in html and "prefers-reduced-motion" in html


def test_the_scene_reads_awake_agents_and_floors_from_the_state():
    html = render_page("n")
    assert "j.awake" in html and "j.floor" in html and "s.deployments" in html


def test_a_failing_scene_cannot_stop_the_ledger_or_the_animation_loop():
    html = render_page("n")
    assert "try { SCENE.update(s); }" in html and html.index("fill($('audit')") < html.index("SCENE.update")
    frame = html.split("function frame(ts)")[1]
    assert frame.index("requestAnimationFrame(frame)") < frame.index("sky()")
