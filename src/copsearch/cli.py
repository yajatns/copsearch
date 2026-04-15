"""CLI entry point for copsearch."""

from __future__ import annotations

import argparse
import sys
import textwrap

from copsearch.filters import filter_sessions
from copsearch.session import Session, load_sessions
from copsearch.tui import TUI


def print_table(sessions: list[Session]) -> None:
    """Print sessions as a formatted table to stdout."""
    if not sessions:
        print("No sessions found.")
        return

    w_age = 5
    w_proj = max(len(s.project) for s in sessions[:50])
    w_proj = min(max(w_proj, 8), 20)
    w_branch = max((len(s.branch) for s in sessions[:50] if s.branch), default=6)
    w_branch = min(max(w_branch, 6), 30)

    hdr = f"  {'Age':<{w_age}} {'Project':<{w_proj}} {'Branch':<{w_branch}} Summary"
    print(f"\033[1m{hdr}\033[0m")
    print("─" * min(len(hdr) + 30, 120))

    for s in sessions:
        indicator = "\033[32m●\033[0m" if s.is_active else " "
        age = s.age_str
        proj = s.project[:w_proj]
        br = (s.branch or "—")[:w_branch]
        summ = s.display_summary[:60]
        print(f"{indicator} {age:<{w_age}} {proj:<{w_proj}} {br:<{w_branch}} {summ}")

    active_count = sum(1 for s in sessions if s.is_active)
    suffix = f"  ({active_count} active)" if active_count else ""
    print(f"\n{len(sessions)} session(s){suffix}")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="copsearch",
        description="Browse, filter, and resume GitHub Copilot CLI sessions.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            examples:
              copsearch                          # interactive TUI
              copsearch --list                   # print all sessions
              copsearch -p Integration           # filter by project
              copsearch -b 'yaj/*'               # filter by branch glob
              copsearch --since 7d               # last 7 days
              copsearch -q "RSS funeth"          # search in summaries/plans
              copsearch -p Integration -b master --since 3d  # combined
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


if __name__ == "__main__":
    main()
