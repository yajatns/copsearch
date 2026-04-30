"""CLI entry point for copsearch."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from copsearch.filters import filter_sessions
from copsearch.session import Session, load_sessions
from copsearch.tui import TUI

SUBCOMMANDS = {"view", "render", "index", "cache"}


def print_table(sessions: list[Session]) -> None:
    """Print sessions as a formatted table to stdout."""
    if not sessions:
        print("No sessions found.")
        return

    w_age = 5
    w_msgs = 4
    w_proj = max(len(s.project) for s in sessions[:50])
    w_proj = min(max(w_proj, 8), 20)
    w_branch = max((len(s.branch) for s in sessions[:50] if s.branch), default=6)
    w_branch = min(max(w_branch, 6), 30)

    hdr = (
        f"  {'Age':<{w_age}} {'Msgs':>{w_msgs}} "
        f"{'Project':<{w_proj}} {'Branch':<{w_branch}} Summary"
    )
    print(f"\033[1m{hdr}\033[0m")
    print("─" * min(len(hdr) + 30, 120))

    for s in sessions:
        indicator = "\033[32m●\033[0m" if s.is_active else " "
        age = s.age_str
        msgs = s.depth_str
        proj = s.project[:w_proj]
        br = (s.branch or "—")[:w_branch]
        summ = s.display_summary[:60]
        print(
            f"{indicator} {age:<{w_age}} {msgs:>{w_msgs}} "
            f"{proj:<{w_proj}} {br:<{w_branch}} {summ}"
        )

    active_count = sum(1 for s in sessions if s.is_active)
    suffix = f"  ({active_count} active)" if active_count else ""
    print(f"\n{len(sessions)} session(s){suffix}")


def main() -> None:
    """Main entry point."""
    # Subcommand mode: copsearch view <id>, copsearch render <id>, etc.
    # Anything else falls through to the legacy flag-only interface.
    if len(sys.argv) > 1 and sys.argv[1] in SUBCOMMANDS:
        return _dispatch_subcommand(sys.argv[1], sys.argv[2:])
    _legacy_main()


def _legacy_main() -> None:
    """Original flag-only interface — preserved for backward compatibility."""
    parser = argparse.ArgumentParser(
        prog="copsearch",
        description="Browse, filter, and resume GitHub Copilot CLI sessions.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            examples:
              copsearch                          # interactive TUI
              copsearch --list                   # print all sessions
              copsearch --active                 # show only running sessions
              copsearch -p webapp                # filter by project
              copsearch -b 'feat/*'              # filter by branch glob
              copsearch --since 7d               # last 7 days
              copsearch -q "database migration"  # search in summaries/plans
              copsearch -p webapp --since 3d     # combined filters

              copsearch view <id>                # render a session in the terminal
              copsearch render <id>              # render a session as HTML
              copsearch index --since 7d         # pre-warm the cache
              copsearch cache stats              # cache size + orphans
        """),
    )
    parser.add_argument("-l", "--list", action="store_true", help="Non-interactive table output")
    parser.add_argument("-p", "--project", default="", help="Filter by project name (substring)")
    parser.add_argument("-b", "--branch", default="", help="Filter by branch (glob pattern)")
    parser.add_argument("--since", default="", help="Filter by age (e.g. 7d, 24h, 2026-04-01)")
    parser.add_argument("-q", "--query", default="", help="Search summaries, plans, branches")
    parser.add_argument(
        "--id", default="", help="Print resume command for a specific session ID (prefix match)"
    )
    parser.add_argument(
        "-a", "--active", action="store_true", help="Show only active (running) sessions"
    )
    parser.add_argument(
        "-V", "--version", action="store_true", help="Print version and exit"
    )
    args = parser.parse_args()

    if args.version:
        from copsearch import __version__

        print(f"copsearch {__version__}")
        sys.exit(0)

    sessions = load_sessions()
    if not sessions:
        print("No sessions found in ~/.copilot/session-state/")
        sys.exit(1)

    # Quick ID lookup mode
    if args.id:
        matches = [s for s in sessions if s.id.startswith(args.id)]
        if not matches:
            print(f"No session matching ID prefix: {args.id}")
            sys.exit(1)
        s = matches[0]
        print(f"cd {s.cwd} && copilot --resume {s.id}")
        sys.exit(0)

    filtered = filter_sessions(sessions, args.project, args.branch, args.since, args.query)
    if args.active:
        filtered = [s for s in filtered if s.is_active]

    has_any_filter = args.project or args.branch or args.since or args.query or args.active

    if args.list or has_any_filter:
        print_table(filtered)
    else:
        tui = TUI(sessions)
        tui.run()


