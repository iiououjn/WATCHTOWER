"""Phase 8c (audit C-M5): every F2 prompt stays inside PROMPT_CHARS; Ollama silently drops the head (the spec)."""
from devfloor_kit import HR, Runner, Script, dev, hr_dev, verdict

from watchtower.engine.workspace import Workspace
from watchtower.floors.f2_dev.devfloor import PROMPT_CHARS

HINDI = "प्रविष्टि जोड़ें और सूची दिखाएँ " * 3  # 80+ chars: json.dumps made each one \\uXXXX (6x)
SPEC = {"title": "अतिथि पुस्तिका", "goal": HINDI * 4, "acceptance": [HINDI] * 4, "out_of_scope": [HINDI]}
PLAN = {"files": [{"path": f"pkg{i}/मॉड्यूल_{i:02d}_" + "m" * 70 + ".py", "purpose": HINDI[:80]} for i in range(15)],
        "entry": "app.py", "routes": []}
CHECKS = [{"name": f"c{i}", "method": "POST", "path": "/add", "form": {f"f{j}": "<" * 60 for j in range(10)},
           "expect_status": 200, "expect_text": "<&>" * 30, "expect_escaped": True} for i in range(8)]


def _files(tmp_path):
    for i in range(6):
        Workspace(tmp_path).write(f"mod{i}.py", ("x = 1  # " + "y" * 90 + "\n") * 80)


def test_the_coder_prompt_fits_with_a_non_ascii_plan_and_big_notes(tmp_path):
    _files(tmp_path)
    s = Script({"f2.architect": [{}], "f2.coder": [{"files": []}]})
    dev(tmp_path, s, Runner([verdict(failures=1, exit_code=1)]), rounds=2).build(SPEC, PLAN, ["<" * 600] * 6, CHECKS)
    for prompt in s.prompts["f2.coder"]:
        assert len(prompt) <= PROMPT_CHARS, len(prompt)
        assert "\\u0" not in prompt and "मॉड्यूल_00" in prompt  # paths survive every trim
        assert "### FILE: mod0.py" in prompt  # the coder still sees code


def test_the_unit_prompt_fits(tmp_path):
    _files(tmp_path)
    s = Script({"f2.architect": [{}], "f2.coder": [{"files": []}]})
    dev(tmp_path, s, Runner([verdict()])).write_units(SPEC, PLAN, CHECKS)
    assert s.prompts["f2.coder"] and all(len(p) <= PROMPT_CHARS for p in s.prompts["f2.coder"])


def test_the_hr_prompt_fits(tmp_path):
    _files(tmp_path)
    Workspace(tmp_path).write("test_app.py", "import unittest\nimport mod0\n")
    s = Script({"f2.architect": [{}], "f2.coder": [{"files": []}], HR.id: [{"pass": True, "reason": "ok"}]})
    hr_dev(tmp_path, s, Runner([verdict()]), rounds=1).build(SPEC, PLAN, [], test_first=True)
    assert s.prompts[HR.id] and len(s.prompts[HR.id][0]) <= PROMPT_CHARS, len(s.prompts[HR.id][0])


def test_the_plan_prompt_caps_research_and_feedback_after_escaping(tmp_path):
    from watchtower.floors.f2_dev.prompt_fit import RESEARCH_CHARS
    s = Script({"f2.architect": [{"files": [], "entry": "app.py", "routes": []}], "f2.coder": [{}]})
    floor = dev(tmp_path, s, Runner([verdict()]))
    floor.plan(SPEC, "<" * 1000, [])  # within budget: only the cap trims it
    assert s.prompts["f2.architect"][0].count("&lt;") * 4 <= RESEARCH_CHARS  # capped after escaping, not before
    floor.plan(SPEC, "<" * 20_000, ["<" * 600] * 5, lessons="<" * 800, reference="r" * 10_000)
    assert len(s.prompts["f2.architect"][1]) <= PROMPT_CHARS, len(s.prompts["f2.architect"][1])
