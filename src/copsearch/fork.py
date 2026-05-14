"""Fork a Copilot CLI session into a new session with a fresh UUID.

A fork copies an existing session directory wholesale (events, plan, checkpoints,
artifacts) and rewrites :file:`workspace.yaml` so the new session has its own
UUID and timestamps. The source session is not touched.

The fork is *offline* — no ``inuse.*.lock`` is created — until the user runs
``copilot --resume=<new-id>``.

Race-safety: ``events.jsonl`` is append-only, so the fork snapshots its byte
length up front and truncates any partial trailing line. The worst case is
losing the very last event being written when the source is active.

Atomicity: everything is staged into a hidden ``.fork-<uuid>.tmp/`` sibling
directory and renamed into place at the end. A failure mid-copy leaves only
the tempdir, which the caller (or a later run) can clean up.
"""

from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Top-level entries we never copy from the source session.
SKIP_NAMES: frozenset[str] = frozenset(
    {
        "rewind-snapshots",
        ".fork-tmp",
    }
)

# Glob patterns we never copy.
SKIP_GLOBS: tuple[str, ...] = (
    "inuse.*.lock",
    ".fork-*.tmp",
)


class ForkError(Exception):
    """Raised when a session cannot be forked."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _snapshot_events(src: Path, dst: Path) -> int:
    """Copy ``events.jsonl`` byte-for-byte up to its current length, truncating
    any partial trailing line. Returns the number of bytes written.
    """
    size = src.stat().st_size
    if size == 0:
        dst.write_bytes(b"")
        return 0

    with src.open("rb") as fh:
        buf = fh.read(size)

    # Truncate to the last complete line so a fork never carries a half-written
    # JSON object (which would break Copilot's parser on resume).
    last_nl = buf.rfind(b"\n")
    if last_nl == -1:
        # No newline yet — drop the partial line entirely.
        buf = b""
    else:
        buf = buf[: last_nl + 1]

    dst.write_bytes(buf)
    return len(buf)


def _last_event_id(events_bytes: bytes) -> str | None:
    """Best-effort extract the ``id`` of the final event in the snapshot."""
    if not events_bytes:
        return None
    # Walk back to the last non-empty line.
    end = len(events_bytes)
    while end > 0 and events_bytes[end - 1 : end] == b"\n":
        end -= 1
    if end == 0:
        return None
    start = events_bytes.rfind(b"\n", 0, end) + 1
    line = events_bytes[start:end]
    try:
        import json

        obj = json.loads(line)
        eid = obj.get("id")
        return str(eid) if eid is not None else None
    except (ValueError, AttributeError):
        return None


def _should_skip(name: str) -> bool:
    if name in SKIP_NAMES:
        return True
    from fnmatch import fnmatch

    return any(fnmatch(name, pat) for pat in SKIP_GLOBS)


def _copy_tree_filtered(src: Path, dst: Path) -> None:
    """Recursively copy ``src`` into ``dst``, skipping fork/lock artifacts."""

    def _ignore(_dir: str, names: list[str]) -> list[str]:
        return [n for n in names if _should_skip(n)]

    shutil.copytree(src, dst, ignore=_ignore, dirs_exist_ok=True, symlinks=False)


def _rewrite_workspace(
    ws_path: Path,
    *,
    new_id: str,
    name: str | None,
    src_id: str,
    src_name: str | None,
    forked_at_event: str | None,
    throwaway: bool,
) -> None:
    """Rewrite ``workspace.yaml`` in place for the forked session."""
    raw = ws_path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise ForkError(f"workspace.yaml at {ws_path} is not a mapping")

    now = _now_iso()
    data["id"] = new_id
    data["created_at"] = now
    data["updated_at"] = now

    if name is not None:
        data["name"] = name
        data["user_named"] = True
    elif src_name:
        data["name"] = f"Fork of {src_name}"
        data["user_named"] = False

    # Provenance — non-invasive; Copilot ignores unknown YAML keys.
    data["forked_from"] = src_id
    if forked_at_event:
        data["forked_at_event"] = forked_at_event
    data["forked_at"] = now

    # Throw-away marker: visible to copsearch, ignored by Copilot.
    if throwaway:
        data["throwaway"] = True
    else:
        data.pop("throwaway", None)

    ws_path.write_text(
        yaml.safe_dump(data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def fork_session(
    src_dir: Path,
    *,
    name: str | None = None,
    base_dir: Path | None = None,
    new_id: str | None = None,
    throwaway: bool = False,
) -> Path:
    """Fork the session at ``src_dir`` into a sibling directory.

    Parameters
    ----------
    src_dir:
        Path to an existing Copilot session directory.
    name:
        Optional human-readable name for the new session. Defaults to
        ``"Fork of <src-name>"`` when the source has a name, otherwise unset.
    base_dir:
        Where to create the new session. Defaults to ``src_dir.parent``.
    new_id:
        Override the generated UUID (used by tests). Must not collide with
        an existing session directory.
    throwaway:
        If ``True``, mark the new session with ``throwaway: true`` in
        :file:`workspace.yaml`. copsearch displays these with a 🗑️ marker
        as a visual reminder to delete them later.

    Returns
    -------
    Path
        The new session directory (already renamed into place).

    Raises
    ------
    ForkError
        If the source is missing required files, the destination already
        exists, or any IO error occurs (the tempdir is cleaned up).
    """
    src_dir = Path(src_dir)
    if not src_dir.is_dir():
        raise ForkError(f"Source session directory not found: {src_dir}")

    src_events = src_dir / "events.jsonl"
    src_ws = src_dir / "workspace.yaml"
    if not src_events.exists():
        raise ForkError(f"Source has no events.jsonl: {src_dir}")
    if not src_ws.exists():
        raise ForkError(f"Source has no workspace.yaml: {src_dir}")

    base = Path(base_dir) if base_dir is not None else src_dir.parent
    base.mkdir(parents=True, exist_ok=True)

    new_id = new_id or str(uuid.uuid4())
    final_dir = base / new_id
    if final_dir.exists():
        raise ForkError(f"Destination already exists: {final_dir}")

    tmp_dir = base / f".fork-{new_id}.tmp"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Read source workspace up front so we can snapshot its name even if the
    # source is being mutated concurrently.
    try:
        src_ws_data = yaml.safe_load(src_ws.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ForkError(f"Cannot read source workspace.yaml: {exc}") from exc
    src_id = str(src_ws_data.get("id") or src_dir.name)
    src_name = src_ws_data.get("name")
    if src_name is not None and not isinstance(src_name, str):
        src_name = str(src_name)

    try:
        tmp_dir.mkdir(parents=True, exist_ok=False)

        # 1. Snapshot events.jsonl first — this defines the fork's "cut point".
        events_size = _snapshot_events(src_events, tmp_dir / "events.jsonl")
        forked_at_event = (
            _last_event_id((tmp_dir / "events.jsonl").read_bytes()) if events_size else None
        )

        # 2. Copy everything else (tree-walk so we can filter by name).
        for entry in src_dir.iterdir():
            if entry.name == "events.jsonl":
                continue  # already snapshotted
            if _should_skip(entry.name):
                continue
            target = tmp_dir / entry.name
            if entry.is_dir():
                _copy_tree_filtered(entry, target)
            elif entry.is_symlink():
                # Materialize the link's target as a regular file/dir copy to
                # avoid leaving dangling references.
                if entry.resolve().is_dir():
                    _copy_tree_filtered(entry, target)
                else:
                    shutil.copy2(entry, target, follow_symlinks=True)
            else:
                shutil.copy2(entry, target, follow_symlinks=True)

        # 3. Rewrite workspace.yaml with the new id + provenance.
        _rewrite_workspace(
            tmp_dir / "workspace.yaml",
            new_id=new_id,
            name=name,
            src_id=src_id,
            src_name=src_name,
            forked_at_event=forked_at_event,
            throwaway=throwaway,
        )

        # 4. Atomic publish.
        os.rename(tmp_dir, final_dir)
    except ForkError:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    except Exception as exc:
        # Wrap unexpected I/O / OS errors so callers that only catch
        # ForkError still surface a clean "Fork failed: <reason>" instead
        # of an uncaught traceback.
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise ForkError(f"unexpected failure during fork: {exc}") from exc

    return final_dir
