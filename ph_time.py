"""Philippine Standard Time (Asia/Manila, UTC+8) for attendance."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TZ_PH = ZoneInfo("Asia/Manila")
UTC = timezone.utc


def now_ph() -> datetime:
    """Current instant as timezone-aware Philippine time."""
    return datetime.now(TZ_PH)


def parse_instant(iso_str: str) -> datetime:
    """Parse stored ISO string to an aware UTC (or preserved) instant.

    Naive strings are treated as legacy UTC (Railway ``datetime.now()``).
    """
    s = iso_str.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def ph_now_iso_and_display() -> tuple[str, str]:
    """ISO timestamp (+08:00) for storage and 12h string for API display."""
    n = now_ph()
    return n.isoformat(timespec="seconds"), n.strftime("%I:%M %p")


def fmt_ph_ampm(iso_str: str) -> str:
    """Format a stored ISO datetime as 12h clock in Philippine time."""
    if not iso_str:
        return ""
    return parse_instant(iso_str).astimezone(TZ_PH).strftime("%I:%M %p")


def fmt_ph_sheet_datetime(iso_str: str) -> str:
    """Human-readable stamp for Google Sheets (Philippine time)."""
    if not iso_str:
        return ""
    return parse_instant(iso_str).astimezone(TZ_PH).strftime("%b %d %Y %I:%M %p")


def fmt_ph_iso_local_for_sheet(iso_str: str) -> str:
    """Philippine wall-clock as ``YYYY-MM-DDTHH:MM:SS`` (no ``+08:00``) for Sheets cells."""
    if not iso_str:
        return ""
    dt = parse_instant(iso_str).astimezone(TZ_PH)
    return dt.replace(tzinfo=None).isoformat(timespec="seconds")
