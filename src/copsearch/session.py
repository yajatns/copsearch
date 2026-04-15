"""Session data model and loader for Copilot CLI sessions."""

from __future__ import annotations

import os
import re
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
    )

    def __init__(self, data: dict, session_dir: Path):
        self.id: str = data.get("id", "")
        self.cwd: str = data.get("cwd", "")
        self.project: str = os.path.basename(self.cwd) if self.cwd else ""
        self.git_root: str = data.get("git_root", "")
        self.repository: str = data.get("repository", "")
        self.branch: str = data.get("branch", "")
        self.summary: str = data.get("summary", "")
        self.summary_count: int = data.get("summary_count", 0)

        self.created_at: datetime | None = _parse_date(data.get("created_at"))
        self.updated_at: datetime | None = _parse_date(data.get("updated_at"))

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
        if events_path.exists():
            try:
                with open(events_path, errors="replace") as f:
                    for line in f:
                        if '"user.message"' in line:
                            self.user_messages += 1
                        elif '"assistant.turn_start"' in line:
                            self.assistant_turns += 1
            except Exception:
                pass

    @property
    def display_summary(self) -> str:
        """Best available summary: plan title > session summary > fallback."""
        return self.plan_title or self.summary or "(no summary)"

    @property
    def depth_str(self) -> str:
        """Human-readable session depth (user message count)."""
        n = self.user_messages
        if n == 0:
            return "—"
        return str(n)

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
