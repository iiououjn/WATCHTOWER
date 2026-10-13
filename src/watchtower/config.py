from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIERS = {
    "small": "ollama/llama3.2:3b",
    "work": "ollama/qwen2.5-coder:7b",
    "review": "ollama/llama3.2:3b",
}


@dataclass(frozen=True)
class Settings:
    home: Path
    tiers: dict[str, str]
    ollama_url: str = "http://localhost:11434"
    cloud_enabled: bool = False
    default_max_tokens: int = 50_000
    tower_max_tokens: int = 300_000  # local tokens are free; the time cap still bounds a job
    default_max_seconds: int = 3600
    default_max_usd: float = 0.0
    min_free_ram_pct: int = 20
    sandbox_free_ram_pct: int = 35  # below this, the model is unloaded before each sandbox run
    agent_slots: int = 1
    sandbox_image: str = "python:latest"
    num_ctx: int = 6144  # set explicitly so Ollama never silently truncates the system prompt
    max_output_tokens: int = 2048
    online: bool = False  # the Beacon may search the web

    @property
    def db_path(self) -> Path:
        return self.home / "watchtower.db"


_MODEL = re.compile(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*(:[A-Za-z0-9._-]+)?")


def load_settings() -> Settings:
    home = Path(os.environ.get("WATCHTOWER_HOME", Path.home() / ".watchtower"))
    home.mkdir(parents=True, exist_ok=True)
    tiers = dict(DEFAULT_TIERS)
    work = os.environ.get("WATCHTOWER_WORK_MODEL")
    if work:
        if not _MODEL.fullmatch(work):
            raise ValueError(f"WATCHTOWER_WORK_MODEL {work!r} is not an Ollama model name")
        tiers["work"] = f"ollama/{work.removeprefix('ollama/')}"
    return Settings(
        home=home,
        tiers=tiers,
        min_free_ram_pct=int(os.environ.get("WATCHTOWER_MIN_FREE_RAM_PCT", "20")),
        sandbox_image=os.environ.get("WATCHTOWER_SANDBOX_IMAGE", "python:latest"),
        online=os.environ.get("WATCHTOWER_OFFLINE") != "1",
    )
