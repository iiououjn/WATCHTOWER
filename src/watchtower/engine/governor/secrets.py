from __future__ import annotations

SERVICE = "watchtower"


class SecretHandle:
    """A reference to a Keychain secret. Printing or logging it never shows the value."""

    def __init__(self, name: str, store: "SecretStore"):
        self.name = name
        self._store = store

    def reveal(self) -> str:
        return self._store._get(self.name)

    def __str__(self) -> str:
        return f"<secret:{self.name}>"

    __repr__ = __str__


class SecretStore:
    def __init__(self, backend=None):
        if backend is None:
            import keyring as backend
        self._b = backend

    def set(self, name: str, value: str) -> None:
        if not name.strip() or not value:
            raise ValueError("secret name and value must not be blank")
        self._b.set_password(SERVICE, name, value)

    def handle(self, name: str) -> SecretHandle:
        self._get(name)
        return SecretHandle(name, self)

    def delete(self, name: str) -> None:
        self._b.delete_password(SERVICE, name)

    def _get(self, name: str) -> str:
        value = self._b.get_password(SERVICE, name)
        if value is None:
            raise KeyError(name)
        return value
