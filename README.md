<div align="center">

# copsearch

**Browse, filter, and resume GitHub Copilot CLI sessions from your terminal.**

[![CI](https://github.com/yajatns/copsearch/actions/workflows/ci.yml/badge.svg)](https://github.com/yajatns/copsearch/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-green.svg)](https://www.python.org/)

</div>

---

If you use [GitHub Copilot CLI](https://githubnext.com/projects/copilot-cli) daily, you know the problem: sessions pile up and there's no built-in way to find the one you need. `copsearch` gives you a fast, standalone tool to search and resume sessions *before* you even start Copilot.

```
$ copsearch --active

   Age   Project          Branch                    Summary
────────────────────────────────────────────────────────────────────────────────
● 12m   openclaw         feat/parser-v2            Rewrite PDF parser to handle multi-column layouts
● 1h    dotfiles         main                      Neovim LSP config for Rust + Go
● 3h    openclaw         fix/ocr-confidence        OCR confidence scoring — false positives on tables

3 session(s)  (3 active)
```

```
$ copsearch -q "database migration"

   Age   Project          Branch                    Summary
────────────────────────────────────────────────────────────────────────────────
  2h    webapp           feat/postgres-16           Migrate from SQLite to Postgres 16
  1d    api-server       fix/migration-rollback     Fix: rollback migration leaves orphan indexes
  5d    webapp           feat/postgres-16           Schema design for user preferences table

3 session(s)
```

## Features

| Feature | Description |
|---------|-------------|
| **Interactive TUI** | Curses-based browser with arrow-key navigation, vim keybindings |
| **Active sessions** | `●` indicator shows which sessions are running in other terminals |
| **Message count** | `Msgs` column shows user messages per session — spot heavy sessions at a glance |
| **Delete sessions** | Press `d` in detail view to delete dead sessions (with confirmation) |
| **Active filter** | `-a` / press `a` in TUI — show only live sessions |
| **Project filter** | `-p webapp` — substring match on project name, repo, or path |
| **Branch filter** | `-b 'feat/*'` — glob pattern matching on branch names |
| **Date filter** | `--since 7d` — relative time (`7d`, `24h`, `30m`) or ISO dates |
| **Full-text search** | `-q "database migration"` — searches summaries, plans, branches, paths |
| **Detail view** | View full plan.md, metadata, and checkpoint info for any session |
| **Quick resume** | Press `Enter` in detail view to resume (launches Copilot in the correct directory) |
| **Clipboard copy** | Press `y` to copy `cd <dir> && copilot --resume <id>` to clipboard |
| **Terminal replay** | `copsearch view <id>` renders the full chat — prompts, replies, tool calls, diffs — as ANSI text |
| **HTML replay** | `copsearch render <id>` writes a self-contained HTML transcript with collapsible tool calls |
| **Cached normalization** | First render parses events.jsonl; subsequent renders are ~10× faster from cache |
| **Zero dependencies** | Only needs Python 3.10+ and PyYAML (usually pre-installed) |

## Install

```bash
# From source
git clone https://github.com/yajatns/copsearch.git
cd copsearch
pip install -e .
```

## Usage

### Interactive TUI

Just run:

```bash
copsearch
```

```
┌─ copsearch — Copilot Session Browser ──── [3 live] ──────────────┐
│    Age  Msgs  Project            Branch                Summary   │
│ ────────────────────────────────────────────────────────────────  │
│ ●  1h     42  openclaw           feat/parser-v2        Rewrite.. │
│ ●  3h     18  openclaw           fix/ocr-confidence    OCR sco.. │
│ ●  5h      7  dotfiles           main                  Neovim ..  │
│ *  1d    156  webapp             feat/postgres-16      Migrate..  │
│    1d     33  api-server         fix/migration-rollback Fix ro.. │
│    3d      —  ml-pipeline        main                  Add dat.. │
│    5d      3  blog               feat/dark-mode        CSS dar.. │
│                                                                  │
│ 42/42 sessions                                                   │
│ ↑↓/jk: navigate  /: search  a: active  Enter: details  q: quit  │
└──────────────────────────────────────────────────────────────────┘
```

**Legend:** `●` = active session, `*` = has plan.md, `Msgs` = user message count (`—` = no event data)

#### TUI Keybindings

| Key | Action |
|-----|--------|
| `↑`/`↓` or `j`/`k` | Navigate sessions |
| `g` / `G` | Jump to top / bottom |
| `Ctrl-D` / `Ctrl-U` or `PgDn`/`PgUp` | Half-page down / up |
| `/` | Search across all session text |
| `p` | Filter by project |
| `b` | Filter by branch (glob pattern) |
| `d` | Filter by date/age |
| `a` | Toggle: show only active (running) sessions |
| `c` | Clear all filters |
| `s` | Cycle sort: updated → project → branch |
| `Enter` | Detail view (full metadata + plan.md) |
| `Enter` (in detail) | Resume session (launches Copilot in correct dir) |
| `r` | Resume session |
| `v` (in detail) | Render the conversation as ANSI text in the terminal |
| `h` (in detail) | Render as HTML and open in the browser |
| `y` | Copy resume command to clipboard |
| `d` (in detail) | Delete session (with confirmation; blocked for active sessions) |
| `q` | Quit |

### CLI Mode

When you pass any filter flag, `copsearch` prints a table and exits (no TUI):

```bash
# Show only active sessions (running in other terminals)
copsearch --active

# Filter by project
copsearch -p openclaw

# Filter by branch glob
copsearch -b 'feat/*'

# Last 7 days only
copsearch --since 7d

# Full-text search
copsearch -q "parser PDF"

# Combine filters
copsearch -p webapp -b 'feat/*' --since 3d

# Get resume command for a session (prefix match on ID)
copsearch --id 884bb
# → cd /home/user/projects/openclaw && copilot --resume 884bb6a6-...

# List everything
copsearch --list
```

## Viewing a session

Beyond browsing, `copsearch` can render a full session — the user prompts,
assistant replies, every tool call with arguments and results — either as
ANSI text in your terminal or as a self-contained HTML file.

```bash
# Render in the terminal (auto-pages via $PAGER)
copsearch view 884bb

# Render as a self-contained HTML file
copsearch render 884bb              # writes ~/.copsearch/renders/<id>.html, opens it
copsearch render 884bb -o foo.html  # custom output path
copsearch render 884bb --no-open    # don't open the browser

# View options
copsearch view 884bb --tools full   # show tool args and results inline (default: brief chips)
copsearch view 884bb --tools none   # chat only, hide all tool calls
copsearch view 884bb --max-output 30  # cap each tool result at 30 lines
copsearch view 884bb --turn 5       # only render user turn 5 and its assistant response
copsearch view 884bb --grep error   # filter to turns matching a pattern
copsearch view 884bb --plain        # disable ANSI colors (also: NO_COLOR=1)
```

The HTML is a single self-contained file (no external assets, no network) so
it's safe to email, attach to a PR, or open from anywhere. Each tool-call
chip is collapsed by default — click to expand and see arguments, result,
and a unified diff for any file edits.

## Cache and indexing

The first `view` or `render` of a session parses its events.jsonl and
caches the normalized form at `~/.copsearch/cache/<id>/`. Subsequent renders
of the same session are ~10× faster.

```bash
# Pre-warm the cache for a window of recent sessions
copsearch index --since 7d

# Pre-warm in the background — no daemon, just shell backgrounding
copsearch index --all &

# Inspect the cache
copsearch cache stats
copsearch cache clear --orphans   # remove caches whose source session is gone
copsearch cache clear --id 884bb
copsearch cache clear             # wipe everything (asks for confirmation)
```

Active sessions (those still being appended to) are always re-parsed —
their cache would be stale by the time it lands. Idle sessions are cached
once and reused until events.jsonl gets newer.

## How It Works

`copsearch` reads session data from `~/.copilot/session-state/`:

```
~/.copilot/session-state/
├── <session-uuid>/
│   ├── workspace.yaml      # id, cwd, branch, repo, summary, dates
│   ├── plan.md             # task plan (if created during session)
│   ├── inuse.<PID>.lock    # present while session is running ← active detection!
│   ├── events.jsonl       # event log (user messages, tool calls, turns)
│   ├── checkpoints/
│   │   └── index.md        # checkpoint history
│   └── files/              # session artifacts
└── ...
```

**Active session detection** works by checking `inuse.<PID>.lock` files — if the PID is still running, the session is live. This lets `copsearch` show you which sessions are open in other terminal windows.

Each session's `workspace.yaml` contains metadata like:

```yaml
id: 884bb6a6-5491-470f-9af7-5e866ff38afc
cwd: /home/user/projects/openclaw
repository: org/openclaw
branch: feat/parser-v2
summary: Rewrite PDF parser to handle multi-column layouts
created_at: 2026-04-07T16:59:51Z
updated_at: 2026-04-14T17:57:52Z
```

The search indexes summaries, plan titles, plan text, branch names, project names, and paths — so you can find sessions by what you *did*, not just when.

## Project Structure

```
copsearch/
├── src/copsearch/
│   ├── __init__.py        # Package version
│   ├── cli.py             # CLI entry point + view/render/index/cache subcommands
│   ├── session.py         # Session data model, loader, active detection
│   ├── filters.py         # Filtering logic
│   ├── tui.py             # Curses-based interactive TUI
│   ├── normalize.py       # events.jsonl → canonical Turn list (renderer-agnostic)
│   ├── cache.py           # On-disk gzipped cache of normalized sessions
│   ├── render_cli.py      # ANSI/plain-text renderer for the terminal
│   └── render_html.py     # Self-contained HTML renderer
├── tests/
│   ├── test_session.py    # Session loader tests
│   ├── test_filters.py    # Filter logic tests
│   ├── test_normalize.py  # Normalizer tests
│   ├── test_cache.py      # Cache layer tests
│   ├── test_render_cli.py # CLI renderer tests
│   └── test_render_html.py# HTML renderer tests
├── pyproject.toml       # Package config
├── LICENSE              # MIT
└── README.md
```

## Compared To Existing Tools

There are great session managers for Claude Code ([resume-resume](https://github.com/eidos-agi/resume-resume), [CCHV](https://github.com/jhlee0409/claude-code-history-viewer), [cchb](https://github.com/iselegant/cchb)) — but none of them work with **GitHub Copilot CLI**, which stores sessions in a completely different format at `~/.copilot/session-state/`.

`copsearch` is purpose-built for GitHub Copilot CLI sessions.

## Requirements

- Python 3.10+
- PyYAML (`pip install pyyaml`)
- macOS, Linux, or Windows
  - On Windows, `windows-curses` is auto-installed as a dependency

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## License

[MIT](LICENSE)
