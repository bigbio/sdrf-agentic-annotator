from __future__ import annotations
import sqlite3
from pathlib import Path
from .models import STATUSES

_COLS = ["accession", "repository", "status", "annotatability", "worker_id",
         "lease_expires_at", "content_hash", "confidence", "route", "block_reason"]

class Ledger:
    def __init__(self, db_path):
        self.db_path = str(db_path)

    def _conn(self):
        c = sqlite3.connect(self.db_path, isolation_level=None)  # autocommit; explicit txns below
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def init_db(self):
        with self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS datasets(
                accession TEXT PRIMARY KEY, repository TEXT, status TEXT DEFAULT 'candidate',
                annotatability REAL DEFAULT 0, worker_id TEXT, lease_expires_at REAL,
                content_hash TEXT, confidence REAL, route TEXT, block_reason TEXT)""")

    def add_candidates(self, rows) -> int:
        n = 0
        with self._conn() as c:
            for r in rows:
                cur = c.execute(
                    "INSERT OR IGNORE INTO datasets(accession, repository, annotatability, status) "
                    "VALUES(?,?,?, 'candidate')",
                    (r["accession"], r["repository"], float(r.get("annotatability", 0))))
                n += cur.rowcount
        return n

    def claim(self, worker_id, n, lease_seconds, now) -> list:
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            rows = c.execute(
                "SELECT accession FROM datasets WHERE status='candidate' "
                "ORDER BY annotatability DESC, accession ASC LIMIT ?", (n,)).fetchall()
            accs = [r["accession"] for r in rows]
            for a in accs:
                c.execute("UPDATE datasets SET status='claimed', worker_id=?, lease_expires_at=? "
                          "WHERE accession=?", (worker_id, now + lease_seconds, a))
            c.execute("COMMIT")
        return accs

    def set_status(self, accession, status, **fields):
        assert status in STATUSES, status
        sets = ["status=?"]; vals = [status]
        for k, v in fields.items():
            assert k in _COLS, k
            sets.append(f"{k}=?"); vals.append(v)
        vals.append(accession)
        with self._conn() as c:
            c.execute(f"UPDATE datasets SET {', '.join(sets)} WHERE accession=?", vals)

    def get(self, accession):
        with self._conn() as c:
            r = c.execute("SELECT * FROM datasets WHERE accession=?", (accession,)).fetchone()
            return dict(r) if r else None

    def reclaim_expired(self, now) -> int:
        with self._conn() as c:
            cur = c.execute("UPDATE datasets SET status='candidate', worker_id=NULL, lease_expires_at=NULL "
                            "WHERE status='claimed' AND lease_expires_at < ?", (now,))
            return cur.rowcount

    def counts(self) -> dict:
        with self._conn() as c:
            return {r["status"]: r["n"] for r in
                    c.execute("SELECT status, COUNT(*) n FROM datasets GROUP BY status")}
