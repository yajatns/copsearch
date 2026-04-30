"""Render a NormalizedSession to ANSI-colored text for the terminal.

Two output modes:

- ``RenderOptions(color=True)`` — full ANSI coloring (default when stdout is a TTY).
- ``RenderOptions(color=False)`` — plain text (default when piping or redirecting,
  or when ``NO_COLOR`` is in the environment).

Tool-call detail is configurable via :class:`RenderOptions.tools`:

- ``"none"`` — chat only, no tool calls
- ``"brief"`` — one line per tool (the default)
- ``"full"`` — args + result for every tool call
"""

from __future__ import annotations

import os
import shutil
import sys
import textwrap
from collections.abc import Iterator
from dataclasses import dataclass

from copsearch.normalize import NormalizedSession, ToolCall, Turn

# ── ANSI ─────────────────────────────────────────────────────────────────────


class A:
    """ANSI escape codes. Empty strings when colors are off."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"

    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"


def _strip_ansi() -> dict[str, str]:
    return {k: "" for k in vars(A) if not k.startswith("_") and k.isupper()}


# ── Options ──────────────────────────────────────────────────────────────────


@dataclass
class RenderOptions:
    """Knobs for the CLI renderer."""

    color: bool = True
    tools: str = "brief"  # "none" | "brief" | "full"
    max_output_lines: int = 0  # 0 = unlimited (for tool result content)
    width: int = 0  # 0 = autodetect
    show_system_events: bool = True
    only_turn: int | None = None  # 1-based; None = all
    grep: str = ""  # case-insensitive substring filter on user/assistant text


def detect_color_support(stream=sys.stdout) -> bool:
    """Return True iff we should emit ANSI colors."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return bool(getattr(stream, "isatty", lambda: False)())


def detect_width(default: int = 100) -> int:
    try:
        return shutil.get_terminal_size((default, 24)).columns
    except OSError:
        return default


# ── Public API ───────────────────────────────────────────────────────────────


def render_session(ns: NormalizedSession, opts: RenderOptions | None = None) -> str:
    """Return the full session as one string, ready to print to a terminal."""
    return "\n".join(iter_lines(ns, opts))


def iter_lines(ns: NormalizedSession, opts: RenderOptions | None = None) -> Iterator[str]:
    """Yield rendered lines one at a time. Useful for piping into ``$PAGER``."""
    opts = opts or RenderOptions()
    ansi = vars(A) if opts.color else _strip_ansi()
    width = opts.width or detect_width()

    yield from _header(ns, ansi, width)
    yield ""

    user_turn_count = 0
    for turn in ns.turns:
        if turn.kind == "user":
            user_turn_count += 1
        if opts.only_turn is not None and user_turn_count != opts.only_turn:
            continue
        if opts.grep and not _turn_matches_grep(turn, opts.grep):
            continue

        if turn.kind == "user":
            yield from _render_user(turn, ansi, width)
        elif turn.kind == "assistant":
            yield from _render_assistant(turn, ansi, width, opts)
        elif turn.kind == "system":
            if opts.show_system_events:
                yield from _render_system(turn, ansi, width)

        yield ""

    yield from _footer(ns, ansi, width)


# ── Sections ─────────────────────────────────────────────────────────────────


def _header(ns: NormalizedSession, ansi: dict, width: int) -> Iterator[str]:
    m = ns.meta
    yield f"{ansi['BOLD']}{ansi['CYAN']}{'═' * width}{ansi['RESET']}"
    title = m.summary or m.session_id or "(no summary)"
    yield f"{ansi['BOLD']}  {title[: width - 4]}{ansi['RESET']}"
    yield f"{ansi['BOLD']}{ansi['CYAN']}{'═' * width}{ansi['RESET']}"
    rows = []
    if m.session_id:
        rows.append(("Session", m.session_id))
    if m.cwd:
        rows.append(("Directory", m.cwd))
    if m.repository:
        rows.append(("Repository", m.repository))
    if m.branch:
        rows.append(("Branch", m.branch))
    if m.created_at or m.updated_at:
        rows.append(("Created", m.created_at or "—"))
        rows.append(("Updated", m.updated_at or "—"))
    if m.is_active:
        rows.append(("Status", f"{ansi['GREEN']}● ACTIVE{ansi['RESET']}"))
    if m.copilot_version:
        rows.append(("Copilot", m.copilot_version))
    if m.current_model:
        rows.append(("Model", m.current_model))
    for label, val in rows:
        yield f"  {ansi['DIM']}{label + ':':<12}{ansi['RESET']} {val}"
    if m.has_plan and m.plan_text:
        yield ""
        yield f"  {ansi['MAGENTA']}{ansi['BOLD']}┐ Plan{ansi['RESET']}"
        for line in m.plan_text.splitlines()[:30]:
            yield f"  {ansi['MAGENTA']}│{ansi['RESET']} {line}"


