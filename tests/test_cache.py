"""Tests for the on-disk normalized-session cache."""

from __future__ import annotations

import gzip
import json
import os
import time
from pathlib import Path

import yaml

from copsearch import cache as cache_mod
from copsearch.session import Session, load_sessions


def _make_session(
    base: Path,
    session_id: str = "test-id",
    events: str | None = None,
    active: bool = False,
) -> Session:
    d = base / session_id
    d.mkdir()
    (d / "checkpoints").mkdir()
    (d / "files").mkdir()
    (d / "workspace.yaml").write_text(
        yaml.dump(
            {
                "id": session_id,
                "cwd": str(base),
                "summary": "test",
                "created_at": "2026-04-10T10:00:00Z",
                "updated_at": "2026-04-10T12:00:00Z",
            }
        )
    )
    if events is not None:
        (d / "events.jsonl").write_text(events)
    if active:
        (d / f"inuse.{os.getpid()}.lock").write_text("")
    return next(s for s in load_sessions(base) if s.id == session_id)


def _basic_events() -> str:
    return (
        json.dumps({"type": "user.message", "data": {"content": "hi"}, "timestamp": "t1"}) + "\n"
        + json.dumps(
            {"type": "assistant.turn_start", "data": {"turnId": "0"}, "timestamp": "t2"}
        ) + "\n"
        + json.dumps(
            {
                "type": "assistant.message",
                "data": {"content": "hello back"},
                "timestamp": "t3",
            }
        ) + "\n"
    )


# ── Basic flow ───────────────────────────────────────────────────────────────


