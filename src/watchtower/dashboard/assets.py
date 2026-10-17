"""9d: what the dashboard may serve besides its page and state: its own JavaScript modules (the `web/` folder, .js only)
and the owner's backdrop photos (`<home>/backdrops`, real image files only). Everything is a fixed, validated name under
a fixed folder: no URL decoding, no directory listing, no symlink out, no file of another type."""
from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).parent / "web"
MAX_STATIC = 4 * 1024 * 1024
MAX_BACKDROP = 30 * 1024 * 1024
_PART = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]*$")
_BACKDROP = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._ -]{0,78}\.(jpe?g|png|webp)$", re.I)


def _inside(path: Path, root: Path) -> Path | None:
    """The real file at `path` if it is a regular file whose real location is inside `root`, else None."""
    try:
        real = path.resolve(strict=True)
        return real if real.is_file() and real.is_relative_to(root.resolve(strict=True)) else None
    except (OSError, RuntimeError, ValueError):
        return None


def read_static(rel: str) -> tuple[bytes, str] | None:
    """A .js file under web/ named by a clean relative path, or None. `rel` is the raw URL path after /static/."""
    parts = rel.split("/")
    if not rel or len(parts) > 8 or not all(_PART.match(p) and ".." not in p for p in parts) or not parts[-1].endswith(".js"):
        return None
    real = _inside(WEB.joinpath(*parts), WEB)
    if real is None or real.stat().st_size > MAX_STATIC:
        return None
    return real.read_bytes(), "text/javascript; charset=utf-8"


def _image_type(head: bytes) -> str | None:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def _backdrop_file(folder: Path, name: str) -> tuple[Path, str] | None:
    if not _BACKDROP.match(name):
        return None
    real = _inside(folder / name, folder)
    if real is None or real.stat().st_size > MAX_BACKDROP:
        return None
    with real.open("rb") as f:
        kind = _image_type(f.read(16))
    return (real, kind) if kind else None


def list_backdrops(folder: Path) -> list[str]:
    try:
        names = sorted(p.name for p in Path(folder).iterdir())
    except OSError:
        return []
    return [n for n in names[:200] if _backdrop_file(Path(folder), n)]


def read_backdrop(folder: Path, name: str) -> tuple[bytes, str] | None:
    hit = _backdrop_file(Path(folder), name)
    return (hit[0].read_bytes(), hit[1]) if hit else None