def _footer(ns: NormalizedSession, ansi: dict, width: int) -> Iterator[str]:
    m = ns.meta
    if not (m.total_premium_requests or m.code_changes or m.model_metrics):
        return
    yield f"{ansi['DIM']}{'─' * width}{ansi['RESET']}"
    yield f"{ansi['BOLD']}  Session totals{ansi['RESET']}"
    if m.total_premium_requests is not None:
        yield f"  {ansi['DIM']}Premium requests:{ansi['RESET']} {m.total_premium_requests}"
    if m.total_api_duration_ms is not None:
        yield (
            f"  {ansi['DIM']}API duration:    {ansi['RESET']}"
            f" {m.total_api_duration_ms / 1000:.1f}s"
        )
    cc = m.code_changes or {}
    if cc:
        added = cc.get("linesAdded", 0)
        removed = cc.get("linesRemoved", 0)
        files = cc.get("filesModified") or []
        yield (
            f"  {ansi['DIM']}Code changes:    {ansi['RESET']}"
            f" {ansi['GREEN']}+{added}{ansi['RESET']} "
            f"{ansi['RED']}-{removed}{ansi['RESET']} "
            f"{ansi['DIM']}({len(files)} file{'s' if len(files) != 1 else ''}){ansi['RESET']}"
        )
        for fp in files[:20]:
            yield f"      {ansi['DIM']}{fp}{ansi['RESET']}"
    for model, m_data in (m.model_metrics or {}).items():
        usage = (m_data or {}).get("usage") or {}
        if usage:
            yield (
                f"  {ansi['DIM']}{model}:{ansi['RESET']} "
                f"in={usage.get('inputTokens', 0):,} "
                f"out={usage.get('outputTokens', 0):,} "
                f"cache_read={usage.get('cacheReadTokens', 0):,}"
            )


def _render_user(turn: Turn, ansi: dict, width: int) -> Iterator[str]:
    ts = _short_ts(turn.timestamp)
    yield (
        f"{ansi['BOLD']}{ansi['BLUE']}▌ You{ansi['RESET']}  "
        f"{ansi['DIM']}{ts}{ansi['RESET']}"
    )
    for line in _wrap(turn.user_text, width - 2):
        yield f"  {line}"


def _render_assistant(
    turn: Turn, ansi: dict, width: int, opts: RenderOptions
) -> Iterator[str]:
    label = "▌ Assistant"
    if turn.aborted:
        label += (
            f" {ansi['YELLOW']}[aborted: {turn.abort_reason or 'unknown'}]"
            f"{ansi['RESET']}"
        )
    ts = _short_ts(turn.timestamp)
    yield (
        f"{ansi['BOLD']}{ansi['MAGENTA']}{label}{ansi['RESET']}  "
        f"{ansi['DIM']}{ts}{ansi['RESET']}"
    )
    if turn.assistant_text:
        for line in _wrap(turn.assistant_text, width - 2):
            yield f"  {line}"
    if opts.tools == "none":
        return
    for tc in turn.tool_calls:
        yield from _render_tool_call(tc, ansi, width, opts)


