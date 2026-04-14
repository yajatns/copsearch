"""Curses-based interactive TUI for browsing sessions."""

from __future__ import annotations

import curses
import os
import subprocess
from datetime import datetime, timezone

from copsearch.filters import filter_sessions
from copsearch.session import Session


class TUI:
    """Interactive terminal UI for browsing and resuming Copilot sessions."""

    HELP_TEXT = (
        "↑↓/jk: navigate  /: search  p: project  b: branch  "
        "d: since  c: clear  s: sort  Enter: details  r: resume  y: copy  q: quit"
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
        self.mode = "list"  # list | detail | input
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

            self.scr.refresh()
            key = self.scr.getch()
            if key == -1:
                continue

            if self.mode == "input":
                self._handle_input(key)
            elif self.mode == "detail":
                self._handle_detail(key)
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

        filter_str = "  ".join(filters_active)
        title_line = f"{title}  {filter_str}" if filter_str else title
        self._addstr(0, 0, title_line[:w].ljust(w), curses.color_pair(2) | curses.A_BOLD)

        # Column header
        col_hdr = self._format_row("Age", "Project", "Branch", "Summary", w)
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
            line = self._format_row(
                s.age_str,
                s.project[:18],
                (s.branch or "—")[:24],
                s.display_summary,
                w,
            )
            attr = curses.color_pair(1) | curses.A_BOLD if idx == self.cursor else 0
            if s.has_plan:
                line = "* " + line[2:] if w > 30 else line
            self._addstr(row, 0, line[:w].ljust(w), attr)

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
            ("Summary", s.summary or "—"),
            ("Project", s.project),
            ("Directory", s.cwd),
            ("Repository", s.repository or "—"),
            ("Branch", s.branch or "—"),
            ("Created", s.created_at.strftime("%Y-%m-%d %H:%M") if s.created_at else "?"),
            ("Updated", s.updated_at.strftime("%Y-%m-%d %H:%M") if s.updated_at else "?"),
            ("Age", s.age_str),
            ("Summaries", str(s.summary_count)),
        ]
        for label, val in fields:
            lines.append((f"  {label + ':':<14} {val}", curses.color_pair(6)))

        lines.append(("", 0))

        if s.has_plan:
            lines.append(("  -- Plan --", curses.color_pair(7) | curses.A_BOLD))
            for pline in s.plan_text.splitlines()[:40]:
                lines.append((f"  {pline}", curses.color_pair(6)))
        else:
            lines.append(("  (no plan.md)", curses.A_DIM))

        lines.append(("", 0))
        resume_cmd = f"  Resume: copilot -r {s.id}"
        lines.append((resume_cmd, curses.color_pair(4) | curses.A_BOLD))
        lines.append(("", 0))
        lines.append(
            ("  Press Esc/q to go back, r to resume, y to copy resume cmd", curses.A_DIM)
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
                h - 1, 0, f" [{pct}%] j/k scroll  Esc: back  r: resume  y: copy", curses.A_DIM
            )

    def _draw_input_bar(self, h: int, w: int) -> None:
        prompt = f" {self.input_prompt}: {self.input_buffer}_"
        self._addstr(h - 2, 0, prompt[:w].ljust(w), curses.color_pair(5))

    # ── Key Handling ─────────────────────────────────────────────────────

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
        elif key == 4:  # Ctrl-D
            h, _ = self.scr.getmaxyx()
            self.cursor = min(self.cursor + h // 2, max(0, len(self.sessions) - 1))
        elif key == 21:  # Ctrl-U
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
            self._apply_filters()
            self.message = "Filters cleared"
        elif key == ord("s"):
            sorts = ["updated", "project", "branch"]
            idx = (sorts.index(self.sort_key) + 1) % len(sorts)
            self.sort_key = sorts[idx]
            self._sort_sessions()
            self.message = f"Sort: {self.sort_key}"
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

    def _handle_detail(self, key: int) -> None:
        if key in (27, ord("q"), curses.KEY_LEFT):
            self.mode = "list"
        elif key in (curses.KEY_DOWN, ord("j")):
            self.detail_scroll += 1
        elif key in (curses.KEY_UP, ord("k")):
            self.detail_scroll = max(0, self.detail_scroll - 1)
        elif key == ord("r"):
            self._resume_session()
        elif key == ord("y"):
            self._copy_resume_cmd()

    def _handle_input(self, key: int) -> None:
        if key == 27:  # Esc
            self.mode = "list"
        elif key in (curses.KEY_ENTER, 10, 13):
            if self.input_target == "search":
                self.filter_text = self.input_buffer
            elif self.input_target == "project":
                self.filter_project = self.input_buffer
            elif self.input_target == "branch":
                self.filter_branch = self.input_buffer
            elif self.input_target == "since":
                self.filter_since = self.input_buffer
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
        self.input_buffer = existing.get(target, "")

    def _apply_filters(self) -> None:
        self.sessions = filter_sessions(
            self.all_sessions,
            project=self.filter_project,
            branch=self.filter_branch,
            since=self.filter_since,
            query=self.filter_text,
        )
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
        cmd = f"copilot -r {s.id}"
        print(f"\n\033[1;32m▶ Resuming session in: {s.cwd}\033[0m")
        print(f"  {cmd}\n")
        os.chdir(s.cwd)
        os.execlp("copilot", "copilot", "-r", s.id)

    def _copy_resume_cmd(self) -> None:
        if not self.sessions:
            return
        s = self.sessions[self.cursor]
        cmd = f"cd {s.cwd} && copilot -r {s.id}"
        try:
            subprocess.run(["pbcopy"], input=cmd.encode(), check=True)
            self.message = "Copied resume command to clipboard"
        except FileNotFoundError:
            # Linux fallback
            try:
                subprocess.run(["xclip", "-selection", "clipboard"], input=cmd.encode(), check=True)
                self.message = "Copied resume command to clipboard"
            except Exception:
                self.message = f"Resume: {cmd}"
        except Exception:
            self.message = f"Resume: {cmd}"

    def _format_row(self, age: str, project: str, branch: str, summary: str, w: int) -> str:
        w_age = 6
        w_proj = 20
        w_branch = 26
        w_summ = max(w - w_age - w_proj - w_branch - 3, 10)
        return f"{age:<{w_age}}{project:<{w_proj}}{branch:<{w_branch}}{summary[:w_summ]}"

    def _addstr(self, y: int, x: int, text: str, attr: int = 0) -> None:
        try:
            h, w = self.scr.getmaxyx()
            if y < h and x < w:
                self.scr.addnstr(y, x, text, w - x, attr)
        except curses.error:
            pass