# ── Subcommand dispatcher ────────────────────────────────────────────────────


def _dispatch_subcommand(cmd: str, argv: list[str]) -> None:
    if cmd == "view":
        return _cmd_view(argv)
    if cmd == "render":
        return _cmd_render(argv)
    if cmd == "index":
        return _cmd_index(argv)
    if cmd == "cache":
        return _cmd_cache(argv)
    print(f"Unknown subcommand: {cmd}", file=sys.stderr)
    sys.exit(2)


def _resolve_session(id_prefix: str) -> Session:
    """Look up a session by ID prefix. Exit with a helpful error if not found."""
    sessions = load_sessions()
    if not sessions:
        print("No sessions found in ~/.copilot/session-state/", file=sys.stderr)
        sys.exit(1)
    matches = [s for s in sessions if s.id.startswith(id_prefix)]
    if not matches:
        print(f"No session matching ID prefix: {id_prefix}", file=sys.stderr)
        sys.exit(1)
    if len(matches) > 1:
        print(
            f"Ambiguous prefix '{id_prefix}' — matches {len(matches)} sessions:",
            file=sys.stderr,
        )
        for m in matches[:10]:
            print(f"  {m.id}  {m.display_summary[:60]}", file=sys.stderr)
        sys.exit(1)
    return matches[0]


# ── view subcommand ──────────────────────────────────────────────────────────


def _cmd_view(argv: list[str]) -> None:
    """copsearch view <id> — render a session as ANSI text in the terminal."""
    parser = argparse.ArgumentParser(
        prog="copsearch view",
        description="Render a Copilot session as ANSI-colored text in the terminal.",
    )
    parser.add_argument("id", help="Session ID (or unique prefix)")
    parser.add_argument(
        "--tools",
        choices=["none", "brief", "full"],
        default="brief",
        help="Tool-call detail level (default: brief)",
    )
    parser.add_argument(
        "--max-output",
        type=int,
        default=0,
        metavar="N",
        help="Cap each tool result to N lines (0 = unlimited, default)",
    )
    parser.add_argument(
        "--turn",
        type=int,
        default=None,
        metavar="N",
        help="Only show user turn N and its assistant response",
    )
    parser.add_argument(
        "--grep", default="", metavar="PATTERN", help="Filter to turns matching pattern"
    )
    parser.add_argument(
        "--no-system", action="store_true", help="Hide session-start/skill/shutdown markers"
    )
    parser.add_argument("--plain", action="store_true", help="Disable ANSI colors")
    parser.add_argument("--no-pager", action="store_true", help="Don't pipe to $PAGER")
    parser.add_argument(
        "--no-cache", action="store_true", help="Force re-parse, don't read or write the cache"
    )
    parser.add_argument(
        "-w",
        "--width",
        type=int,
        default=0,
        help="Terminal width (default: autodetect)",
    )
    args = parser.parse_args(argv)

    from copsearch import cache as cache_mod
    from copsearch.render_cli import RenderOptions, detect_color_support, iter_lines

    session = _resolve_session(args.id)
    ns = cache_mod.get(session, use_cache=not args.no_cache)

    use_color = (not args.plain) and detect_color_support(sys.stdout)
    opts = RenderOptions(
        color=use_color,
        tools=args.tools,
        max_output_lines=args.max_output,
        only_turn=args.turn,
        grep=args.grep,
        show_system_events=not args.no_system,
        width=args.width,
    )

    if args.no_pager or not sys.stdout.isatty():
        for line in iter_lines(ns, opts):
            print(line)
        return

    _print_via_pager(iter_lines(ns, opts))


