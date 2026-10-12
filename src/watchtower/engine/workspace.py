from __future__ import annotations

from pathlib import Path, PurePosixPath

ALLOWED_SUFFIXES = {".py", ".html", ".css", ".js", ".json", ".md", ".txt", ".sql"}
MAX_FILE_BYTES = 100_000
MAX_FILES = 30


class WorkspaceError(ValueError):
    pass


class Workspace:
    """The only way agent-written files reach disk: inside the job's workspace, nowhere else."""

    def __init__(self, root: Path):
        self.root = root

    def _target(self, path: str) -> tuple[str, Path]:
        raw = (path or "").strip()
        rel = PurePosixPath(raw)
        if not raw or "\\" in raw or rel.is_absolute() or ".." in rel.parts or any(ord(c) < 32 or c == "\x7f" for c in raw):
            raise WorkspaceError(f"unsafe path {path!r}")
        if any(part.startswith(".") for part in rel.parts):
            raise WorkspaceError(f"hidden files are not allowed: {path!r}")
        if rel.suffix not in ALLOWED_SUFFIXES:
            raise WorkspaceError(f"file type {rel.suffix or '(none)'} is not allowed: {path!r}")
        target = self.root / rel
        root = self.root.resolve()
        probe = target
        while not probe.exists() and probe != self.root:
            probe = probe.parent
        if not probe.resolve().is_relative_to(root) or target.is_symlink():
            raise WorkspaceError(f"path escapes the workspace: {path!r}")
        return str(rel), target

    def write(self, path: str, content: str) -> str:
        try:
            return self._write(path, content)
        except (OSError, ValueError) as e:  # NUL bytes, over-long names, odd filesystem states
            if isinstance(e, WorkspaceError):
                raise
            raise WorkspaceError(f"cannot write {path!r}: {type(e).__name__}") from e

    def delete(self, path: str) -> None:
        rel, target = self._target(path)
        if target.is_file() and not target.is_symlink():
            target.unlink()

    def _write(self, path: str, content: str) -> str:
        rel, target = self._target(path)
        if len(content.encode()) > MAX_FILE_BYTES:
            raise WorkspaceError(f"{rel} is larger than 100 KB")
        if not target.exists() and len(self.files()) >= MAX_FILES:
            raise WorkspaceError(f"workspace already has {MAX_FILES} files")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.parent.resolve().is_relative_to(self.root.resolve()):
            raise WorkspaceError(f"path escapes the workspace: {path!r}")
        target.write_text(content)
        return rel

    def files(self) -> list[str]:
        out = []
        for p in sorted(self.root.rglob("*")):
            rel = p.relative_to(self.root)
            if p.is_file() and not p.is_symlink() and not any(
                    part.startswith(".") or part == "__pycache__" for part in rel.parts):
                out.append(rel.as_posix())
        return out

    def read(self, path: str) -> str:
        _, target = self._target(path)
        return target.read_text(errors="replace")

    def snapshot(self, max_chars: int = 6000) -> str:
        parts, used = [], 0
        for name in self.files():
            body = (self.root / name).read_text(errors="replace")
            room = max_chars - used
            if room <= 200:
                parts.append("(truncated: more files not shown)")
                break
            if len(body) > room - 100:
                body = body[: room - 100] + "\n(truncated)"
            block = f"### {name}\n{body}\n"
            parts.append(block)
            used += len(block)
        return "\n".join(parts) or "(no files yet)"
