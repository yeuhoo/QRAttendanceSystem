from __future__ import annotations

import os
import json
import base64
import logging
import tempfile
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Column layout in the Google Sheet
HEADERS = ["Timestamp", "Full Name", "Name of School", "Position", "Email Address", "Phone / Mobile Number", "time_in", "time_out", "Duration"]
COL_ID   = 1
COL_NAME = 2
COL_TIN  = 7
COL_TOUT = 8
COL_DUR  = 9


def _calc_duration(time_in: str, time_out: str) -> str:
    try:
        diff = datetime.fromisoformat(time_out) - datetime.fromisoformat(time_in)
        h, rem = divmod(int(diff.total_seconds()), 3600)
        return f"{h}h {rem // 60}m"
    except Exception:
        return ""


def _resolve_credentials_dict() -> dict | None:
    """
    Returns the credentials as a dict, or None.
    Supports two sources:
      1. GOOGLE_CREDENTIALS_JSON env var — base64-encoded JSON (for Railway/cloud)
      2. GOOGLE_CREDENTIALS_FILE env var — local file path (for local dev)
    """
    # Cloud: credentials stored as base64-encoded JSON in env var
    creds_b64 = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
    if creds_b64:
        try:
            creds_json = base64.b64decode(creds_b64).decode("utf-8")
            return json.loads(creds_json)
        except Exception as exc:
            logger.error("Failed to decode GOOGLE_CREDENTIALS_JSON: %s", exc)
            return None

    # Local: credentials file path
    creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
    if os.path.exists(creds_file):
        try:
            with open(creds_file) as f:
                return json.load(f)
        except Exception as exc:
            logger.error("Failed to read credentials file: %s", exc)
            return None

    return None


class SheetsManager:
    def __init__(self):
        self.enabled = os.getenv("GOOGLE_SHEETS_ENABLED", "false").lower() == "true"
        self.spreadsheet_id = os.getenv("GOOGLE_SPREADSHEET_ID", "")
        self.gc = None

        if not self.enabled:
            return

        creds_dict = _resolve_credentials_dict()
        if not creds_dict:
            logger.warning("Google Sheets enabled but no credentials found. Disabling Sheets sync.")
            self.enabled = False
            return

        try:
            creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
            self.gc = gspread.authorize(creds)
            logger.info("Google Sheets integration enabled (spreadsheet: %s)", self.spreadsheet_id)
        except Exception as exc:
            logger.error("Google Sheets init failed: %s", exc)
            self.enabled = False
            return

        try:
            self._ensure_headers()
        except Exception as exc:
            logger.warning("Google Sheets headers check failed (will retry on write): %s", exc)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _sheet(self):
        if not self.gc:
            return None
        try:
            return self.gc.open_by_key(self.spreadsheet_id).sheet1
        except Exception as exc:
            logger.error("Cannot open spreadsheet: %s", exc)
            return None

    def _ensure_headers(self):
        sheet = self._sheet()
        if sheet is None:
            return
        first_row = sheet.row_values(1)
        if not first_row or first_row[0] != HEADERS[0]:
            sheet.insert_row(HEADERS, 1)

    def _ensure_headers_before_write(self):
        """Re-check headers at write time in case startup had no sheet access yet."""
        try:
            self._ensure_headers()
        except Exception as exc:
            logger.warning("Could not ensure headers: %s", exc)

    # ── Public API ─────────────────────────────────────────────────────────────

    def upsert_attendance(self, attendee: dict, time_in: str | None, time_out: str | None):
        """Write or update a row for this attendee. Safe to call even if Sheets is disabled."""
        if not self.enabled:
            return
        sheet = self._sheet()
        if sheet is None:
            return
        self._ensure_headers_before_write()

        try:
            attendee_id = attendee["id"]
            duration = _calc_duration(time_in, time_out) if time_in and time_out else ""

            # Timestamp = time_in formatted nicely, or now
            try:
                ts = datetime.fromisoformat(time_in).strftime("%b %d %Y %I:%M %p") if time_in else ""
            except Exception:
                ts = time_in or ""

            row_data = [
                ts,
                attendee.get("name", ""),
                attendee.get("school", ""),
                attendee.get("position", ""),
                attendee.get("email", ""),
                attendee.get("phone", ""),
                time_in or "",
                time_out or "",
                duration,
            ]

            # Search column E (email) for existing row (skip header in row 1)
            all_emails = sheet.col_values(5)  # Column E = Email Address
            email = attendee.get("email", "").lower()
            match_row = None
            for i, val in enumerate(all_emails[1:], start=2):  # skip header
                if val.strip().lower() == email:
                    match_row = i
                    break

            if match_row:
                sheet.update(f"A{match_row}:I{match_row}", [row_data])
            else:
                sheet.append_row(row_data, value_input_option="RAW")

        except Exception as exc:
            logger.error("Failed to upsert attendance in Sheets: %s", exc)
