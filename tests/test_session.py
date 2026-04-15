"""Tests for session loader."""

from pathlib import Path

import yaml

from copsearch.session import Session, load_sessions


def _make_session_dir(tmp_path: Path, session_id: str, **kwargs) -> Path:
    """Helper to create a fake session directory."""
    d = tmp_path / session_id
    d.mkdir()
    (d / "checkpoints").mkdir()
    (d / "files").mkdir()

    data = {
        "id": session_id,
        "cwd": str(tmp_path),
        "summary_count": 0,
        "created_at": "2026-04-10T10:00:00Z",
        "updated_at": "2026-04-10T12:00:00Z",
        **kwargs,
    }
    (d / "workspace.yaml").write_text(yaml.dump(data))
    return d


def test_load_sessions_empty(tmp_path: Path):
    sessions = load_sessions(tmp_path)
    assert sessions == []


def test_load_sessions_basic(tmp_path: Path):
    _make_session_dir(tmp_path, "aaa-111", summary="Test session", branch="main")
    _make_session_dir(tmp_path, "bbb-222", summary="Another session", branch="dev")

    sessions = load_sessions(tmp_path)
    assert len(sessions) == 2
    assert all(isinstance(s, Session) for s in sessions)


def test_session_fields(tmp_path: Path):
    _make_session_dir(
        tmp_path,
        "ccc-333",
        summary="My session",
        branch="yaj/feature",
        repository="org/repo",
        cwd="/Users/test/project",
    )

    sessions = load_sessions(tmp_path)
    s = sessions[0]
    assert s.id == "ccc-333"
    assert s.summary == "My session"
    assert s.branch == "yaj/feature"
    assert s.repository == "org/repo"
    assert s.project == "project"


def test_session_with_plan(tmp_path: Path):
    d = _make_session_dir(tmp_path, "ddd-444", summary="Has a plan")
    (d / "plan.md").write_text("# Fix the Bug\n\nDetailed description here.")

    sessions = load_sessions(tmp_path)
    s = sessions[0]
    assert s.has_plan is True
    assert s.plan_title == "Fix the Bug"
    assert s.display_summary == "Fix the Bug"


def test_session_without_plan(tmp_path: Path):
    _make_session_dir(tmp_path, "eee-555", summary="No plan here")

    sessions = load_sessions(tmp_path)
    s = sessions[0]
    assert s.has_plan is False
    assert s.plan_title == ""
    assert s.display_summary == "No plan here"


def test_session_no_summary(tmp_path: Path):
    _make_session_dir(tmp_path, "fff-666")

    sessions = load_sessions(tmp_path)
    s = sessions[0]
    assert s.display_summary == "(no summary)"


def test_sessions_sorted_by_updated(tmp_path: Path):
    _make_session_dir(tmp_path, "old", updated_at="2026-04-01T00:00:00Z")
    _make_session_dir(tmp_path, "new", updated_at="2026-04-10T00:00:00Z")
    _make_session_dir(tmp_path, "mid", updated_at="2026-04-05T00:00:00Z")

    sessions = load_sessions(tmp_path)
    ids = [s.id for s in sessions]
    assert ids == ["new", "mid", "old"]


def test_searchable_field(tmp_path: Path):
    _make_session_dir(
        tmp_path,
        "ggg-777",
        summary="RSS throughput test",
        branch="yaj/rss-fix",
        cwd="/Users/test/Integration",
    )

    sessions = load_sessions(tmp_path)
    s = sessions[0]
    assert "rss" in s.searchable
    assert "throughput" in s.searchable
    assert "integration" in s.searchable
    assert "yaj/rss-fix" in s.searchable


def test_age_str(tmp_path: Path):
    _make_session_dir(tmp_path, "hhh-888", updated_at="2020-01-01T00:00:00Z")

    sessions = load_sessions(tmp_path)
    s = sessions[0]
    assert "mo" in s.age_str  # should be many months ago


def test_skips_bad_yaml(tmp_path: Path):
    d = tmp_path / "bad-session"
    d.mkdir()
    (d / "workspace.yaml").write_text(":::invalid yaml{{{}}")

    sessions = load_sessions(tmp_path)
    assert sessions == []


def test_active_session_with_live_pid(tmp_path: Path):
    """Session with inuse lock matching a running PID is marked active."""
    import os

    d = _make_session_dir(tmp_path, "active-001", summary="Active session")
    # Use our own PID — guaranteed to be alive
    (d / f"inuse.{os.getpid()}.lock").write_text("")

    sessions = load_sessions(tmp_path)
    s = sessions[0]
    assert s.is_active is True
    assert s.active_pid == os.getpid()


def test_inactive_session_with_stale_lock(tmp_path: Path):
    """Session with inuse lock for a dead PID is not active."""
    d = _make_session_dir(tmp_path, "stale-001", summary="Stale lock")
    # PID 999999 is almost certainly not running
    (d / "inuse.999999.lock").write_text("")

    sessions = load_sessions(tmp_path)
    s = sessions[0]
    assert s.is_active is False
    assert s.active_pid is None


def test_session_without_lock_is_inactive(tmp_path: Path):
    """Session with no lock file is not active."""
    _make_session_dir(tmp_path, "nolock-001", summary="No lock")

    sessions = load_sessions(tmp_path)
    s = sessions[0]
    assert s.is_active is False
    assert s.active_pid is None