def _print_via_pager(lines) -> None:
    """Pipe lines into ``$PAGER`` (or ``less -R``). Falls back to direct print."""
    pager = os.environ.get("PAGER") or "less"
    pager_args: list[str] = []
    if pager == "less":
        # -R: pass ANSI through. -F: quit if output fits one screen. -X: don't init/deinit.
        # +g: start at top.
        pager_args = ["-RFX"]
    try:
        proc = subprocess.Popen(
            [pager, *pager_args],
            stdin=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
    except (OSError, FileNotFoundError):
        for line in lines:
            print(line)
        return
    try:
        assert proc.stdin is not None
        for line in lines:
            proc.stdin.write(line + "\n")
        proc.stdin.close()
    except (BrokenPipeError, OSError):
        pass  # User pressed q before we finished writing — that's fine.
    proc.wait()


# ── render subcommand (HTML) ─────────────────────────────────────────────────


def _cmd_render(argv: list[str]) -> None:
    """copsearch render <id> — write the session as a self-contained HTML file."""
    parser = argparse.ArgumentParser(
        prog="copsearch render",
        description="Render a Copilot session as a self-contained HTML file.",
    )
    parser.add_argument("id", help="Session ID (or unique prefix)")
    parser.add_argument(
        "-o",
        "--output",
        default="",
        metavar="PATH",
        help="Output file (default: ~/.copsearch/renders/<id>.html)",
    )
    parser.add_argument(
        "--no-open", action="store_true", help="Don't try to open the file in a browser"
    )
    parser.add_argument(
        "--no-cache", action="store_true", help="Force re-parse, don't read or write the cache"
    )
    parser.add_argument(
        "--print", dest="to_stdout", action="store_true", help="Write HTML to stdout instead"
    )
    args = parser.parse_args(argv)

    from copsearch import cache as cache_mod
    from copsearch.render_html import render_html

    session = _resolve_session(args.id)
    ns = cache_mod.get(session, use_cache=not args.no_cache)
    html = render_html(ns)

    if args.to_stdout:
        sys.stdout.write(html)
        return

    if args.output:
        out_path = Path(args.output).expanduser().resolve()
    else:
        out_path = Path.home() / ".copsearch" / "renders" / f"{session.id}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path}")

    if not args.no_open:
        _open_in_browser(out_path)


