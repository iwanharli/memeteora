"""Display timezone.

Everything is stored as UTC in `timestamptz` - that is an absolute instant and
must stay that way, or snapshots taken on different machines stop being
comparable. This module only converts for human-facing output.

WIB has never observed DST, so a fixed +07:00 offset is exact rather than an
approximation.
"""
from datetime import datetime, timedelta, timezone

WIB = timezone(timedelta(hours=7), "WIB")


def now_utc():
    """The instant to persist. Never store the result of local_now()."""
    return datetime.now(timezone.utc)


def local(dt):
    """UTC (or naive-assumed-UTC) -> WIB, for display only."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(WIB)


def stamp(dt=None, fmt="%Y-%m-%d %H:%M:%S"):
    return (local(dt) if dt else datetime.now(WIB)).strftime(fmt)
