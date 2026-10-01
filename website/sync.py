"""Cross-device sync: an 8-digit code instead of an account.

A reader asks for a code on one device and types it (or scans its QR code) on
another. Each code owns one small JSON document holding reading progress and
reading settings. Devices push what they have and get back the merge, so every
device converges on the same state no matter who wrote last:

* progress is merged per chapter, and the entry with the newer ``at`` wins;
* settings travel as one object with an ``at`` stamp, and the newer one wins.

There is no password behind a code. What it unlocks is how far someone has read
and which font they like, so the code is the whole credential — anyone holding
it can read and write the same progress. That is the trade the feature makes
for not asking for an email address.

Storage is a single SQLite file (``DWFE_SYNC_DB``). Writes merge inside an
immediate transaction, so two gunicorn workers pushing at once cannot lose
each other's chapters.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import threading
import time

CODE_PATTERN = re.compile(r"^\d{8}$")

# Generous for a reading history (a few hundred chapters), small enough that a
# code cannot be used as free file storage.
MAX_PROGRESS_ENTRIES = 1000
MAX_TEXT = 300
MAX_URL = 600
MAX_KEY = 300

# The settings the reader actually has. Anything else in a pushed document is
# dropped rather than stored and handed to other devices.
SETTING_TYPES: dict[str, tuple[type, ...]] = {
    "theme": (str,),
    "font": (str,),
    "width": (str,),
    "align": (str,),
    "fontSize": (int, float),
    "lineHeight": (int, float),
    "letterSpacing": (int, float),
    "wordSpacing": (int, float),
    "paragraphSpacing": (int, float),
    "focus": (bool,),
    "calm": (bool,),
}


def normalise_code(raw: object) -> str | None:
    """Accept "1234 5678" or "1234-5678" as typed; return the 8 digits or None."""
    if not isinstance(raw, str):
        return None
    digits = re.sub(r"[\s\-]", "", raw)
    return digits if CODE_PATTERN.match(digits) else None


def _number(value: object) -> float | None:
    # bool is an int subclass; True is not a timestamp.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return float(value)


def _text(value: object, limit: int) -> str:
    return value[:limit] if isinstance(value, str) else ""


def clean_progress(raw: object) -> dict:
    """Keep only well-formed progress entries, as reader.js writes them."""
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, dict] = {}
    for key, entry in raw.items():
        if not isinstance(key, str) or not key or len(key) > MAX_KEY or not isinstance(entry, dict):
            continue
        ratio = _number(entry.get("ratio"))
        at = _number(entry.get("at"))
        url = entry.get("url")
        # Only same-site paths: a synced entry becomes a link on another device.
        if ratio is None or at is None or not isinstance(url, str):
            continue
        if not url.startswith("/") or url.startswith("//") or len(url) > MAX_URL:
            continue
        cleaned[key] = {
            "ratio": min(1.0, max(0.0, ratio)),
            "title": _text(entry.get("title"), MAX_TEXT),
            "book": _text(entry.get("book"), MAX_TEXT),
            "url": url,
            "at": at,
        }
    if len(cleaned) > MAX_PROGRESS_ENTRIES:
        newest = sorted(cleaned.items(), key=lambda item: item[1]["at"], reverse=True)
        cleaned = dict(newest[:MAX_PROGRESS_ENTRIES])
    return cleaned


def clean_settings(raw: object) -> dict | None:
    """``{"at": <ms>, "values": {...}}`` with known keys only, or None."""
    if not isinstance(raw, dict):
        return None
    at = _number(raw.get("at"))
    values = raw.get("values")
    if at is None or not isinstance(values, dict):
        return None
    kept = {}
    for name, kinds in SETTING_TYPES.items():
        value = values.get(name)
        if isinstance(value, bool) and bool not in kinds:
            continue
        if isinstance(value, kinds):
            kept[name] = value[:40] if isinstance(value, str) else value
    return {"at": at, "values": kept}


def merge(stored: dict, incoming: dict) -> dict:
    """Combine two sync documents; newest wins per chapter and for settings."""
    progress = dict(stored.get("progress") or {})
    for key, entry in (incoming.get("progress") or {}).items():
        current = progress.get(key)
        if current is None or entry["at"] > current["at"]:
            progress[key] = entry
    if len(progress) > MAX_PROGRESS_ENTRIES:
        progress = clean_progress(progress)

    settings = stored.get("settings")
    offered = incoming.get("settings")
    if offered and (not settings or offered["at"] > settings["at"]):
        settings = offered

    return {"progress": progress, "settings": settings}


class SyncStore:
    """One row per sync code: the code, its merged document and timestamps."""

    def __init__(self, path: str):
        self.path = path
        self._ready = False
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        if not self._ready:
            with self._lock:
                if not self._ready:
                    folder = os.path.dirname(os.path.abspath(self.path))
                    os.makedirs(folder, exist_ok=True)
                    conn = sqlite3.connect(self.path, timeout=10)
                    try:
                        conn.execute(
                            "CREATE TABLE IF NOT EXISTS sync ("
                            " code TEXT PRIMARY KEY,"
                            " data TEXT NOT NULL,"
                            " created_at REAL NOT NULL,"
                            " updated_at REAL NOT NULL)"
                        )
                        conn.commit()
                    finally:
                        conn.close()
                    self._ready = True
        # Autocommit mode: transactions are opened explicitly below.
        return sqlite3.connect(self.path, timeout=10, isolation_level=None)

    def create(self) -> str:
        """Allocate a fresh, unused 8-digit code (never starting with 0)."""
        now = time.time()
        empty = json.dumps({"progress": {}, "settings": None})
        conn = self._connect()
        try:
            for _ in range(50):
                code = str(10_000_000 + secrets.randbelow(90_000_000))
                try:
                    conn.execute(
                        "INSERT INTO sync (code, data, created_at, updated_at) VALUES (?, ?, ?, ?)",
                        (code, empty, now, now),
                    )
                    return code
                except sqlite3.IntegrityError:
                    continue
        finally:
            conn.close()
        raise RuntimeError("could not allocate a sync code")

    def exists(self, code: str) -> bool:
        conn = self._connect()
        try:
            row = conn.execute("SELECT 1 FROM sync WHERE code = ?", (code,)).fetchone()
        finally:
            conn.close()
        return row is not None

    def get(self, code: str) -> dict | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT data, updated_at FROM sync WHERE code = ?", (code,)).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        document = json.loads(row[0])
        document["updated_at"] = row[1]
        return document

    def push(self, code: str, incoming: dict) -> dict | None:
        """Merge ``incoming`` into the stored document and return the result."""
        offered = {
            "progress": clean_progress(incoming.get("progress")),
            "settings": clean_settings(incoming.get("settings")),
        }
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT data FROM sync WHERE code = ?", (code,)).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return None
            merged = merge(json.loads(row[0]), offered)
            now = time.time()
            conn.execute(
                "UPDATE sync SET data = ?, updated_at = ? WHERE code = ?",
                (json.dumps(merged, ensure_ascii=False), now, code),
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
        merged["updated_at"] = now
        return merged
