"""Transactional owned uploads and results. All methods run through a thread adapter."""

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from src.errors import Missing, QuotaExceeded


class Store:
    """SQLite enforces quota, deduplication and expiry atomically across concurrent requests."""

    def __init__(self, path: Path):
        self.path = path

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS uploads (
                    owner TEXT NOT NULL, file_id TEXT NOT NULL, content BLOB NOT NULL,
                    filename TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
                    expires REAL NOT NULL, PRIMARY KEY(owner, file_id)
                );
                CREATE TABLE IF NOT EXISTS results (
                    owner TEXT NOT NULL, file_id TEXT NOT NULL, signature TEXT NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(owner, file_id, signature),
                    FOREIGN KEY(owner, file_id) REFERENCES uploads(owner, file_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS upload_expiry ON uploads(expires);
            """)

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _owner(owner):
        return hashlib.sha256(owner.encode()).hexdigest()

    @staticmethod
    def _usage(db, owner):
        return db.execute("""SELECT
            (SELECT COALESCE(SUM(length(content)), 0) FROM uploads WHERE owner=?) +
            (SELECT COALESCE(SUM(length(CAST(payload AS BLOB))), 0) FROM results WHERE owner=?)""",
                          (owner, owner)).fetchone()[0]

    def put(self, owner, filename, data, width, height, ttl, quota):
        key = self._owner(owner)
        file_id = hashlib.sha256(key.encode() + b"\0" + data).hexdigest()[:32]
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM uploads WHERE expires <= ?", (time.time(),))
            found = db.execute("SELECT *, length(content) AS size_bytes FROM uploads WHERE owner=? AND file_id=?",
                               (key, file_id)).fetchone()
            if found:
                return self._metadata(found)
            if self._usage(db, key) + len(data) > quota:
                raise QuotaExceeded("Your OCR storage quota is full. Wait for uploads to expire.")
            expires = time.time() + ttl
            db.execute("INSERT INTO uploads VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (key, file_id, data, filename, width, height, expires))
            return {"file_id": file_id, "width": width, "height": height,
                    "size_bytes": len(data), "expires_at": expires}

    @staticmethod
    def _metadata(row):
        return {"file_id": row["file_id"], "width": row["width"], "height": row["height"],
                "size_bytes": row["size_bytes"], "expires_at": row["expires"]}

    def get(self, owner, file_id, *, content=False):
        with self._connection() as db:
            fields = "*, length(content) AS size_bytes" if content else (
                "file_id, width, height, expires, length(content) AS size_bytes")
            row = db.execute(f"SELECT {fields} FROM uploads WHERE owner=? AND file_id=? AND expires>?",
                             (self._owner(owner), file_id, time.time())).fetchone()
            if row is None:
                raise Missing("That upload expired or does not exist. Upload the image again.")
            return row["content"] if content else self._metadata(row)

    def get_result(self, owner, file_id, signature):
        with self._connection() as db:
            row = db.execute("""SELECT payload FROM results JOIN uploads USING(owner, file_id)
                WHERE owner=? AND file_id=? AND signature=? AND expires>?""",
                             (self._owner(owner), file_id, signature, time.time())).fetchone()
            return json.loads(row[0]) if row else None

    def put_result(self, owner, file_id, signature, payload, quota):
        key = self._owner(owner)
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            found = db.execute("SELECT 1 FROM uploads WHERE owner=? AND file_id=? AND expires>?",
                               (key, file_id, time.time())).fetchone()
            if not found:
                raise Missing("That upload expired. Upload the image again.")
            old = db.execute("SELECT length(CAST(payload AS BLOB)) FROM results "
                             "WHERE owner=? AND file_id=? AND signature=?", (key, file_id, signature)).fetchone()
            if self._usage(db, key) - (old[0] if old else 0) + len(encoded.encode()) > quota:
                raise QuotaExceeded("Your OCR storage quota is full. Wait for uploads to expire.")
            db.execute("INSERT OR REPLACE INTO results VALUES (?, ?, ?, ?)", (key, file_id, signature, encoded))

    def sweep(self, now=None):
        with self._connection() as db:
            return db.execute("DELETE FROM uploads WHERE expires<=?", (time.time() if now is None else now,)).rowcount
