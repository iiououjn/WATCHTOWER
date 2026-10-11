from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIERS = {
    "small": "ollama/llama3.2:3b",
    "work": "ollama/qwen2.5-coder:3b",
    "review": "ollama/llama3.2:3b",
}


@dataclass(frozen=True)
class Settings:
    home: Path
    tiers: dict[str, str]
    ollama_url: str = "http://localhost:11434"
    cloud_enabled: bool = False
    default_max_tokens: int = 50_000
    default_max_seconds: int = 3600
    default_max_usd: float = 0.0

    @property
    def db_path(self) -> Path:
        return self.home / "watchtower.db"


def load_settings() -> Settings:
    home = Path(os.environ.get("WATCHTOWER_HOME", Path.home() / ".watchtower"))
    home.mkdir(parents=True, exist_ok=True)
    return Settings(home=home, tiers=dict(DEFAULT_TIERS))
