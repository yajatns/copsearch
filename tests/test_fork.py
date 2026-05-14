"""Tests for the session fork engine."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
import yaml

from copsearch.fork import ForkError, fork_session


def _make_source(
    base: Path,
    src_id: str = "11111111-1111-1111-1111-111111111111",
    *,
    extra_files: dict[str, str] | None = None,
    events: list[dict] | None = None,
    workspace_extra: dict | None = None,
    name: str | None = "Source session",
) -> Path:
    src = base / src_id
    src.mkdir()
    ws = {
        "id": src_id,
        "cwd": str(base),
        "branch": "main",
        "summary_count": 2,
        "created_at": "2026-04-01T10:00:00Z",
        "updated_at": "2026-04-01T11:00:00Z",
    }
    if name is not None:
        ws["name"] = name
        ws["user_named"] = True
    if workspace_extra:
        ws.update(workspace_extra)
    (src / "workspace.yaml").write_text(yaml.dump(ws))

    events = events or [
        {"type": "user.message", "id": "ev-1", "data": {"text": "hi"}},
        {"type": "assistant.turn_start", "id": "ev-2"},
    ]
    (src / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")

    # Realistic siblings.
    (src / ".sqlite").write_bytes(b"")
    (src / "session.db").write_bytes(b"sqlite-fake")
    (src / "checkpoints").mkdir()
    (src / "checkpoints" / "index.md").write_text("# Checkpoints\n")
    (src / "files").mkdir()
    (src / "files" / "note.txt").write_text("hello\n")
    (src / "plan.md").write_text("# Plan\n\nDo the thing.\n")
    # Things that must NOT be copied.
    (src / "inuse.99999.lock").write_text("99999")
    (src / "rewind-snapshots").mkdir()
    (src / "rewind-snapshots" / "snap-1.json").write_text("{}")

    if extra_files:
        for rel, content in extra_files.items():
            p = src / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)

    return src


def test_fork_creates_new_session_dir(tmp_path: Path):
    src = _make_source(tmp_path)
    new_dir = fork_session(src)

    assert new_dir.exists()
    assert new_dir.parent == tmp_path
    assert new_dir.name != src.name
    # Looks like a UUID.
    uuid.UUID(new_dir.name)


def test_fork_preserves_events_byte_for_byte(tmp_path: Path):
    src = _make_source(tmp_path)
    new_dir = fork_session(src)

    src_bytes = (src / "events.jsonl").read_bytes()
    new_bytes = (new_dir / "events.jsonl").read_bytes()
    assert src_bytes == new_bytes


def test_fork_truncates_partial_trailing_line(tmp_path: Path):
    src = _make_source(tmp_path)
    # Append a half-written line (no terminating newline).
    with (src / "events.jsonl").open("a") as fh:
        fh.write('{"type": "user.message", "id": "partial')

    new_dir = fork_session(src)
    new_text = (new_dir / "events.jsonl").read_text()
    # Must end with newline (no partial line carried over).
    assert new_text.endswith("\n")
    assert "partial" not in new_text


def test_fork_rewrites_workspace_id_and_provenance(tmp_path: Path):
    src = _make_source(tmp_path, src_id="22222222-2222-2222-2222-222222222222")
    new_dir = fork_session(src)

    new_ws = yaml.safe_load((new_dir / "workspace.yaml").read_text())
    assert new_ws["id"] == new_dir.name
    assert new_ws["id"] != "22222222-2222-2222-2222-222222222222"
    assert new_ws["forked_from"] == "22222222-2222-2222-2222-222222222222"
    assert new_ws["forked_at"]  # has a timestamp
    assert new_ws["forked_at_event"] == "ev-2"
    # Default name when source has one.
    assert new_ws["name"] == "Fork of Source session"
    assert new_ws["user_named"] is False


def test_fork_with_explicit_name(tmp_path: Path):
    src = _make_source(tmp_path)
    new_dir = fork_session(src, name="My experiment")

    new_ws = yaml.safe_load((new_dir / "workspace.yaml").read_text())
    assert new_ws["name"] == "My experiment"
    assert new_ws["user_named"] is True


def test_fork_throwaway_flag(tmp_path: Path):
    src = _make_source(tmp_path)
    keep_dir = fork_session(src)
    toss_dir = fork_session(src, throwaway=True)

    keep_ws = yaml.safe_load((keep_dir / "workspace.yaml").read_text())
    toss_ws = yaml.safe_load((toss_dir / "workspace.yaml").read_text())
    assert "throwaway" not in keep_ws
    assert toss_ws["throwaway"] is True


def test_fork_does_not_copy_lock_or_rewind(tmp_path: Path):
    src = _make_source(tmp_path)
    new_dir = fork_session(src)

    assert not list(new_dir.glob("inuse.*.lock"))
    assert not (new_dir / "rewind-snapshots").exists()


def test_fork_copies_artifacts(tmp_path: Path):
    src = _make_source(tmp_path)
    new_dir = fork_session(src)

    assert (new_dir / "plan.md").read_text() == "# Plan\n\nDo the thing.\n"
    assert (new_dir / "checkpoints" / "index.md").exists()
    assert (new_dir / "files" / "note.txt").read_text() == "hello\n"
    assert (new_dir / "session.db").read_bytes() == b"sqlite-fake"
    assert (new_dir / ".sqlite").exists()


def test_fork_leaves_source_untouched(tmp_path: Path):
    src = _make_source(tmp_path)
    src_ws_before = (src / "workspace.yaml").read_text()
    src_events_before = (src / "events.jsonl").read_bytes()
    src_lock_before = (src / "inuse.99999.lock").read_text()

    fork_session(src)

    assert (src / "workspace.yaml").read_text() == src_ws_before
    assert (src / "events.jsonl").read_bytes() == src_events_before
    assert (src / "inuse.99999.lock").read_text() == src_lock_before


def test_two_forks_dont_collide(tmp_path: Path):
    src = _make_source(tmp_path)
    a = fork_session(src)
    b = fork_session(src)
    assert a != b
    assert a.exists() and b.exists()


def test_fork_atomicity_no_leftover_tmp_on_success(tmp_path: Path):
    src = _make_source(tmp_path)
    fork_session(src)
    leftover = list(tmp_path.glob(".fork-*.tmp"))
    assert leftover == []


def test_fork_cleans_tmp_on_failure(tmp_path: Path, monkeypatch):
    src = _make_source(tmp_path)
    from copsearch import fork as fork_mod

    def boom(*a, **kw):
        raise RuntimeError("simulated mid-copy failure")

    monkeypatch.setattr(fork_mod, "_rewrite_workspace", boom)
    with pytest.raises(RuntimeError, match="simulated"):
        fork_session(src)

    leftover = list(tmp_path.glob(".fork-*.tmp"))
    assert leftover == []


def test_fork_missing_source_raises(tmp_path: Path):
    with pytest.raises(ForkError, match="not found"):
        fork_session(tmp_path / "does-not-exist")


def test_fork_missing_events_raises(tmp_path: Path):
    src = tmp_path / "no-events"
    src.mkdir()
    (src / "workspace.yaml").write_text(yaml.dump({"id": "x"}))
    with pytest.raises(ForkError, match="events.jsonl"):
        fork_session(src)


def test_fork_explicit_new_id_collision(tmp_path: Path):
    src = _make_source(tmp_path)
    fixed = "deadbeef-1234-1234-1234-123456789abc"
    fork_session(src, new_id=fixed)
    with pytest.raises(ForkError, match="already exists"):
        fork_session(src, new_id=fixed)


def test_fork_into_separate_base_dir(tmp_path: Path):
    src = _make_source(tmp_path)
    other = tmp_path / "other"
    new_dir = fork_session(src, base_dir=other)
    assert new_dir.parent == other
    assert new_dir.exists()
