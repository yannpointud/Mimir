"""
UTC clock of the application.

Timestamps are stored and compared as naive UTC datetimes, since SQLite keeps
no time zone: every caller takes the current time from here.
"""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Current UTC time as a naive datetime."""
    return datetime.now(UTC).replace(tzinfo=None)