def _open_in_browser(path: Path) -> None:
    """Open ``path`` in the user's default browser. Best effort; never raises."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        elif sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except (OSError, FileNotFoundError):
        pass


# ── index subcommand ─────────────────────────────────────────────────────────


def _cmd_index(argv: list[str]) -> None:
    """copsearch index [<id> | --all | --since 7d] — pre-warm the normalize cache."""
    parser = argparse.ArgumentParser(
        prog="copsearch index",
        description="Pre-normalize one or more sessions into the cache.",
    )
    parser.add_argument("id", nargs="?", default="", help="Session ID prefix to index (optional)")
    parser.add_argument("--all", action="store_true", help="Index every idle session on disk")
    parser.add_argument(
        "--since", default="", help="Only index sessions updated within this window (e.g. 7d)"
    )
    parser.add_argument("--force", action="store_true", help="Re-index even if cache is fresh")
    parser.add_argument("-q", "--quiet", action="store_true", help="No per-session output")
    args = parser.parse_args(argv)

    from copsearch import cache as cache_mod

    if args.id:
        session = _resolve_session(args.id)
        targets = [session]
    else:
        sessions = load_sessions()
        if args.since:
            sessions = filter_sessions(sessions, since=args.since)
        if not args.all and not args.since:
            print(
                "Specify a session ID, --all, or --since <window>. "
                "Refusing to index everything implicitly.",
                file=sys.stderr,
            )
            sys.exit(2)
        targets = sessions

    indexed = 0
    skipped_active = 0
    skipped_fresh = 0
    skipped_no_events = 0
    for s in targets:
        if s.is_active:
            skipped_active += 1
            if not args.quiet:
                print(f"  skip (active):  {s.id[:8]}  {s.display_summary[:50]}")
            continue
        events_path = s.session_dir / "events.jsonl"
        if not events_path.exists():
            skipped_no_events += 1
            continue
        if not args.force and cache_mod.is_fresh(s):
            skipped_fresh += 1
            if not args.quiet:
                print(f"  skip (fresh):   {s.id[:8]}  {s.display_summary[:50]}")
            continue
        ns = cache_mod.get(s, use_cache=False)  # parse from disk...
        cache_mod.store(s, ns)  # ...then write cache
        indexed += 1
        if not args.quiet:
            print(f"  indexed:        {s.id[:8]}  {len(ns.turns)} turns  {s.display_summary[:40]}")

    print(
        f"\nIndexed {indexed} session(s)."
        f"  {skipped_fresh} already fresh."
        f"  {skipped_active} active."
        f"  {skipped_no_events} without events."
    )


# ── cache subcommand ─────────────────────────────────────────────────────────


def _cmd_cache(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="copsearch cache",
        description="Inspect or clean the on-disk normalize cache.",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    sub.add_parser("stats", help="Show cache size and orphan count")

    p_clear = sub.add_parser("clear", help="Delete cache entries")
    p_clear.add_argument("--id", default="", help="Clear just this session's cache")
    p_clear.add_argument(
        "--orphans", action="store_true", help="Clear caches whose source session is gone"
    )
    p_clear.add_argument("--yes", action="store_true", help="Skip confirmation prompt")

    args = parser.parse_args(argv)

    from copsearch import cache as cache_mod

    if args.action == "stats":
        sessions = load_sessions()
        st = cache_mod.stats(sessions=sessions)
        print(f"Cache directory: {st.cache_dir}")
        print(f"Entries:         {st.entries}")
        print(f"Total size:      {_humanize_bytes(st.total_bytes)}")
        if st.orphan_ids:
            print(f"Orphan entries:  {len(st.orphan_ids)} (source session deleted)")
            for oid in st.orphan_ids[:10]:
                print(f"  {oid}")
            if len(st.orphan_ids) > 10:
                print(f"  … and {len(st.orphan_ids) - 10} more")
            print("\nRun 'copsearch cache clear --orphans' to remove them.")
        return

    if args.action == "clear":
        if args.id:
            removed = cache_mod.clear(session_id=args.id)
            print(f"Removed {removed} cache entr{'y' if removed == 1 else 'ies'}.")
            return
        if args.orphans:
            sessions = load_sessions()
            removed = cache_mod.clear(orphans_only=True, sessions=sessions)
            print(f"Removed {removed} orphan{'' if removed == 1 else 's'}.")
            return
        if not args.yes:
            resp = input(
                f"Wipe entire cache at {cache_mod.DEFAULT_CACHE_DIR}? [y/N] "
            ).strip().lower()
            if resp not in ("y", "yes"):
                print("Cancelled.")
                return
        removed = cache_mod.clear()
        print(f"Removed {removed} cache entr{'y' if removed == 1 else 'ies'}.")


def _humanize_bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    val = float(n)
    for unit in units:
        if val < 1024:
            return f"{val:.1f} {unit}"
        val /= 1024
    return f"{val:.1f} TB"


if __name__ == "__main__":
    main()
