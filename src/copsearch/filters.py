"""Filtering logic for Copilot sessions."""

from __future__ import annotations

import fnmatch
import re
from datetime import datetime, timedelta, timezone

from copsearch.session import Session


def filter_sessions(
    sessions: list[Session],
    project: str = "",
    branch: str = "",
    since: str = "",
    query: str = "",
) -> list[Session]:
    """Apply filters to a list of sessions.

    Args:
        sessions: Input session list.
        project: Substring match against project name, repository, or cwd.
        branch: Glob pattern matched against branch name.
        since: Time filter — e.g. '7d', '24h', '30m', or ISO date string.
        query: Space-separated search terms matched against all session text.

    Returns:
        Filtered list of sessions (same order as input).
    """
    result = sessions

    if project:
        pat = project.lower()
        result = [
            s
            for s in result
            if pat in s.project.lower() or pat in s.repository.lower() or pat in s.cwd.lower()
        ]

    if branch:
        result = [s for s in result if fnmatch.fnmatch(s.branch, branch)]

    if since:
        cutoff = _parse_since(since)
        if cutoff:
            result = [s for s in result if s.updated_at and s.updated_at >= cutoff]

    if query:
        terms = query.lower().split()
        result = [s for s in result if all(t in s.searchable for t in terms)]

    return result


def _parse_since(val: str) -> datetime | None:
    """Parse a relative time string (e.g. '7d') or ISO date into a datetime."""
    m = re.match(r"(\d+)([dhm])", val.lower())
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"d": timedelta(days=n), "h": timedelta(hours=n), "m": timedelta(minutes=n)}
        return datetime.now(timezone.utc) - delta.get(unit, timedelta())
    try:
        dt = datetime.fromisoformat(val)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None
