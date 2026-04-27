"""Curses-based interactive TUI for browsing sessions."""

from __future__ import annotations

import curses
import os
import subprocess
import sys
from datetime import datetime, timezone

from copsearch.filters import filter_sessions
from copsearch.session import Session


class TUI:
    """Interactive terminal UI for browsing and resuming Copilot sessions."""

    HELP_TEXT = (
        "↑↓/jk: navigate  /: search  p: project  b: branch  "
        "d: since  a: active  c: clear  s: sort  Enter: details  r: resume  y: copy  q: quit"
    )

    def __init__(self, sessions: list[Session]):
        self.all_sessions = sessions
        self.sessions = list(sessions)
        self.cursor = 0
        self.scroll = 0
        self.filter_text = ""
        self.filter_project = ""
        self.filter_branch = ""
        self.filter_since = ""
        self.filter_active = False
        self.mode = "list"  # list | detail | input | confirm_delete
        self.input_prompt = ""
        self.input_buffer = ""
        self.input_target = ""
        self.detail_scroll = 0
        self.message = ""
        self.sort_key = "updated"  # updated | project | branch

    def run(self) -> None:
        """Launch the interactive TUI."""
        try:
            curses.wrapper(self._main)
        except KeyboardInterrupt:
            pass

    def _main(self, stdscr: curses.window) -> None:
        self.scr = stdscr
        curses.curs_set(0)
        curses.use_default_colors()
        curses.start_color()
        curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)  # selected row
        curses.init_pair(2, curses.COLOR_CYAN, -1)  # header
        curses.init_pair(3, curses.COLOR_YELLOW, -1)  # filter bar
        curses.init_pair(4, curses.COLOR_GREEN, -1)  # status
        curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_YELLOW)  # input bar
        curses.init_pair(6, curses.COLOR_WHITE, -1)  # detail text
        curses.init_pair(7, curses.COLOR_MAGENTA, -1)  # plan header
        curses.init_pair(8, curses.COLOR_GREEN, -1)  # active session indicator
        curses.init_pair(9, curses.COLOR_RED, curses.COLOR_BLACK)  # delete confirm

        self.scr.timeout(100)

        while True:
            self.scr.erase()
            h, w = self.scr.getmaxyx()

            if self.mode == "list":
                self._draw_list(h, w)
            elif self.mode == "detail":
                self._draw_detail(h, w)
            elif self.mode == "input":
                self._draw_list(h, w)
                self._draw_input_bar(h, w)
            elif self.mode == "confirm_delete":
                self._draw_detail(h, w)
                self._draw_confirm_bar(h, w)

            self.scr.refresh()
            key = self.scr.getch()
            if key == -1:
                continue

            if self.mode == "confirm_delete":
                self._handle_confirm_delete(key)
            elif self.mode == "input":
                self._handle_input(key)
            elif self.mode == "detail":
                if self._handle_detail(key):
                    break
            else:
                if self._handle_list(key):
                    break

    # ── Drawing ──────────────────────────────────────────────────────────

    def _draw_list(self, h: int, w: int) -> None:
        # Title bar with active filters
        title = " copsearch — Copilot Session Browser "
        filters_active = []
        if self.filter_project:
            filters_active.append(f"project:{self.filter_project}")
        if self.filter_branch:
            filters_active.append(f"branch:{self.filter_branch}")
        if self.filter_since:
            filters_active.append(f"since:{self.filter_since}")
        if self.filter_text:
            filters_active.append(f"search:{self.filter_text}")
        if self.filter_active:
            filters_active.append("active-only")

        active_count = sum(1 for s in self.all_sessions if s.is_active)
        filter_str = "  ".join(filters_active)
        active_badge = f"  [{active_count} live]" if active_count else ""
        title_line = f"{title}{active_badge}  {filter_str}" if filter_str or active_badge else title
        self._addstr(0, 0, title_line[:w].ljust(w), curses.color_pair(2) | curses.A_BOLD)

        # Column header
        col_hdr = self._format_row(
            "", "Age", "Msgs", "Project", "Branch", "Summary", w,
        )
        self._addstr(1, 0, col_hdr, curses.A_BOLD | curses.A_UNDERLINE)

        # Session rows
        table_h = h - 4  # title + header + status + help
        if self.cursor >= self.scroll + table_h:
            self.scroll = self.cursor - table_h + 1
        if self.cursor < self.scroll:
            self.scroll = self.cursor

        for i in range(table_h):
            idx = self.scroll + i
            row = 2 + i
            if idx >= len(self.sessions):
                break
            s = self.sessions[idx]
            indicator = "●" if s.is_active else " "
            plan_mark = "*" if s.has_plan else " "
            prefix = f"{indicator}{plan_mark}"
            line = self._format_row(
                prefix,
                s.age_str,
                s.depth_str,
                s.project[:18],
                (s.branch or "—")[:24],
                s.display_summary,
                w,
            )
            attr = curses.color_pair(1) | curses.A_BOLD if idx == self.cursor else 0
            self._addstr(row, 0, line[:w].ljust(w), attr)
            # Draw the active indicator in green if active (overwrite first char)
            if s.is_active and idx != self.cursor:
                self._addstr(row, 0, "●", curses.color_pair(8) | curses.A_BOLD)

        # Status bar
        status = f" {len(self.sessions)}/{len(self.all_sessions)} sessions"
        if self.message:
            status += f"  |  {self.message}"
        self._addstr(h - 2, 0, status[:w].ljust(w), curses.color_pair(4))

        # Help bar
        self._addstr(h - 1, 0, self.HELP_TEXT[:w].ljust(w), curses.A_DIM)

    def _draw_detail(self, h: int, w: int) -> None:
        if not self.sessions:
            return
        s = self.sessions[self.cursor]

        lines: list[tuple[str, int]] = []
        lines.append(("=" * (w - 2), curses.color_pair(2)))
        lines.append((f"  Session: {s.id}", curses.color_pair(2) | curses.A_BOLD))
        lines.append(("=" * (w - 2), curses.color_pair(2)))
        lines.append(("", 0))

        fields = [
            ("Status", f"● ACTIVE (PID {s.active_pid})" if s.is_active else "idle"),
            ("Summary", s.summary or "—"),
            ("Project", s.project),
            ("Directory", (s.cwd or "—") + ("  ⚠ path not found" if not s.cwd_exists else "")),
            ("Repository", s.repository or "—"),
            ("Branch", s.branch or "—"),
            ("Created", s.created_at.strftime("%Y-%m-%d %H:%M") if s.created_at else "?"),
            ("Updated", s.updated_at.strftime("%Y-%m-%d %H:%M") if s.updated_at else "?"),
            ("Age", s.age_str),
            ("User messages", str(s.user_messages) if s.has_events else "—"),
            ("Agent turns", str(s.assistant_turns) if s.has_events else "—"),
            ("Summaries", str(s.summary_count)),
        ]
        for label, val in fields:
            attr = curses.color_pair(6)
            if label == "Status" and s.is_active:
                attr = curses.color_pair(8) | curses.A_BOLD
            lines.append((f"  {label + ':':<14} {val}", attr))

        lines.append(("", 0))

        if s.has_plan:
            lines.append(("  -- Plan --", curses.color_pair(7) | curses.A_BOLD))
            for pline in s.plan_text.splitlines()[:40]:
                lines.append((f"  {pline}", curses.color_pair(6)))
        else:
            lines.append(("  (no plan.md)", curses.A_DIM))

        lines.append(("", 0))
        resume_cmd = f"  Resume: copilot --resume {s.id}"
        lines.append((resume_cmd, curses.color_pair(4) | curses.A_BOLD))
        lines.append(("", 0))
        lines.append(
            ("  Press Esc/q: back  Enter/r: resume  y: copy  d: delete  p: change path",
             curses.A_DIM)
        )

        visible = h - 1
        for i in range(visible):
            idx = self.detail_scroll + i
            if idx >= len(lines):
                break
            text, attr = lines[idx]
            self._addstr(i, 0, text[:w].ljust(w), attr)

        if len(lines) > visible:
            pct = int((self.detail_scroll / max(1, len(lines) - visible)) * 100)
            self._addstr(
                h - 1, 0, f" [{pct}%] j/k scroll  Esc: back  Enter: resume  y: copy", curses.A_DIM
            )

    def _draw_input_bar(self, h: int, w: int) -> None:
        prompt = f" {self.input_prompt}: {self.input_buffer}_"
        self._addstr(h - 2, 0, prompt[:w].ljust(w), curses.color_pair(5))

    def _draw_confirm_bar(self, h: int, w: int) -> None:
        s = self.sessions[self.cursor]
        label = s.project or s.id[:12]
        prompt = f" ⚠ Delete session '{label}'? (y/N) "
        self._addstr(h - 2, 0, prompt[:w].ljust(w), curses.color_pair(9) | curses.A_BOLD)

    # ── Key Handling ─────────────────────────────────────────────────────

    def _handle_confirm_delete(self, key: int) -> None:
        """Handle y/n confirmation for session deletion."""
        if key == ord("y"):
            s = self.sessions[self.cursor]
            s.refresh_active()
            if s.is_active:
                self.message = "Session became active — delete cancelled"
                self.mode = "detail"
                return
            if s.delete():
                self.all_sessions.remove(s)
                self.sessions.remove(s)
                self.cursor = min(self.cursor, max(0, len(self.sessions) - 1))
                self.message = f"Deleted session: {s.project or s.id[:12]}"
            else:
                self.message = "Failed to delete session"
            self.mode = "list"
        else:
            # Any other key cancels
            self.message = "Delete cancelled"
            self.mode = "detail"

    def _handle_list(self, key: int) -> bool:
        """Handle keypress in list mode. Returns True to quit."""
        if key in (ord("q"), ord("Q")):
            return True
        elif key in (curses.KEY_DOWN, ord("j")):
            self.cursor = min(self.cursor + 1, max(0, len(self.sessions) - 1))
        elif key in (curses.KEY_UP, ord("k")):
            self.cursor = max(self.cursor - 1, 0)
        elif key == ord("g"):
            self.cursor = 0
            self.scroll = 0
        elif key == ord("G"):
            self.cursor = max(0, len(self.sessions) - 1)
        elif key in (4, curses.KEY_NPAGE):  # Ctrl-D / PageDown
            h, _ = self.scr.getmaxyx()
            self.cursor = min(self.cursor + h // 2, max(0, len(self.sessions) - 1))
        elif key in (21, curses.KEY_PPAGE):  # Ctrl-U / PageUp
            h, _ = self.scr.getmaxyx()
            self.cursor = max(self.cursor - h // 2, 0)
        elif key == ord("/"):
            self._start_input("Search", "search")
        elif key == ord("p"):
            self._start_input("Project filter", "project")
        elif key == ord("b"):
            self._start_input("Branch filter (glob)", "branch")
        elif key == ord("d"):
            self._start_input("Since (e.g. 7d, 24h, 2026-04-01)", "since")
        elif key == ord("c"):
            self.filter_text = ""
            self.filter_project = ""
            self.filter_branch = ""
            self.filter_since = ""
            self.filter_active = False
            self._apply_filters()
            self.message = "Filters cleared"
        elif key == ord("s"):
            sorts = ["updated", "project", "branch"]
            idx = (sorts.index(self.sort_key) + 1) % len(sorts)
            self.sort_key = sorts[idx]
            self._sort_sessions()
            self.message = f"Sort: {self.sort_key}"
        elif key == ord("a"):
            self.filter_active = not self.filter_active
            self._apply_filters()
            self.message = "Active sessions only" if self.filter_active else "Showing all sessions"
        elif key in (curses.KEY_ENTER, 10, 13):
            if self.sessions:
                self.mode = "detail"
                self.detail_scroll = 0
        elif key == ord("r"):
            self._resume_session()
            return True
        elif key == ord("y"):
            self._copy_resume_cmd()

        if key not in (ord("c"),):
            self.message = ""
        return False

    def _handle_detail(self, key: int) -> bool:
        """Handle keypress in detail mode. Returns True to quit (resume)."""
        if key in (27, ord("q"), curses.KEY_LEFT):
            self.mode = "list"
        elif key in (curses.KEY_DOWN, ord("j")):
            self.detail_scroll += 1
        elif key in (curses.KEY_UP, ord("k")):
            self.detail_scroll = max(0, self.detail_scroll - 1)
        elif key in (4, curses.KEY_NPAGE):  # Ctrl-D / PageDown
            h, _ = self.scr.getmaxyx()
            self.detail_scroll += h // 2
        elif key in (21, curses.KEY_PPAGE):  # Ctrl-U / PageUp
            h, _ = self.scr.getmaxyx()
            self.detail_scroll = max(0, self.detail_scroll - h // 2)
        elif key in (curses.KEY_ENTER, 10, 13, ord("r")):
            self._resume_session()
            return True
        elif key == ord("y"):
            self._copy_resume_cmd()
        elif key in (ord("D"), ord("d")):
            s = self.sessions[self.cursor]
            s.refresh_active()
            if s.is_active:
                self.message = "Cannot delete an active session"
            else:
                self.mode = "confirm_delete"
        elif key == ord("p"):
            self._start_input("New path", "path")
        return False

    def _handle_input(self, key: int) -> None:
        if key == 27:  # Esc
            self.mode = "list" if self.input_target != "path" else "detail"
        elif key in (curses.KEY_ENTER, 10, 13):
            if self.input_target == "search":
                self.filter_text = self.input_buffer
            elif self.input_target == "project":
                self.filter_project = self.input_buffer
            elif self.input_target == "branch":
                self.filter_branch = self.input_buffer
            elif self.input_target == "since":
                self.filter_since = self.input_buffer
            elif self.input_target == "path":
                new_path = os.path.expanduser(self.input_buffer.strip())
                if not new_path:
                    self.message = "Path cannot be empty"
                elif not os.path.isdir(new_path):
                    self.message = f"Directory not found: {new_path}"
                else:
                    s = self.sessions[self.cursor]
                    if s.update_cwd(new_path):
                        self.message = f"Path updated to: {new_path}"
                    else:
                        self.message = "Failed to update workspace.yaml"
                self.mode = "detail"
                return
            self._apply_filters()
            self.mode = "list"
            self.message = f"Filter applied: {len(self.sessions)} results"
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            self.input_buffer = self.input_buffer[:-1]
        elif 32 <= key <= 126:
            self.input_buffer += chr(key)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _start_input(self, prompt: str, target: str) -> None:
        self.mode = "input"
        self.input_prompt = prompt
        self.input_target = target
        existing = {
            "search": self.filter_text,
            "project": self.filter_project,
            "branch": self.filter_branch,
            "since": self.filter_since,
        }
        if target == "path" and self.sessions:
            self.input_buffer = self.sessions[self.cursor].cwd
        else:
            self.input_buffer = existing.get(target, "")

    def _apply_filters(self) -> None:
        self.sessions = filter_sessions(
            self.all_sessions,
            project=self.filter_project,
            branch=self.filter_branch,
            since=self.filter_since,
            query=self.filter_text,
        )
        if self.filter_active:
            self.sessions = [s for s in self.sessions if s.is_active]
        self.cursor = min(self.cursor, max(0, len(self.sessions) - 1))
        self.scroll = 0

    def _sort_sessions(self) -> None:
        if self.sort_key == "updated":
            self.sessions.sort(
                key=lambda s: s.updated_at or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
        elif self.sort_key == "project":
            self.sessions.sort(key=lambda s: s.project.lower())
        elif self.sort_key == "branch":
            self.sessions.sort(key=lambda s: s.branch.lower())

    def _resume_session(self) -> None:
        if not self.sessions:
            return
        s = self.sessions[self.cursor]
        curses.endwin()
        cmd = f"copilot --resume {s.id}"

        # Handle stale/moved/inaccessible directories
        target_dir = s.cwd
        home_dir = os.path.expanduser("~")
        warning: str | None = None

        try:
            os.chdir(target_dir)
        except (FileNotFoundError, NotADirectoryError):
            warning = f"\n\033[1;33m⚠ Directory no longer exists: {target_dir}\033[0m"
            target_dir = home_dir
        except PermissionError:
            warning = f"\n\033[1;33m⚠ Permission denied: {target_dir}\033[0m"
            target_dir = home_dir
        except OSError as exc:
            warning = f"\n\033[1;33m⚠ Unable to access directory: {target_dir} ({exc})\033[0m"
            target_dir = home_dir

        if target_dir == home_dir:
            if warning:
                print(warning)
                print("  Resuming from home directory instead.\n")
            os.chdir(home_dir)

        print(f"\n\033[1;32m▶ Resuming session in: {target_dir}\033[0m")
        print(f"  {cmd}\n")
        if sys.platform == "win32":
            # On Windows, os.execlp doesn't replace the process properly —
            # use subprocess to avoid breaking session resume.
            import subprocess as _sp

            raise SystemExit(_sp.call(["copilot", "--resume", s.id]))
        else:
            os.execlp("copilot", "copilot", "--resume", s.id)

    def _copy_resume_cmd(self) -> None:
        if not self.sessions:
            return
        s = self.sessions[self.cursor]
        if s.cwd_exists:
            from shlex import quote
            cmd = f"cd {quote(s.cwd)} && copilot --resume {s.id}"
        else:
            cmd = f"copilot --resume {s.id}"
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["clip"], input=cmd.encode(), check=True,
                )
            elif sys.platform == "darwin":
                subprocess.run(
                    ["pbcopy"], input=cmd.encode(), check=True,
                )
            else:
                subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=cmd.encode(), check=True,
                )
            self.message = "Copied resume command to clipboard"
        except (FileNotFoundError, Exception):
            self.message = f"Resume: {cmd}"

    def _format_row(
        self, prefix: str, age: str, msgs: str, project: str,
        branch: str, summary: str, w: int,
    ) -> str:
        w_pre = 3
        w_age = 5
        w_msgs = 5
        w_proj = 20
        w_branch = 26
        w_summ = max(w - w_pre - w_age - w_msgs - w_proj - w_branch - 3, 10)
        return (
            f"{prefix:<{w_pre}}{age:<{w_age}}{msgs:>{w_msgs}} "
            f"{project:<{w_proj}}{branch:<{w_branch}}{summary[:w_summ]}"
        )

    def _addstr(self, y: int, x: int, text: str, attr: int = 0) -> None:
        try:
            h, w = self.scr.getmaxyx()
            if y < h and x < w:
                self.scr.addnstr(y, x, text, w - x, attr)
        except curses.error:
            pass
