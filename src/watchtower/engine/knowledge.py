from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass

from watchtower.engine.db import now

CHUNK_CHARS = 1200
MAX_TERMS = 16
STOPWORDS = frozenset(
    "a an and are as at be but by can do does for from has have how i if in into is it its me my of on "
    "or our so than that the their them then there these they this to us was we were what when where "
    "which who why will with you your about explain describe summarise summarize tell".split()
)


@dataclass(frozen=True)
class Hit:
    doc_id: int
    title: str
    source: str
    snippet: str
    score: float
    trusted: bool
    text: str = ""  # the full matching chunk, for agents; snippet is for display


def _chunks(text: str) -> list[str]:
    chunks, current = [], ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        while len(para) > CHUNK_CHARS:
            chunks.append(para[:CHUNK_CHARS])
            para = para[CHUNK_CHARS:]
        if current and len(current) + len(para) + 2 > CHUNK_CHARS:
            chunks.append(current)
            current = ""
        current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return chunks


class Knowledge:
    """Local knowledge store: chunked full-text search (SQLite FTS5, BM25) with provenance.
    Every chunk keeps its source and a trusted flag; web content is untrusted by default."""

    def __init__(self, conn: sqlite3.Connection, workspace_id: str = "default"):
        self._conn = conn
        self._ws = workspace_id

    def add(self, text: str, source: str, title: str = "", trusted: bool = False) -> int:
        text, source = text.strip(), source.strip()
        if not text or not source:
            raise ValueError("knowledge text and source must not be blank")
        digest = hashlib.sha256(text.encode()).hexdigest()
        row = self._conn.execute(
            "SELECT id FROM knowledge_docs WHERE workspace_id=? AND sha256=?", (self._ws, digest)
        ).fetchone()
        if row:
            return row["id"]
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            doc_id = self._conn.execute(
                "INSERT INTO knowledge_docs(workspace_id, source, title, sha256, trusted, added_at)"
                " VALUES (?,?,?,?,?,?)",
                (self._ws, source, title.strip() or source, digest, int(trusted), now()),
            ).lastrowid
            self._conn.executemany(
                "INSERT INTO knowledge_fts(title, body, doc_id, workspace_id) VALUES (?,?,?,?)",
                [(title, chunk, doc_id, self._ws) for chunk in _chunks(text)],
            )
            self._conn.execute("COMMIT")
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        return doc_id

    def search(self, query: str, limit: int = 5, distinct: bool = True) -> list[Hit]:
        """Best-ranked chunks; distinct=True keeps one hit per document (for display)."""
        terms = [t for t in re.findall(r"\w+", query.lower()) if t not in STOPWORDS][:MAX_TERMS]
        if not terms:
            return []
        match = " OR ".join(f'"{t}"' for t in terms)
        rows = self._conn.execute(
            "SELECT d.id, d.title, d.source, d.trusted,"
            " snippet(knowledge_fts, 1, '[', ']', '…', 12) AS snip, knowledge_fts.body AS body,"
            " bm25(knowledge_fts) AS rank"
            " FROM knowledge_fts JOIN knowledge_docs d ON d.id = knowledge_fts.doc_id"
            " WHERE knowledge_fts MATCH ? AND knowledge_fts.workspace_id = ?"
            " ORDER BY rank LIMIT ?",
            (match, self._ws, limit * 4),
        ).fetchall()
        hits, seen = [], set()
        for r in rows:
            if distinct and r["id"] in seen:
                continue
            seen.add(r["id"])
            hits.append(Hit(r["id"], r["title"], r["source"], r["snip"], -r["rank"], bool(r["trusted"]), r["body"]))
            if len(hits) == limit:
                break
        return hits

    def count(self) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM knowledge_docs WHERE workspace_id=?", (self._ws,)
        ).fetchone()[0]
