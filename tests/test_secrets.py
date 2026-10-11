import pytest

from watchtower.engine.governor.secrets import SERVICE, SecretStore


class MemoryBackend:
    def __init__(self):
        self.data = {}

    def get_password(self, service, name):
        return self.data.get((service, name))

    def set_password(self, service, name, value):
        self.data[(service, name)] = value

    def delete_password(self, service, name):
        self.data.pop((service, name), None)


def test_set_and_reveal():
    backend = MemoryBackend()
    store = SecretStore(backend)
    store.set("anthropic", "sk-123")
    assert backend.data[(SERVICE, "anthropic")] == "sk-123"
    assert store.handle("anthropic").reveal() == "sk-123"


def test_handle_never_shows_value():
    store = SecretStore(MemoryBackend())
    store.set("anthropic", "sk-123")
    h = store.handle("anthropic")
    assert "sk-123" not in str(h)
    assert "sk-123" not in repr(h)
    assert f"{h}" == "<secret:anthropic>"


def test_missing_secret():
    with pytest.raises(KeyError):
        SecretStore(MemoryBackend()).handle("nope")


@pytest.mark.parametrize("name,value", [("", "v"), ("n", ""), ("  ", "v")])
def test_rejects_blank(name, value):
    with pytest.raises(ValueError):
        SecretStore(MemoryBackend()).set(name, value)


def test_delete():
    store = SecretStore(MemoryBackend())
    store.set("x", "y")
    store.delete("x")
    with pytest.raises(KeyError):
        store.handle("x")
