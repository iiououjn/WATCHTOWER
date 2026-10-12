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


def manifest_of(root: Path, files: list[str]) -> dict[str, str]:
    return {name: _sha(root / name) for name in sorted(files)}


def manifest_problems(root: Path, manifest: dict[str, str]) -> list[str]:
    """Which released files are changed or missing. Extra files (.DS_Store, an app's own data file) are
    ignored: they are never shipped — deploy copies manifest files only and re-hashes each copy."""
    problems = []
    for name, digest in manifest.items():
        path = root / name
        try:
            if not path.is_file() or path.is_symlink():
                problems.append(f"{name} is missing")
            elif _sha(path) != digest:
                problems.append(f"{name} changed after QA")
        except OSError as e:
            problems.append(f"{name} cannot be read ({type(e).__name__})")
    return problems


class Releases:
    """What passed QA, pinned by file hashes: a deploy ships exactly these bytes or refuses."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def record(self, job_id: str, entry: str, root: Path, files: list[str]) -> None:
        self.record_manifest(job_id, entry, manifest_of(root, files))

    def record_manifest(self, job_id: str, entry: str, manifest: dict[str, str]) -> None:
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
        return manifest_problems(root, release.manifest)
