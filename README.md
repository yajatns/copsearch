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
| **Active filter** | `-a` / press `a` in TUI — show only live sessions |
| **Project filter** | `-p webapp` — substring match on project name, repo, or path |
| **Branch filter** | `-b 'feat/*'` — glob pattern matching on branch names |
| **Date filter** | `--since 7d` — relative time (`7d`, `24h`, `30m`) or ISO dates |
| **Full-text search** | `-q "database migration"` — searches summaries, plans, branches, paths |
| **Detail view** | View full plan.md, metadata, and checkpoint info for any session |
| **Quick resume** | Press `Enter` in detail view to resume (launches Copilot in the correct directory) |
| **Clipboard copy** | Press `y` to copy `cd <dir> && copilot --resume <id>` to clipboard |
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
│    Age   Project            Branch                Summary        │
│ ────────────────────────────────────────────────────────────────  │
│ ●  1h    openclaw           feat/parser-v2        Rewrite PDF... │
│ ●  3h    openclaw           fix/ocr-confidence    OCR scoring... │
│ ●  5h    dotfiles           main                  Neovim LSP...  │
│ *  1d    webapp             feat/postgres-16      Migrate to...  │
│    1d    api-server         fix/migration-rollback Fix rollba... │
│    3d    ml-pipeline        main                  Add data va... │
│    5d    blog               feat/dark-mode        CSS dark mo... │
│                                                                  │
│ 42/42 sessions                                                   │
│ ↑↓/jk: navigate  /: search  a: active  Enter: details  q: quit  │
└──────────────────────────────────────────────────────────────────┘
```

**Legend:** `●` = session is running in another terminal, `*` = session has a plan.md

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
| `y` | Copy resume command to clipboard |
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

## How It Works

`copsearch` reads session data from `~/.copilot/session-state/`:

```
~/.copilot/session-state/
├── <session-uuid>/
│   ├── workspace.yaml      # id, cwd, branch, repo, summary, dates
│   ├── plan.md             # task plan (if created during session)
│   ├── inuse.<PID>.lock    # present while session is running ← active detection!
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
│   ├── __init__.py      # Package version
│   ├── cli.py           # CLI entry point and argument parsing
│   ├── session.py       # Session data model, loader, active detection
│   ├── filters.py       # Filtering logic
│   └── tui.py           # Curses-based interactive TUI
├── tests/
│   ├── test_session.py  # Session loader tests
│   └── test_filters.py  # Filter logic tests
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
- macOS or Linux (curses is built-in)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## License

[MIT](LICENSE)
