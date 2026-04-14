<div align="center">

# copsearch

**Browse, filter, and resume GitHub Copilot CLI sessions from your terminal.**

</div>

---

If you use [GitHub Copilot CLI](https://githubnext.com/projects/copilot-cli) daily, you know the problem: sessions pile up and there's no built-in way to find the one you need. `copsearch` gives you a fast, standalone tool to search and resume sessions *before* you even start Copilot.

```
$ copsearch -q "RSS funeth"
Age   Project     Branch                    Summary
────────────────────────────────────────────────────────────────────────────────
1h    Integration yaj/rss-traffic-dna-down  WHLK Certification Resumption Plan
2h    Integration yaj/rss-traffic-dna-down  Run RSS Traffic Without DNA
20h   s21f1       master                    Plan: Add RSS Test Cases to funeth_tests.py
14d   Integration yajsingh/funeth-rss-tests Fix Git Pull Error

4 session(s)
```

## Features

| Feature | Description |
|---------|-------------|
| **Interactive TUI** | Curses-based browser with arrow-key navigation, vim keybindings |
| **Project filter** | `-p Integration` — substring match on project name, repo, or path |
| **Branch filter** | `-b 'yaj/*'` — glob pattern matching on branch names |
| **Date filter** | `--since 7d` — relative time (`7d`, `24h`, `30m`) or ISO dates |
| **Full-text search** | `-q "RSS funeth"` — searches summaries, plans, branches, paths |
| **Detail view** | View full plan.md, metadata, and checkpoint info for any session |
| **Quick resume** | Press `r` or use `--id` to get the resume command with correct `cd` |
| **Clipboard copy** | Press `y` to copy `cd <dir> && copilot -r <id>` to clipboard |
| **Zero dependencies** | Only needs Python 3.10+ and PyYAML (usually pre-installed) |

## Install

```bash
# From PyPI (once published)
pip install copsearch

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
┌─ copsearch — Copilot Session Browser ─────────────────────────────┐
│ Age   Project            Branch                    Summary        │
│ ──────────────────────────────────────────────────────────────── │
│ 1h    Integration        yaj/rss-traffic-dna-down  WHLK Cert...  │
│ 2h    IntegrationTools   yaj/skill-test-case-docs  AI Onboard... │
│ 12h   exe                main                      DPUUtility... │
│ 20h   s21f1              master                    RSS Tests...   │
│ 1d    FunTools           yaj/dpc_cli_improvements  DPC CLI...     │
│                                                                   │
│ 131/131 sessions                                                  │
│ ↑↓/jk: navigate  /: search  p: project  b: branch  r: resume    │
└───────────────────────────────────────────────────────────────────┘
```

#### TUI Keybindings

| Key | Action |
|-----|--------|
| `↑`/`↓` or `j`/`k` | Navigate sessions |
| `g` / `G` | Jump to top / bottom |
| `Ctrl-D` / `Ctrl-U` | Half-page down / up |
| `/` | Search across all session text |
| `p` | Filter by project |
| `b` | Filter by branch (glob pattern) |
| `d` | Filter by date/age |
| `c` | Clear all filters |
| `s` | Cycle sort: updated → project → branch |
| `Enter` | Detail view (full metadata + plan.md) |
| `r` | Resume session (launches Copilot in correct dir) |
| `y` | Copy resume command to clipboard |
| `q` | Quit |

### CLI Mode

When you pass any filter flag, `copsearch` prints a table and exits (no TUI):

```bash
# Filter by project
copsearch -p Integration

# Filter by branch glob
copsearch -b 'yaj/*'

# Last 7 days only
copsearch --since 7d

# Full-text search
copsearch -q "RSS funeth"

# Combine filters
copsearch -p Integration -b master --since 3d

# Get resume command for a session (prefix match on ID)
copsearch --id 884bb
# → cd /Users/you/project && copilot -r 884bb6a6-...

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
│   ├── checkpoints/
│   │   └── index.md        # checkpoint history
│   └── files/              # session artifacts
└── ...
```

Each session's `workspace.yaml` contains metadata like:

```yaml
id: 884bb6a6-5491-470f-9af7-5e866ff38afc
cwd: /Users/you/project
repository: org/repo
branch: yaj/feature
summary: Fix the critical bug
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
│   ├── session.py       # Session data model and loader
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

## License

[MIT](LICENSE)
