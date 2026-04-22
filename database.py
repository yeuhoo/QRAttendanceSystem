from __future__ import annotations

import sqlite3
from datetime import datetime

DB_PATH = "attendance.db"


class Database:
    def __init__(self):
        self._init_schema()

    def _conn(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS attendees (
                    id         TEXT PRIMARY KEY,
                    name       TEXT NOT NULL,
                    email      TEXT DEFAULT '',
                    phone      TEXT DEFAULT '',
                    school     TEXT DEFAULT '',
                    position   TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS attendance (
                    attendee_id TEXT PRIMARY KEY,
                    time_in     TEXT,
                    time_out    TEXT,
                    FOREIGN KEY (attendee_id) REFERENCES attendees(id) ON DELETE CASCADE
                );
            """)

    # ── Attendees ──────────────────────────────────────────────────────────────

    def add_attendee(self, id: str, name: str, email: str, phone: str, school: str, position: str):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO attendees (id, name, email, phone, school, position, created_at) VALUES (?,?,?,?,?,?,?)",
                (id, name, email, phone, school, position, datetime.now().isoformat()),
            )

    def get_attendee(self, id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM attendees WHERE id = ?", (id,)).fetchone()
            return dict(row) if row else None

    def get_all_attendees(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT a.id, a.name, a.email, a.phone, a.school, a.position, a.created_at,
                       att.time_in, att.time_out
                FROM attendees a
                LEFT JOIN attendance att ON a.id = att.attendee_id
                ORDER BY a.name COLLATE NOCASE
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_attendee(self, id: str):
        with self._conn() as conn:
            conn.execute("DELETE FROM attendees WHERE id = ?", (id,))

    # ── Attendance ─────────────────────────────────────────────────────────────

    def get_attendance(self, attendee_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM attendance WHERE attendee_id = ?", (attendee_id,)
            ).fetchone()
            return dict(row) if row else None

    def record_time_in(self, attendee_id: str, timestamp: str):
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO attendance (attendee_id, time_in)
                VALUES (?, ?)
                ON CONFLICT(attendee_id) DO UPDATE SET time_in = excluded.time_in
                """,
                (attendee_id, timestamp),
            )

    def record_time_out(self, attendee_id: str, timestamp: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE attendance SET time_out = ? WHERE attendee_id = ?",
                (timestamp, attendee_id),
            )

    def get_all_attendance(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT a.name, a.email, a.phone, a.school, a.position,
                       att.time_in, att.time_out
                FROM attendees a
                LEFT JOIN attendance att ON a.id = att.attendee_id
                ORDER BY COALESCE(att.time_in, 'ZZZZ') ASC
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def reset_attendance(self):
        with self._conn() as conn:
            conn.execute("DELETE FROM attendance")
