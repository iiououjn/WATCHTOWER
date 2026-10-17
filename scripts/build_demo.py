"""Build the static demo for GitHub Pages into ./site: the 3D office playing a made-up run, no tower behind it.
Usage: uv run python scripts/build_demo.py [outdir]"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from watchtower.dashboard.assets import WEB
from watchtower.dashboard.page import render_page


VERCEL = {"cleanUrls": True, "headers": [{"source": "/(.*)", "headers": [
    {"key": "X-Content-Type-Options", "value": "nosniff"}, {"key": "X-Frame-Options", "value": "DENY"},
    {"key": "Referrer-Policy", "value": "no-referrer"}, {"key": "Permissions-Policy", "value": "camera=(), microphone=(), geolocation=()"}]}]}


def build(out: Path) -> list[str]:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / "index.html").write_text(render_page("demo", demo=True), encoding="utf-8")
    (out / ".nojekyll").write_text("")
    (out / "vercel.json").write_text(json.dumps(VERCEL, indent=2) + "\n")   # headers for hosting on Vercel; GitHub Pages ignores this file
    written = ["index.html"]
    for src in sorted(p for p in WEB.rglob("*.js") if p.is_file()):    # only JavaScript is ever published
        rel = Path("static") / src.relative_to(WEB)
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, out / rel)
        written.append(rel.as_posix())
    shutil.copyfile(WEB / "vendor" / "three" / "LICENSE", out / "static" / "vendor" / "three" / "LICENSE")
    return written


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "site")
    files = build(target)
    print(f"demo built in {target}/ ({len(files)} files)")
