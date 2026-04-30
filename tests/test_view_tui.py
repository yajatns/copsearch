"""Tests for the curses viewer's line classifier and state machine.

We don't drive the full curses loop in tests — that requires a TTY and
makes assertions noisy. Instead we exercise the parts that don't touch
curses: the line classifier and the ``_State`` rendering-state machine.
"""

from __future__ import annotations

from copsearch.normalize import NormalizedSession, SessionMeta, ToolCall, Turn
from copsearch.render_cli import RenderOptions
from copsearch.view_tui import (
    PAIR_ASSISTANT,
    PAIR_DEFAULT,
    PAIR_DIFF_ADD,
    PAIR_DIFF_DEL,
    PAIR_DIFF_HUNK,
    PAIR_DIVIDER,
    PAIR_TOOL_ERR,
    PAIR_TOOL_OK,
    PAIR_TOOL_WAIT,
    PAIR_USER,
    _classify_line,
    _State,
)

# ── Classifier ───────────────────────────────────────────────────────────────


def test_classify_user_header():
    assert _classify_line("▌ You  10:24:11") == PAIR_USER


def test_classify_assistant_header():
    assert _classify_line("▌ Assistant  10:24:11") == PAIR_ASSISTANT


def test_classify_tool_ok_at_indent():
    assert _classify_line("  ✓ bash  list files  (123 ms)") == PAIR_TOOL_OK


def test_classify_tool_err():
    assert _classify_line("  ✗ bash  failed cmd  (45 ms)") == PAIR_TOOL_ERR


def test_classify_tool_wait():
    assert _classify_line("  ⏳ bash  no result captured") == PAIR_TOOL_WAIT


def test_classify_tool_subagent_indent():
    """A nested tool call has │ guides before the glyph — still classifies."""
    assert _classify_line("  │  ✓ bash  inner call") == PAIR_TOOL_OK


def test_classify_divider():
    assert _classify_line("════════════════════════") == PAIR_DIVIDER


def test_classify_diff_add():
    assert _classify_line("    +new line") == PAIR_DIFF_ADD


def test_classify_diff_del():
    assert _classify_line("    -old line") == PAIR_DIFF_DEL


def test_classify_diff_hunk():
    assert _classify_line("    @@ -1,5 +1,7 @@") == PAIR_DIFF_HUNK


def test_classify_blank_line():
    assert _classify_line("") == PAIR_DEFAULT


def test_classify_plain_text_falls_through():
    """User prompt body text gets the default pair (no special class)."""
    assert _classify_line("  This is plain prompt text from the user.") == PAIR_DEFAULT


# ── State ────────────────────────────────────────────────────────────────────


def _ns_with_turns() -> NormalizedSession:
    meta = SessionMeta(session_id="x", summary="Test")
    turns = [
        Turn(kind="user", user_text="first prompt"),
        Turn(
            kind="assistant",
            assistant_text="reply",
            tool_calls=[
                ToolCall(
                    tool_call_id="t1", name="bash", arguments={"command": "ls"},
                    has_result=True, success=True, result_content="file1",
                ),
            ],
        ),
        Turn(kind="user", user_text="second prompt"),
        Turn(kind="assistant", assistant_text="reply two"),
    ]
    return NormalizedSession(meta=meta, turns=turns)


def test_state_refresh_populates_lines_and_pairs():
    s = _State(ns=_ns_with_turns(), opts=RenderOptions(width=80))
    s.refresh_lines()
    assert len(s.lines) > 0
    assert len(s.pairs) == len(s.lines)


def test_state_turn_starts_finds_user_and_assistant_headers():
    s = _State(ns=_ns_with_turns(), opts=RenderOptions(width=80))
    s.refresh_lines()
    starts = s.turn_starts()
    # Two user + two assistant turns → four header lines.
    assert len(starts) == 4
    # Indices must be strictly increasing.
    assert starts == sorted(starts)


def test_state_tools_mode_switch_changes_output():
    s = _State(ns=_ns_with_turns(), opts=RenderOptions(width=80))
    s.refresh_lines()
    brief_lines = list(s.lines)
    s.tools_mode = "full"
    s.refresh_lines()
    full_lines = list(s.lines)
    s.tools_mode = "none"
    s.refresh_lines()
    none_lines = list(s.lines)

    # Tool result content ("file1") should appear only in "full" mode.
    assert any("file1" in line for line in full_lines)
    assert not any("file1" in line for line in brief_lines)
    # The tool name "bash" should disappear when tools are hidden.
    assert any("bash" in line for line in brief_lines)
    assert not any("bash" in line for line in none_lines)
