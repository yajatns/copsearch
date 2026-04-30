"""On-disk cache for normalized session data.

Layout::

    ~/.copsearch/
    └── cache/
        └── <session-id>/
            └── normalized.json.gz    (gzipped JSON of NormalizedSession)

Cache freshness is determined by mtime: the cache is fresh iff its mtime is
``>=`` the source ``events.jsonl`` mtime. For active sessions (``events.jsonl``
is being appended right now) we always re-normalize but skip writing the
cache, to avoid rewriting on every ``view`` while tailing.
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from copsearch.normalize import (
    NormalizedSession,
    SessionMeta,
    from_dict,
    normalize_events,
    to_dict,
)
from copsearch.session import Session

DEFAULT_CACHE_DIR = Path.home() / ".copsearch" / "cache"
CACHE_FILENAME = "normalized.json.gz"


@dataclass
class CacheStats:
    """Result of :func:`stats`."""

    cache_dir: Path
    entries: int
    total_bytes: int
    orphan_ids: list[str]  # cache entries whose source session is gone


def _entries_dir(cache_dir: Path | None = None) -> Path:
    return cache_dir or DEFAULT_CACHE_DIR


def cache_path(session_id: str, cache_dir: Path | None = None) -> Path:
    """Path where the cache file for a session would live (may not exist)."""
    return _entries_dir(cache_dir) / session_id / CACHE_FILENAME


def is_fresh(session: Session, cache_dir: Path | None = None) -> bool:
    """True if a cache exists and is at least as new as ``events.jsonl``."""
    cp = cache_path(session.id, cache_dir)
    if not cp.exists():
        return False
    events_path = session.session_dir / "events.jsonl"
    if not events_path.exists():
        # No source to invalidate against — the cache is by definition stale-OK.
        return True
    try:
        return cp.stat().st_mtime >= events_path.stat().st_mtime
    except OSError:
        return False


def load(session: Session, cache_dir: Path | None = None) -> NormalizedSession | None:
    """Return the cached :class:`NormalizedSession` if present, else None.

    Does *not* check freshness — call :func:`is_fresh` first if that matters.
    Returns None on any read/parse error (treated as a cache miss).
    """
    cp = cache_path(session.id, cache_dir)
    if not cp.exists():
        return None
    try:
        with gzip.open(cp, "rt", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return from_dict(data)


def store(
    session: Session,
    normalized: NormalizedSession,
    cache_dir: Path | None = None,
) -> Path | None:
    """Write ``normalized`` to the cache. Returns the path written, or None.

    Returns None (skips writing) for active sessions — events.jsonl is still
    being appended, so the cache would be stale by the time it lands.
    """
    if session.is_active:
        return None
    cp = cache_path(session.id, cache_dir)
    cp.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replace: write to a sibling tmp file, then rename.
    tmp = cp.with_suffix(cp.suffix + ".tmp")
    try:
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump(to_dict(normalized), f, separators=(",", ":"))
        os.replace(tmp, cp)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    return cp


def get(
    session: Session,
    cache_dir: Path | None = None,
    use_cache: bool = True,
) -> NormalizedSession:
    """Load normalized data for a session, using the cache when possible.

    Flow:
        1. If ``use_cache`` and a fresh cache exists → load and return.
        2. Otherwise, parse ``events.jsonl`` from disk.
        3. If the session is idle and ``use_cache``, write the new cache.

    Sessions with no ``events.jsonl`` return an empty :class:`NormalizedSession`
    (one with the metadata filled in but ``turns=[]``).
    """
    if use_cache and is_fresh(session, cache_dir):
        cached = load(session, cache_dir)
        if cached is not None:
            return cached

    meta = _meta_from_session(session)
    events_path = session.session_dir / "events.jsonl"
    if not events_path.exists():
        return NormalizedSession(meta=meta, turns=[])

    normalized = normalize_events(events_path, meta)
    if use_cache:
        store(session, normalized, cache_dir)
    return normalized


# ── Cache management ─────────────────────────────────────────────────────────


def stats(
    sessions: list[Session] | None = None,
    cache_dir: Path | None = None,
) -> CacheStats:
    """Return on-disk cache statistics.

    If ``sessions`` is provided, identifies cache entries whose source
    session no longer exists (orphans).
    """
    base = _entries_dir(cache_dir)
    entries = 0
    total = 0
    cached_ids: list[str] = []
    if base.exists():
        for child in base.iterdir():
            cp = child / CACHE_FILENAME
            if cp.exists():
                entries += 1
                cached_ids.append(child.name)
                try:
                    total += cp.stat().st_size
                except OSError:
                    pass
    orphans: list[str] = []
    if sessions is not None:
        live_ids = {s.id for s in sessions}
        orphans = [cid for cid in cached_ids if cid not in live_ids]
    return CacheStats(cache_dir=base, entries=entries, total_bytes=total, orphan_ids=orphans)


def clear(
    session_id: str | None = None,
    orphans_only: bool = False,
    sessions: list[Session] | None = None,
    cache_dir: Path | None = None,
) -> int:
    """Delete cache entries. Returns the number of session caches removed.

    - ``session_id`` set: remove just that one.
    - ``orphans_only=True``: remove only entries with no matching session
      (requires ``sessions``).
    - neither: remove the entire cache directory.
    """
    base = _entries_dir(cache_dir)
    if not base.exists():
        return 0

    if session_id:
        target = base / session_id
        if not target.exists():
            return 0
        try:
            shutil.rmtree(target)
            return 1
        except OSError:
            return 0

    if orphans_only:
        if sessions is None:
            return 0
        live_ids = {s.id for s in sessions}
        removed = 0
        for child in list(base.iterdir()):
            if child.name not in live_ids:
                try:
                    shutil.rmtree(child)
                    removed += 1
                except OSError:
                    continue
        return removed

    # Wipe everything.
    removed = 0
    for child in list(base.iterdir()):
        try:
            shutil.rmtree(child)
            removed += 1
        except OSError:
            continue
    return removed


# ── Internals ────────────────────────────────────────────────────────────────


def _meta_from_session(session: Session) -> SessionMeta:
    """Build a :class:`SessionMeta` from the session's workspace.yaml fields."""
    return SessionMeta(
        session_id=session.id,
        cwd=session.cwd,
        branch=session.branch,
        repository=session.repository,
        summary=session.summary,
        created_at=session.created_at.isoformat() if session.created_at else "",
        updated_at=session.updated_at.isoformat() if session.updated_at else "",
        is_active=session.is_active,
        has_plan=session.has_plan,
        plan_text=session.plan_text,
    )