def _render_system(turn: Turn, ansi: dict, width: int) -> Iterator[str]:
    label_map = {
        "session_start": ("○ Session start", "GREEN"),
        "session_shutdown": ("○ Session end", "GRAY"),
        "skill_invoked": ("◆ Skill", "YELLOW"),
    }
    label, color_name = label_map.get(turn.system_kind, ("○", "GRAY"))
    color = ansi.get(color_name, "")
    ts = _short_ts(turn.timestamp)
    yield (
        f"{ansi['DIM']}{color}{label}{ansi['RESET']}  "
        f"{ansi['DIM']}{ts}{ansi['RESET']}"
    )
    if turn.system_kind == "skill_invoked":
        yield f"  {ansi['DIM']}name:{ansi['RESET']} {turn.system_data.get('name', '')}"
        path = turn.system_data.get("path", "")
        if path:
            yield f"  {ansi['DIM']}path:{ansi['RESET']} {path}"
    elif turn.system_kind == "session_shutdown":
        cc = turn.system_data.get("codeChanges") or {}
        if cc:
            yield (
                f"  {ansi['DIM']}files modified:{ansi['RESET']} "
                f"{len(cc.get('filesModified') or [])}"
            )


def _render_tool_call(tc: ToolCall, ansi: dict, width: int, opts: RenderOptions) -> Iterator[str]:
    indent = "  " + "│  " * tc.depth
    status_glyph, status_color_name = _tool_status(tc, ansi)
    status_color = ansi.get(status_color_name, "")
    name_str = tc.name
    if tc.mcp_server:
        name_str = f"{tc.mcp_server}::{tc.name}"
    intent = tc.intent or _summarize_args(tc.arguments)
    head = (
        f"{indent}{status_color}{status_glyph}{ansi['RESET']} "
        f"{ansi['CYAN']}{name_str}{ansi['RESET']}"
    )
    if intent:
        intent_max = max(20, width - len(_strip_codes(head)) - 4)
        head += f"  {ansi['DIM']}{_truncate(intent, intent_max)}{ansi['RESET']}"
    if tc.duration_ms is not None and tc.duration_ms >= 100:
        head += f"  {ansi['DIM']}({tc.duration_ms} ms){ansi['RESET']}"
    if tc.truncated:
        head += f"  {ansi['YELLOW']}[truncated]{ansi['RESET']}"
    yield head

    if opts.tools == "brief":
        return

    # Full mode: dump args + result.
    if tc.arguments:
        for line in _format_args(tc.arguments, indent + "  ", ansi, width):
            yield line
    if tc.has_result:
        body = _pick_result_body(tc)
        if body:
            yield f"{indent}  {ansi['DIM']}── result ──{ansi['RESET']}"
            for line in _render_result_body(body, tc, indent + "  ", ansi, opts):
                yield line
    elif not tc.aborted:
        yield f"{indent}  {ansi['DIM']}(no result captured){ansi['RESET']}"


def _render_result_body(
    body: str, tc: ToolCall, indent: str, ansi: dict, opts: RenderOptions
) -> Iterator[str]:
    lines = body.splitlines()
    is_diff = body.lstrip().startswith("diff --git") or any(
        line.startswith(("@@ ", "+++ ", "--- ")) for line in lines[:10]
    )
    cap = opts.max_output_lines if opts.max_output_lines > 0 else len(lines)
    shown = lines[:cap]
    for line in shown:
        if is_diff:
            yield f"{indent}{_color_diff_line(line, ansi)}"
        else:
            yield f"{indent}{ansi['DIM']}{line}{ansi['RESET']}"
    if len(lines) > cap:
        yield f"{indent}{ansi['DIM']}… ({len(lines) - cap} more lines){ansi['RESET']}"


def _color_diff_line(line: str, ansi: dict) -> str:
    if line.startswith("+++") or line.startswith("---"):
        return f"{ansi['BOLD']}{line}{ansi['RESET']}"
    if line.startswith("+"):
        return f"{ansi['GREEN']}{line}{ansi['RESET']}"
    if line.startswith("-"):
        return f"{ansi['RED']}{line}{ansi['RESET']}"
    if line.startswith("@@"):
        return f"{ansi['CYAN']}{line}{ansi['RESET']}"
    return f"{ansi['DIM']}{line}{ansi['RESET']}"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _pick_result_body(tc: ToolCall) -> str:
    """Choose between ``result_content`` and ``result_detailed`` for display.

    For mutation tools (``edit``, ``create``, etc.) Copilot puts a one-line
    summary in ``content`` and the actual unified diff in ``detailedContent``.
    For read tools (``view``, ``bash``, …) ``content`` is the real output
    and ``detailedContent`` is either empty or a synthetic file-vs-/dev/null
    diff that's strictly less useful.

    Heuristic: prefer ``detailedContent`` only when ``content`` is a short
    summary AND ``detailedContent`` looks like a real diff.
    """
    content = tc.result_content or ""
    detailed = tc.result_detailed or ""
    if not detailed:
        return content
    if not content:
        return detailed
    is_diff = "diff --git" in detailed[:200] or detailed.lstrip().startswith(("@@ ", "+++ "))
    if is_diff and _is_mutation_summary(content):
        return detailed
    return content


