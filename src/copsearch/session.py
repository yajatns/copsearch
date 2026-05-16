"""Session data model and loader for Copilot CLI sessions."""

from __future__ import annotations

import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

DEFAULT_SESSION_DIR = Path.home() / ".copilot" / "session-state"


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is running."""
    if sys.platform == "win32":
        # On Windows, os.kill(pid, 0) doesn't work as expected.
        # Use ctypes to call OpenProcess and check if it succeeds.
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


class Session:
    """Represents a single Copilot CLI session with its metadata."""

    __slots__ = (
        "id",
        "session_dir",
        "cwd",
        "project",
        "git_root",
        "repository",
        "branch",
        "summary",
        "summary_count",
        "created_at",
        "updated_at",
        "plan_title",
        "plan_text",
        "checkpoint_count",
        "has_plan",
        "is_active",
        "active_pid",
        "user_messages",
        "assistant_turns",
        "has_events",
        "throwaway",
        "forked_from",
        "forked_at",
    )

    def __init__(self, data: dict, session_dir: Path):
        self.id: str = data.get("id", "")
        self.session_dir: Path = session_dir
        self.cwd: str = data.get("cwd", "")
        self.project: str = os.path.basename(self.cwd) if self.cwd else ""
        self.git_root: str = data.get("git_root", "")
        self.repository: str = data.get("repository", "")
        self.branch: str = data.get("branch", "")
        self.summary: str = data.get("summary", "")
        self.summary_count: int = data.get("summary_count", 0)

        self.created_at: datetime | None = _parse_date(data.get("created_at"))
        self.updated_at: datetime | None = _parse_date(data.get("updated_at"))

        # Fork metadata. The sidecar (.copsearch.json) is the durable source
        # of truth — Copilot CLI rewrites workspace.yaml with its own schema
        # and drops unknown keys, so any fork markers there only survive until
        # Copilot first saves the session. Sidecar values win when both
        # sources are present.
        from copsearch.sidecar import read_sidecar

        sidecar = read_sidecar(session_dir)
        self.throwaway: bool = bool(sidecar.get("throwaway", data.get("throwaway", False)))
        self.forked_from: str = str(
            sidecar.get("forked_from") or data.get("forked_from") or ""
        )
        self.forked_at: datetime | None = _parse_date(
            sidecar.get("forked_at") or data.get("forked_at")
        )

        # Auto-heal: if the events log thinks this session has a different id
        # (i.e. it's a fork whose workspace.yaml was already rewritten by
        # Copilot), backfill the sidecar so future loads don't have to reread
        # the events file. This also recovers fork provenance for sessions
        # forked before the sidecar existed.
        if not self.forked_from and self.id:
            inferred = _infer_forked_from(session_dir, self.id)
            if inferred:
                self.forked_from = inferred
                try:
                    from copsearch.sidecar import update_sidecar

                    update_sidecar(
                        session_dir,
                        forked_from=inferred,
                        forked_at=(
                            self.created_at.isoformat()
                            if self.created_at
                            else None
                        ),
                    )
                except Exception:
                    pass

        # Detect active session via inuse.*.lock files
        self.is_active: bool = False
        self.active_pid: int | None = None
        for lock_file in session_dir.glob("inuse.*.lock"):
            try:
                pid = int(lock_file.stem.split(".")[-1])
                if _is_pid_alive(pid):
                    self.is_active = True
                    self.active_pid = pid
                    break
            except (ValueError, IndexError):
                continue

        # Load plan.md if present
        plan_path = session_dir / "plan.md"
        self.has_plan: bool = plan_path.exists()
        if self.has_plan:
            try:
                text = plan_path.read_text(errors="replace")
                self.plan_text = text
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                self.plan_title = _clean_title(lines[0]) if lines else ""
            except Exception:
                self.plan_text = ""
                self.plan_title = ""
        else:
            self.plan_text = ""
            self.plan_title = ""

        # Count checkpoints
        cp_index = session_dir / "checkpoints" / "index.md"
        if cp_index.exists():
            try:
                content = cp_index.read_text(errors="replace")
                self.checkpoint_count = content.count("| ")
            except Exception:
                self.checkpoint_count = 0
        else:
            self.checkpoint_count = 0

        # Count user messages and assistant turns from events.jsonl
        events_path = session_dir / "events.jsonl"
        self.user_messages: int = 0
        self.assistant_turns: int = 0
        self.has_events: bool = events_path.exists()
        if self.has_events:
            try:
                with events_path.open(encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if '"user.message"' in line:
                            self.user_messages += 1
                        elif '"assistant.turn_start"' in line:
                            self.assistant_turns += 1
            except OSError:
                self.has_events = False

    @property
    def display_summary(self) -> str:
        """Best available summary: plan title > session summary > fallback."""
        return self.plan_title or self.summary or "(no summary)"

    @property
    def depth_str(self) -> str:
        """Human-readable session depth (user message count)."""
        if not self.has_events:
            return "—"
        return str(self.user_messages)

    @property
    def age_str(self) -> str:
        """Human-readable age string (e.g. '2h', '3d', '1mo')."""
        if not self.updated_at:
            return "?"
        delta = datetime.now(timezone.utc) - self.updated_at
        if delta.days > 30:
            return f"{delta.days // 30}mo"
        if delta.days > 0:
            return f"{delta.days}d"
        hours = delta.seconds // 3600
        if hours > 0:
            return f"{hours}h"
        return f"{delta.seconds // 60}m"

    @property
    def date_str(self) -> str:
        """Formatted date string for display."""
        d = self.updated_at or self.created_at
        return d.strftime("%Y-%m-%d %H:%M") if d else "?"

    def delete(self) -> bool:
        """Delete the session directory. Returns True on success."""
        try:
            shutil.rmtree(self.session_dir)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            return False

    @property
    def cwd_exists(self) -> bool:
        """Check if the session's working directory still exists."""
        return bool(self.cwd) and os.path.isdir(self.cwd)

    def update_cwd(self, new_path: str) -> bool:
        """Update the session's cwd in workspace.yaml. Returns True on success."""
        workspace_file = self.session_dir / "workspace.yaml"
        if not workspace_file.exists():
            return False
        try:
            data = yaml.safe_load(workspace_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return False
            data["cwd"] = new_path
            workspace_file.write_text(
                yaml.dump(data, default_flow_style=False, sort_keys=False),
                encoding="utf-8",
            )
            self.cwd = new_path
            normalized = os.path.normpath(new_path) if new_path else ""
            self.project = os.path.basename(normalized) if normalized else ""
            return True
        except (OSError, yaml.YAMLError, TypeError):
            return False

    def set_throwaway(self, value: bool) -> bool:
        """Toggle the throw-away marker. Returns True on success.

        The marker is written to the sidecar (.copsearch.json) so it survives
        Copilot rewriting workspace.yaml. We also mirror the change into
        workspace.yaml when present, for any tooling that reads it directly,
        but the sidecar is authoritative.
        """
        from copsearch.sidecar import update_sidecar

        ok_sidecar = update_sidecar(self.session_dir, throwaway=bool(value))

        workspace_file = self.session_dir / "workspace.yaml"
        if workspace_file.exists():
            try:
                data = yaml.safe_load(workspace_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    if value:
                        data["throwaway"] = True
                    else:
                        data.pop("throwaway", None)
                    workspace_file.write_text(
                        yaml.dump(data, default_flow_style=False, sort_keys=False),
                        encoding="utf-8",
                    )
            except (OSError, yaml.YAMLError, TypeError):
                # Sidecar is the source of truth — workspace.yaml is best-effort.
                pass

        if ok_sidecar:
            self.throwaway = bool(value)
        return ok_sidecar

    def refresh_active(self) -> None:
        """Re-check active status from on-disk lock files."""
        self.is_active = False
        self.active_pid = None
        if not self.session_dir.exists():
            return
        for lock_file in self.session_dir.glob("inuse.*.lock"):
            try:
                pid = int(lock_file.stem.split(".")[-1])
            except ValueError:
                continue
            if _is_pid_alive(pid):
                self.is_active = True
                self.active_pid = pid
                return

    @property
    def searchable(self) -> str:
        """Combined lowercase text for full-text search."""
        return " ".join(
            [
                self.summary,
                self.plan_title,
                self.plan_text,
                self.branch,
                self.project,
                self.repository,
                self.cwd,
            ]
        ).lower()


def _infer_forked_from(session_dir: Path, self_id: str) -> str | None:
    """Detect a fork by inspecting the first event in ``events.jsonl``.

    A fork's events log starts with the source's ``session.start`` event,
    which carries ``data.sessionId == <source-id>``. If that id differs from
    the session directory's own id, the session is a fork of that source.

    Returns the inferred source id, or ``None`` if the events log is missing,
    unreadable, or has a matching sessionId (i.e. not a fork).
    """
    events = session_dir / "events.jsonl"
    if not events.exists():
        return None
    try:
        with events.open(encoding="utf-8", errors="replace") as fh:
            first = fh.readline()
    except OSError:
        return None
    if not first:
        return None
    try:
        import json as _json

        obj = _json.loads(first)
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    data = obj.get("data") or {}
    sid = data.get("sessionId") if isinstance(data, dict) else None
    if not sid or not isinstance(sid, str):
        return None
    if sid == self_id:
        return None
    return sid


def _parse_date(val: object) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val
    try:
        s = str(val).replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _clean_title(line: str) -> str:
    return re.sub(r"^#+\s*", "", line).strip()


def load_sessions(session_dir: Path | None = None) -> list[Session]:
    """Load all sessions from the Copilot session state directory.

    Returns sessions sorted by updated_at (most recent first).
    """
    base = session_dir or DEFAULT_SESSION_DIR
    if not base.exists():
        return []

    sessions: list[Session] = []
    for d in base.iterdir():
        # Skip in-flight fork temp dirs — they may have a partial workspace.yaml
        # written before a crash and would otherwise show up as a phantom
        # session.
        if d.name.startswith(".fork-") and d.name.endswith(".tmp"):
            continue
        ws = d / "workspace.yaml"
        if not ws.exists():
            continue
        try:
            with open(ws) as f:
                data = yaml.safe_load(f)
            if data:
                sessions.append(Session(data, d))
        except Exception:
            continue

    sessions.sort(
        key=lambda s: s.updated_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return sessions
