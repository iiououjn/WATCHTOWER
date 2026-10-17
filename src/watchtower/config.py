from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

# 8a (audit D-M7, E-S7): pinned by digest, so a pull never changes the sandbox and deploy base under the tower.
# Python 3.14.8, the python:latest the owner already had (no pull, no change to any check).
SANDBOX_IMAGE = "python:3.14.8@sha256:b9767f56a1cc620aa72d38cc3557d26412e38a4597c92953476136b78894ccbd"
_PINNED = re.compile(r"[a-z0-9][a-z0-9./_-]*(:[A-Za-z0-9._-]+)?@sha256:[0-9a-f]{64}")  # no leading "-"
DEFAULT_TIERS = {
    "small": "ollama/llama3.2:3b",
    "work": "ollama/qwen2.5-coder:7b",
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
    sandbox_image: str = SANDBOX_IMAGE
    slot_wait_s: int = 600  # a second job waits this long for a slot, then pauses (calls took up to 327 s)
    num_ctx: int = 6144  # set explicitly so Ollama never silently truncates the system prompt
    max_output_tokens: int = 2048
    call_timeout_s: int = 600  # one model call; real replies took up to 327 s on 8 GB (runs 36-39)
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
    image = os.environ.get("WATCHTOWER_SANDBOX_IMAGE", SANDBOX_IMAGE)
    if not _PINNED.fullmatch(image):  # also keeps docker flags and Dockerfile lines out of the image name
        raise ValueError(f"WATCHTOWER_SANDBOX_IMAGE {image!r} must be pinned by digest: name[:tag]@sha256:<64 hex>")
    return Settings(
        home=home,
        tiers=tiers,
        min_free_ram_pct=int(os.environ.get("WATCHTOWER_MIN_FREE_RAM_PCT", "20")),
        sandbox_image=image,
        online=os.environ.get("WATCHTOWER_OFFLINE") != "1",
    )