_MUTATION_PREFIXES = (
    "File ",
    "Created file ",
    "Created ",
    "Wrote ",
    "Modified ",
    "Updated ",
    "Edited ",
    "Replaced ",
)


def _is_mutation_summary(content: str) -> bool:
    """Detect Copilot's one-line summary for tools that wrote/edited a file."""
    s = content.strip()
    if not s or "\n" in s:
        return False
    return s.startswith(_MUTATION_PREFIXES)


def _tool_status(tc: ToolCall, ansi: dict) -> tuple[str, str]:
    """Return (glyph, color_name) for a tool call."""
    if not tc.has_result:
        return ("⏳", "YELLOW")
    if tc.success:
        return ("✓", "GREEN")
    return ("✗", "RED")


def _summarize_args(args: dict) -> str:
    """One-line summary of arguments, used when intentionSummary is empty."""
    if not args:
        return ""
    # Pick the most useful single field.
    for key in ("command", "path", "query", "url", "intent", "description"):
        v = args.get(key)
        if isinstance(v, str) and v:
            return v
    # Otherwise: join short values.
    parts = []
    for k, v in args.items():
        if isinstance(v, str) and len(v) < 60:
            parts.append(f"{k}={v}")
        elif isinstance(v, (int, float, bool)):
            parts.append(f"{k}={v}")
        if len(parts) >= 3:
            break
    return ", ".join(parts)


def _format_args(args: dict, indent: str, ansi: dict, width: int) -> Iterator[str]:
    """Render arguments as ``key: value`` lines."""
    for k, v in args.items():
        if isinstance(v, str):
            if "\n" in v or len(v) > width - len(indent) - len(k) - 3:
                yield f"{indent}{ansi['DIM']}{k}:{ansi['RESET']}"
                for line in v.splitlines():
                    for w in _wrap(line, width - len(indent) - 2):
                        yield f"{indent}  {w}"
            else:
                yield f"{indent}{ansi['DIM']}{k}:{ansi['RESET']} {v}"
        else:
            yield f"{indent}{ansi['DIM']}{k}:{ansi['RESET']} {v}"


def _wrap(text: str, width: int) -> list[str]:
    """Word-wrap text. Preserves explicit newlines."""
    if width <= 0:
        return text.splitlines() or [""]
    out = []
    for line in text.splitlines() or [""]:
        if not line:
            out.append("")
            continue
        wrapped = textwrap.wrap(
            line, width=width, break_long_words=False, replace_whitespace=False
        )
        out.extend(wrapped or [""])
    return out


def _short_ts(ts: str) -> str:
    """Shorten an ISO timestamp to ``HH:MM:SS`` for display."""
    if not ts:
        return ""
    t = ts
    # ISO format: 2026-04-10T06:17:28.000Z → take HH:MM:SS slice.
    if "T" in t:
        time_part = t.split("T", 1)[1]
        return time_part.split(".")[0].rstrip("Z")
    return t


def _truncate(text: str, width: int) -> str:
    text = text.replace("\n", " ")
    if len(text) <= width:
        return text
    return text[: max(1, width - 1)] + "…"


def _strip_codes(s: str) -> str:
    """Strip ANSI codes for length calculation."""
    out = []
    i = 0
    while i < len(s):
        if s[i] == "\033":
            j = s.find("m", i)
            if j == -1:
                break
            i = j + 1
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _turn_matches_grep(turn: Turn, needle: str) -> bool:
    n = needle.lower()
    if turn.kind == "user" and n in turn.user_text.lower():
        return True
    if turn.kind == "assistant":
        if n in turn.assistant_text.lower():
            return True
        for tc in turn.tool_calls:
            if n in tc.intent.lower() or n in tc.name.lower():
                return True
            if n in tc.result_content.lower() or n in tc.result_detailed.lower():
                return True
    if turn.kind == "system":
        if any(n in str(v).lower() for v in turn.system_data.values()):
            return True
    return False
