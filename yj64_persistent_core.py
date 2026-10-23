"""YJ-64 persistent event, state, task and archive core.

Independent of Kivy. Structured records live in SQLite; a concise human-readable
summary lives beside the database. API credentials must never be stored here.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

SCHEMA = "yj64.persistent_core.v1"
DB_NAME = "yj64_memory.sqlite3"
SUMMARY_NAME = "YJ-64_LOCAL_SKILLS.md"


class PersistentCore:
    """Append-only event journal with mutable state/tasks and portable ZIP archives."""

    def __init__(self, data_dir: str | Path) -> None:
        self.root = Path(data_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / DB_NAME
        self.summary_path = self.root / SUMMARY_NAME
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.db_path), timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    timestamp_ms INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_type_time
                    ON events(event_type, timestamp_ms);
                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_ms INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority TEXT NOT NULL DEFAULT 'normal',
                    roi TEXT NOT NULL DEFAULT '',
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_ms INTEGER NOT NULL,
                    updated_ms INTEGER NOT NULL
                );
            """)
        if not self.summary_path.exists():
            self.summary_path.write_text(
                "# YJ-64 LOCAL SKILLS\n\n"
                "Human-readable semantic summary. Do not store API keys, passwords, "
                "or access tokens here.\n\n"
                "## Operating rules\n"
                "- Keep API context bounded and include only recent messages needed.\n"
                "- Run routine observer ticks locally without LLM calls.\n"
                "- Record route, request-body bytes, history count, duration and result.\n"
                "- Never substitute one participant's answer for another participant.\n",
                encoding="utf-8",
            )

    def record_event(self, event_type: str, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        with self._connect() as db:
            db.execute(
                "INSERT INTO events(event_id,timestamp_ms,event_type,payload_json) VALUES(?,?,?,?)",
                (uuid.uuid4().hex, int(time.time() * 1000), str(event_type), encoded),
            )

    def set_state(self, key: str, value: Any) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO state(key,value_json,updated_ms) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_ms=excluded.updated_ms",
                (str(key), json.dumps(value, ensure_ascii=False, default=str), int(time.time() * 1000)),
            )

    def get_state(self, key: str, default: Any = None) -> Any:
        with self._connect() as db:
            row = db.execute("SELECT value_json FROM state WHERE key=?", (str(key),)).fetchone()
        return json.loads(row["value_json"]) if row else default

    def create_task(
        self, title: str, *, priority: str = "normal", roi: str = "",
        details: dict[str, Any] | None = None,
    ) -> str:
        now = int(time.time() * 1000)
        task_id = uuid.uuid4().hex
        with self._connect() as db:
            db.execute(
                "INSERT INTO tasks(task_id,title,status,priority,roi,details_json,created_ms,updated_ms) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (task_id, str(title), "open", str(priority), str(roi),
                 json.dumps(details or {}, ensure_ascii=False, default=str), now, now),
            )
        return task_id

    def update_task(self, task_id: str, *, status: str | None = None) -> bool:
        if status is None:
            return False
        with self._connect() as db:
            result = db.execute(
                "UPDATE tasks SET status=?,updated_ms=? WHERE task_id=?",
                (str(status), int(time.time() * 1000), str(task_id)),
            )
            return result.rowcount == 1

    def list_tasks(self, status: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM tasks"
        params: tuple[Any, ...] = ()
        if status:
            sql += " WHERE status=?"
            params = (status,)
        sql += " ORDER BY updated_ms DESC"
        with self._connect() as db:
            rows = db.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def export_archive(self, destination: str | Path) -> str:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp_db = self.root / ("export-" + uuid.uuid4().hex + ".sqlite3")
        try:
            with self._connect() as source, sqlite3.connect(str(temp_db)) as target:
                source.backup(target)
            with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.write(temp_db, DB_NAME)
                if self.summary_path.exists():
                    archive.write(self.summary_path, SUMMARY_NAME)
                archive.writestr(
                    "manifest.json",
                    json.dumps({"schema": SCHEMA, "exported_ms": int(time.time() * 1000}),
                               ensure_ascii=False),
                )
        finally:
            try:
                temp_db.unlink()
            except OSError:
                pass
        return str(destination)

    def import_archive(self, source: str | Path) -> int:
        with zipfile.ZipFile(source, "r") as archive:
            names = set(archive.namelist())
            if "manifest.json" not in names or DB_NAME not in names:
                raise ValueError("Archive is missing the YJ-64 manifest or SQLite database")
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            if manifest.get("schema") != SCHEMA:
                raise ValueError("Unsupported YJ-64 archive schema")
            temp_db = self.root / ("import-" + uuid.uuid4().hex + ".sqlite3")
            temp_db.write_bytes(archive.read(DB_NAME))
            try:
                with sqlite3.connect(str(temp_db)) as imported:
                    count = int(imported.execute("SELECT COUNT(*) FROM events").fetchone()[0])
                    imported.execute("SELECT key FROM state LIMIT 1").fetchall()
                with self._connect() as target, sqlite3.connect(str(temp_db)) as source_db:
                    source_db.backup(target)
                if SUMMARY_NAME in names:
                    self.summary_path.write_bytes(archive.read(SUMMARY_NAME))
                return count
            finally:
                try:
                    temp_db.unlink()
                except OSError:
                    pass
