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
    # Unexpected errors are wrapped in ForkError so the CLI/TUI layers
    # (which only catch ForkError) render a clean message instead of a
    # traceback. The original exception is preserved via __cause__.
    with pytest.raises(ForkError, match="unexpected failure") as exc_info:
        fork_session(src)
    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert "simulated" in str(exc_info.value.__cause__)

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


def test_fork_rewrites_sessionId_in_events(tmp_path: Path):
    """Copilot CLI reads ``data.sessionId`` from session.start when resuming
    and writes its inuse.<pid>.lock under that id's directory. If the fork
    keeps the source's sessionId, the fork's lock lands in the *source's*
    directory and copsearch lights up the wrong session as active.
    """
    src_id = "aaaaaaaa-1111-1111-1111-111111111111"
    src = _make_source(
        tmp_path,
        src_id=src_id,
        events=[
            {
                "type": "session.start",
                "id": "ev-start",
                "data": {"sessionId": src_id, "version": 1},
            },
            {
                "type": "user.message",
                "id": "ev-1",
                "data": {"sessionId": src_id, "text": "hello"},
            },
        ],
    )

    new_dir = fork_session(src)
    new_id = new_dir.name

    body = (new_dir / "events.jsonl").read_text()
    assert src_id not in body, "source sessionId still present"
    # Both events had a sessionId field — both should be rewritten.
    import re as _re

    assert len(_re.findall(rf'"sessionId"\s*:\s*"{new_id}"', body)) == 2

    # Source events are untouched.
    src_body = (src / "events.jsonl").read_text()
    assert src_id in src_body
    assert new_id not in src_body


def test_fork_sessionId_rewrite_is_localized(tmp_path: Path):
    """The rewrite must only target the literal ``"sessionId":"<src>"`` token,
    not arbitrary occurrences of the source id (e.g. inside message text)."""
    src_id = "bbbbbbbb-2222-2222-2222-222222222222"
    src = _make_source(
        tmp_path,
        src_id=src_id,
        events=[
            {
                "type": "session.start",
                "id": "ev-start",
                "data": {"sessionId": src_id},
            },
            {
                "type": "user.message",
                "id": "ev-1",
                "data": {"text": f"the previous session id was {src_id}"},
            },
        ],
    )

    new_dir = fork_session(src)
    body = (new_dir / "events.jsonl").read_text()

    # The session.start sessionId is rewritten...
    import re as _re

    assert _re.search(rf'"sessionId"\s*:\s*"{new_dir.name}"', body)
    # ...but the user message that quotes the id verbatim is preserved.
    assert f"the previous session id was {src_id}" in body


def test_fork_writes_sidecar(tmp_path: Path):
    """Fork metadata lives in .copsearch.json so it survives Copilot CLI
    rewriting workspace.yaml on save."""
    from copsearch.sidecar import read_sidecar

    src = _make_source(tmp_path)
    new_dir = fork_session(src, name="My Fork")

    sidecar = read_sidecar(new_dir)
    assert sidecar["forked_from"] == src.name
    assert sidecar["throwaway"] is False
    assert "forked_at" in sidecar
    assert "schema" in sidecar


def test_fork_sidecar_records_throwaway(tmp_path: Path):
    from copsearch.sidecar import read_sidecar

    src = _make_source(tmp_path)
    new_dir = fork_session(src, throwaway=True)

    assert read_sidecar(new_dir)["throwaway"] is True


def test_session_reads_fork_metadata_from_sidecar(tmp_path: Path):
    """If Copilot has wiped workspace.yaml's fork keys, the sidecar still
    yields forked_from / throwaway / forked_at to copsearch."""
    import yaml as _yaml

    from copsearch.session import Session
    from copsearch.sidecar import write_sidecar

    src = _make_source(tmp_path)
    new_dir = fork_session(src, throwaway=True)

    # Simulate Copilot rewriting workspace.yaml: keep only the fields it
    # knows about, dropping forked_from / forked_at / throwaway.
    ws = new_dir / "workspace.yaml"
    data = _yaml.safe_load(ws.read_text())
    cleaned = {
        k: v
        for k, v in data.items()
        if k not in {"forked_from", "forked_at", "forked_at_event", "throwaway"}
    }
    ws.write_text(_yaml.dump(cleaned, default_flow_style=False, sort_keys=False))

    s = Session(cleaned, new_dir)
    assert s.forked_from == src.name
    assert s.throwaway is True

    # And the sidecar wins over a stale workspace.yaml value.
    write_sidecar(new_dir, {"forked_from": "override-id", "throwaway": False})
    s2 = Session(cleaned, new_dir)
    assert s2.forked_from == "override-id"
    assert s2.throwaway is False


def test_session_infers_fork_when_sidecar_missing(tmp_path: Path):
    """Sessions forked before the sidecar/sessionId-rewrite existed are
    still detectable: their events.jsonl starts with the source's
    ``session.start`` event, whose ``data.sessionId`` differs from the
    directory name."""
    import yaml as _yaml

    from copsearch.session import Session

    src_id = "11111111-1111-1111-1111-111111111111"
    legacy_fork_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    legacy = tmp_path / legacy_fork_id
    legacy.mkdir()
    (legacy / "workspace.yaml").write_text(
        _yaml.dump(
            {
                "id": legacy_fork_id,
                "cwd": str(tmp_path),
                "created_at": "2026-04-01T10:00:00Z",
                "updated_at": "2026-04-01T11:00:00Z",
            },
            default_flow_style=False,
            sort_keys=False,
        )
    )
    (legacy / "events.jsonl").write_text(
        json.dumps(
            {
                "type": "session.start",
                "id": "ev-start",
                "data": {"sessionId": src_id},
            }
        )
        + "\n"
    )

    data = _yaml.safe_load((legacy / "workspace.yaml").read_text())
    s = Session(data, legacy)
    assert s.forked_from == src_id

    # Auto-heal wrote the sidecar back so subsequent loads are fast.
    from copsearch.sidecar import read_sidecar

    assert read_sidecar(legacy).get("forked_from") == src_id


def test_session_does_not_invent_forked_from_for_originals(tmp_path: Path):
    """A non-forked session whose first event references its own sessionId
    must not be flagged as a fork."""
    from copsearch.session import Session

    src = _make_source(
        tmp_path,
        events=[
            {
                "type": "session.start",
                "id": "ev-start",
                "data": {"sessionId": "11111111-1111-1111-1111-111111111111"},
            },
        ],
    )
    import yaml as _yaml

    data = _yaml.safe_load((src / "workspace.yaml").read_text())
    s = Session(data, src)
    assert s.forked_from == ""


def test_set_throwaway_persists_to_sidecar(tmp_path: Path):
    """Toggling the throw-away flag must update the sidecar, not just
    workspace.yaml — otherwise the change vanishes the next time Copilot
    saves the session."""
    import yaml as _yaml

    from copsearch.session import Session
    from copsearch.sidecar import read_sidecar

    src = _make_source(tmp_path)
    new_dir = fork_session(src)

    data = _yaml.safe_load((new_dir / "workspace.yaml").read_text())
    s = Session(data, new_dir)
    assert s.throwaway is False

    assert s.set_throwaway(True) is True
    assert read_sidecar(new_dir)["throwaway"] is True

    assert s.set_throwaway(False) is True
    assert read_sidecar(new_dir)["throwaway"] is False
