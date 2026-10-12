from watchtower.config import Settings, load_settings


def test_default_sandbox_image_is_the_one_the_owner_has(monkeypatch, tmp_path):
    monkeypatch.setenv("WATCHTOWER_HOME", str(tmp_path))
    monkeypatch.delenv("WATCHTOWER_SANDBOX_IMAGE", raising=False)
    assert load_settings().sandbox_image == "python:latest"
    assert Settings.__dataclass_fields__["sandbox_image"].default == "python:latest"
