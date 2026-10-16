import re
from pathlib import Path

import pytest

from watchtower.config import Settings, load_settings

ROOT = Path(__file__).resolve().parent.parent
PINNED = re.compile(r"[a-z0-9./_-]+(:[A-Za-z0-9._-]+)?@sha256:[0-9a-f]{64}")
DIGEST = "sha256:" + "a" * 64


def test_default_sandbox_image_is_pinned_by_digest(monkeypatch, tmp_path):
    """8a (audit D-M7, E-S7): python:latest changed the sandbox and deploy base under the tower on every pull."""
    monkeypatch.setenv("WATCHTOWER_HOME", str(tmp_path))
    monkeypatch.delenv("WATCHTOWER_SANDBOX_IMAGE", raising=False)
    default = Settings.__dataclass_fields__["sandbox_image"].default
    assert PINNED.fullmatch(default) and "latest" not in default
    assert load_settings().sandbox_image == default


@pytest.mark.parametrize("image", ["python:latest", "python:3.14", "--privileged", "python@sha256:abc",
                                   f"python:3.14@{DIGEST}\nRUN curl x", f"-v /:/h python@{DIGEST}"])
def test_an_unpinned_or_odd_image_override_is_refused(monkeypatch, tmp_path, image):
    monkeypatch.setenv("WATCHTOWER_HOME", str(tmp_path))
    monkeypatch.setenv("WATCHTOWER_SANDBOX_IMAGE", image)
    with pytest.raises(ValueError, match="WATCHTOWER_SANDBOX_IMAGE"):
        load_settings()


def test_a_digest_pinned_override_is_used(monkeypatch, tmp_path):
    monkeypatch.setenv("WATCHTOWER_HOME", str(tmp_path))
    monkeypatch.setenv("WATCHTOWER_SANDBOX_IMAGE", f"python:3.12-slim@{DIGEST}")
    assert load_settings().sandbox_image == f"python:3.12-slim@{DIGEST}"


def test_the_project_python_is_pinned():
    """8a (audit E-S5): with no .python-version a fresh uv picked 3.13; the project and CI are on 3.12."""
    assert (ROOT / ".python-version").read_text().strip() == "3.12"
    ci = (ROOT / ".github" / "workflows" / "tests.yml").read_text()
    assert "uv sync --locked" in ci  # uv reads .python-version itself
