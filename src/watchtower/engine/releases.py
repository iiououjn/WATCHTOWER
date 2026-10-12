from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from watchtower.engine.db import now


@dataclass(frozen=True)
class Release:
    job_id: str
    entry: str
    manifest: dict[str, str]
    created_at: str


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Releases:
    """What passed QA, pinned by file hashes: a deploy ships exactly these bytes or refuses."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def record(self, job_id: str, entry: str, root: Path, files: list[str]) -> None:
        manifest = {name: _sha(root / name) for name in sorted(files)}
        self._conn.execute("INSERT OR REPLACE INTO releases(job_id, entry, manifest, created_at) VALUES (?,?,?,?)",
                           (job_id, entry, json.dumps(manifest), now()))

    def get(self, job_id: str) -> Release | None:
        row = self._conn.execute("SELECT * FROM releases WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            return None
        return Release(row["job_id"], row["entry"], json.loads(row["manifest"]), row["created_at"])

    def verify(self, job_id: str, root: Path) -> list[str]:
        release = self.get(job_id)
        if release is None:
            return [f"job {job_id} has no release"]
        problems = []
        for name, digest in release.manifest.items():
            path = root / name
            if not path.is_file() or path.is_symlink():
                problems.append(f"{name} is missing")
            elif _sha(path) != digest:
                problems.append(f"{name} changed after QA")
        present = {p.relative_to(root).as_posix() for p in root.rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts}
        problems += [f"{name} is not in the release" for name in sorted(present - set(release.manifest))]
        return problems