def test_get_with_no_cache_parses_and_writes(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    s = _make_session(sessions_dir, events=_basic_events())

    assert not cache_mod.is_fresh(s, cache_dir)
    ns = cache_mod.get(s, cache_dir)
    assert len(ns.turns) == 2
    assert cache_mod.is_fresh(s, cache_dir)
    # Cache file actually exists and is gzipped JSON.
    cp = cache_mod.cache_path(s.id, cache_dir)
    assert cp.exists()
    with gzip.open(cp, "rt") as f:
        data = json.load(f)
    assert data["schema_version"] >= 1


def test_get_uses_cache_when_fresh(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    s = _make_session(sessions_dir, events=_basic_events())

    cache_mod.get(s, cache_dir)  # First call: parse + write.

    # Tamper with the cache file so we know the second call read it.
    cp = cache_mod.cache_path(s.id, cache_dir)
    with gzip.open(cp, "rt") as f:
        data = json.load(f)
    data["meta"]["session_id"] = "TAMPERED"
    with gzip.open(cp, "wt") as f:
        json.dump(data, f)
    # Preserve the cache mtime > events mtime relationship — cache is fresh.
    new_mtime = (sessions_dir / s.id / "events.jsonl").stat().st_mtime + 10
    os.utime(cp, (new_mtime, new_mtime))

    ns = cache_mod.get(s, cache_dir)
    assert ns.meta.session_id == "TAMPERED"  # confirms cache was used


def test_cache_invalidates_on_events_mtime_advance(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    s = _make_session(sessions_dir, events=_basic_events())

    cache_mod.get(s, cache_dir)

    # Bump events.jsonl mtime forward — cache should now be stale.
    events_path = sessions_dir / s.id / "events.jsonl"
    new_mtime = time.time() + 100
    os.utime(events_path, (new_mtime, new_mtime))

    assert not cache_mod.is_fresh(s, cache_dir)

    # get() with a stale cache should re-parse.
    s2 = load_sessions(sessions_dir)[0]
    ns = cache_mod.get(s2, cache_dir)
    assert ns.meta.session_id == s.id  # not tampered, was re-derived from disk


def test_active_session_skips_cache_write(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    s = _make_session(sessions_dir, events=_basic_events(), active=True)
    assert s.is_active

    ns = cache_mod.get(s, cache_dir)
    assert len(ns.turns) == 2
    # No cache should have been written.
    assert not cache_mod.cache_path(s.id, cache_dir).exists()


def test_use_cache_false_forces_reparse(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    s = _make_session(sessions_dir, events=_basic_events())

    cache_mod.get(s, cache_dir)
    cp = cache_mod.cache_path(s.id, cache_dir)
    cp_mtime_before = cp.stat().st_mtime

    # use_cache=False: don't read or write the cache.
    time.sleep(0.01)
    cache_mod.get(s, cache_dir, use_cache=False)
    assert cp.stat().st_mtime == cp_mtime_before


def test_session_with_no_events_returns_empty(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    s = _make_session(sessions_dir, events=None)

    ns = cache_mod.get(s, cache_dir)
    assert ns.turns == []
    assert ns.meta.session_id == s.id


# ── Stats / clear ────────────────────────────────────────────────────────────


def test_stats_counts_entries(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    s1 = _make_session(sessions_dir, "id-1", events=_basic_events())
    cache_mod.get(s1, cache_dir)
    s2 = _make_session(sessions_dir, "id-2", events=_basic_events())
    cache_mod.get(s2, cache_dir)

    st = cache_mod.stats(cache_dir=cache_dir)
    assert st.entries == 2
    assert st.total_bytes > 0


def test_stats_identifies_orphans(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    s = _make_session(sessions_dir, "live", events=_basic_events())
    cache_mod.get(s, cache_dir)
    # Manually create an orphan cache entry.
    orphan_dir = cache_dir / "deleted-session"
    orphan_dir.mkdir(parents=True)
    with gzip.open(orphan_dir / cache_mod.CACHE_FILENAME, "wt") as f:
        json.dump({"schema_version": 1, "meta": {}, "turns": []}, f)

    sessions = load_sessions(sessions_dir)
    st = cache_mod.stats(sessions=sessions, cache_dir=cache_dir)
    assert st.entries == 2
    assert "deleted-session" in st.orphan_ids


def test_clear_one(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    s1 = _make_session(sessions_dir, "id-1", events=_basic_events())
    s2 = _make_session(sessions_dir, "id-2", events=_basic_events())
    cache_mod.get(s1, cache_dir)
    cache_mod.get(s2, cache_dir)

    removed = cache_mod.clear(session_id="id-1", cache_dir=cache_dir)
    assert removed == 1
    assert not cache_mod.cache_path("id-1", cache_dir).exists()
    assert cache_mod.cache_path("id-2", cache_dir).exists()


def test_clear_orphans_only(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    s = _make_session(sessions_dir, "live", events=_basic_events())
    cache_mod.get(s, cache_dir)
    orphan_dir = cache_dir / "deleted"
    orphan_dir.mkdir(parents=True)
    with gzip.open(orphan_dir / cache_mod.CACHE_FILENAME, "wt") as f:
        json.dump({"schema_version": 1, "meta": {}, "turns": []}, f)

    sessions = load_sessions(sessions_dir)
    removed = cache_mod.clear(orphans_only=True, sessions=sessions, cache_dir=cache_dir)
    assert removed == 1
    assert cache_mod.cache_path("live", cache_dir).exists()
    assert not (cache_dir / "deleted").exists()


def test_clear_all(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    cache_mod.get(_make_session(sessions_dir, "a", events=_basic_events()), cache_dir)
    cache_mod.get(_make_session(sessions_dir, "b", events=_basic_events()), cache_dir)

    removed = cache_mod.clear(cache_dir=cache_dir)
    assert removed == 2
    assert cache_mod.stats(cache_dir=cache_dir).entries == 0


def test_resolve_cached_id_accepts_prefix(tmp_path: Path, monkeypatch):
    """`copsearch cache clear --id 884bb` should work, not require the full UUID."""
    import copsearch.cache as cache_mod_real
    from copsearch.cli import _resolve_cached_id

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "884bb6a6-5491-470f-9af7-5e866ff38afc").mkdir()
    (cache_dir / "deadbeef-1234").mkdir()

    monkeypatch.setattr(cache_mod_real, "DEFAULT_CACHE_DIR", cache_dir)
    full = _resolve_cached_id("884bb", cache_mod_real)
    assert full == "884bb6a6-5491-470f-9af7-5e866ff38afc"


def test_resolve_cached_id_returns_input_when_no_match(tmp_path: Path, monkeypatch):
    import copsearch.cache as cache_mod_real
    from copsearch.cli import _resolve_cached_id

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(cache_mod_real, "DEFAULT_CACHE_DIR", cache_dir)
    # No matching prefix → return input verbatim so clear() no-ops cleanly.
    assert _resolve_cached_id("nope", cache_mod_real) == "nope"


def test_resolve_cached_id_errors_on_ambiguous(tmp_path: Path, monkeypatch, capsys):
    import copsearch.cache as cache_mod_real
    from copsearch.cli import _resolve_cached_id

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "abc-1").mkdir()
    (cache_dir / "abc-2").mkdir()
    monkeypatch.setattr(cache_mod_real, "DEFAULT_CACHE_DIR", cache_dir)
    try:
        _resolve_cached_id("abc", cache_mod_real)
    except SystemExit as e:
        assert e.code == 1
    err = capsys.readouterr().err
    assert "Ambiguous prefix" in err


def test_load_returns_none_for_older_schema_version(tmp_path: Path):
    """Caches written by an older schema must be ignored, forcing re-parse."""
    cache_dir = tmp_path / "cache"
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    s = _make_session(sessions_dir, "stale-cache", events=_basic_events())

    # Hand-write a cache with schema_version 0 (older than the live constant).
    cp = cache_mod.cache_path(s.id, cache_dir)
    cp.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(cp, "wt", encoding="utf-8") as f:
        json.dump({"schema_version": 0, "meta": {"session_id": s.id}, "turns": []}, f)
    # Bump cache mtime so is_fresh() would say "fresh" — version check must
    # still reject it.
    new_mtime = (sessions_dir / s.id / "events.jsonl").stat().st_mtime + 10
    os.utime(cp, (new_mtime, new_mtime))

    assert cache_mod.is_fresh(s, cache_dir) is True  # mtime says fresh
    assert cache_mod.load(s, cache_dir) is None  # but version says no
    # And the get() flow should re-parse and return real turns.
    ns = cache_mod.get(s, cache_dir)
    assert len(ns.turns) > 0


def test_clear_nonexistent_is_safe(tmp_path: Path):
    cache_dir = tmp_path / "does-not-exist"
    assert cache_mod.clear(cache_dir=cache_dir) == 0
    assert cache_mod.clear(session_id="anything", cache_dir=cache_dir) == 0
