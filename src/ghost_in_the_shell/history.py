"""Local history of requests, commands, runs and feedback.

Stored in SQLite under the user's state folder; nothing leaves the machine.
All queries use parameters, so request and command text is never part of SQL.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id         INTEGER PRIMARY KEY,
    created    TEXT NOT NULL,
    mode       TEXT NOT NULL CHECK (mode IN ('ask', 'explain')),
    folder     TEXT NOT NULL,
    request    TEXT NOT NULL,
    command    TEXT NOT NULL,
    level      TEXT NOT NULL,
    ran        INTEGER NOT NULL DEFAULT 0,
    exit_code  INTEGER,
    feedback   INTEGER CHECK (feedback IN (-1, 1))
);
CREATE INDEX IF NOT EXISTS entries_created ON entries (created);
"""


@dataclass(frozen=True)
class Entry:
    id: int
    created: datetime
    mode: str
    folder: str
    request: str
    command: str
    level: str
    ran: bool
    exit_code: int | None
    feedback: int | None


class History:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def add(self, mode: str, folder: Path, request: str, command: str, level: str) -> int:
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO entries (created, mode, folder, request, command, level) VALUES (?, ?, ?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), mode, str(folder), request, command, level),
            )
            return int(cursor.lastrowid)

    def record_run(self, entry_id: int, command: str, level: str, exit_code: int | None) -> None:
        """Store the command as it was run (the user may have edited it)."""
        with self._connect() as db:
            db.execute("UPDATE entries SET ran = 1, command = ?, level = ?, exit_code = ? WHERE id = ?",
                       (command, level, exit_code, entry_id))

    def set_feedback(self, entry_id: int, value: int | None) -> None:
        if value not in (-1, 1, None):
            raise ValueError("feedback must be -1, 1 or None")
        with self._connect() as db:
            db.execute("UPDATE entries SET feedback = ? WHERE id = ?", (value, entry_id))

    def recent(self, limit: int = 50, search: str = "") -> list[Entry]:
        query = "SELECT * FROM entries"
        params: list = []
        if search:
            # Escape LIKE wildcards so that "%" or "_" in the search are literal.
            pattern = "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            query += " WHERE request LIKE ? ESCAPE '\\' OR command LIKE ? ESCAPE '\\'"
            params += [pattern, pattern]
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        return [Entry(r[0], datetime.fromisoformat(r[1]), r[2], r[3], r[4], r[5], r[6], bool(r[7]), r[8], r[9])
                for r in rows]

    def stats(self) -> dict[str, int]:
        with self._connect() as db:
            total, ran, up, down = db.execute(
                "SELECT COUNT(*), COALESCE(SUM(ran), 0), "
                "COALESCE(SUM(feedback = 1), 0), COALESCE(SUM(feedback = -1), 0) FROM entries"
            ).fetchone()
        return {"total": total, "ran": ran, "helpful": up, "not_helpful": down}

    def clear(self) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM entries")
