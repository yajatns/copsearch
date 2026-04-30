"""Tests for the CLI renderer."""

from __future__ import annotations

from copsearch.normalize import (
    NormalizedSession,
    SessionMeta,
    ToolCall,
    Turn,
)
from copsearch.render_cli import (
    RenderOptions,
    _is_mutation_summary,
    _pick_result_body,
    _strip_codes,
    render_session,
)


def _ns(*turns: Turn, **meta_kwargs) -> NormalizedSession:
    base = {"session_id": "test", "summary": "Test session"}
    base.update(meta_kwargs)
    return NormalizedSession(meta=SessionMeta(**base), turns=list(turns))


# ── Body picking heuristic ───────────────────────────────────────────────────


def test_pick_body_prefers_content_for_view():
    tc = ToolCall(
        tool_call_id="t",
        name="view",
        arguments={},
        has_result=True,
        result_content="1. # Hello\n2. World",
        result_detailed="diff --git a/x b/x\n+++ b/x\n+# Hello",
    )
    # Content is real file output (not a mutation summary) — keep it.
    assert _pick_result_body(tc) == "1. # Hello\n2. World"


def test_pick_body_prefers_detailed_for_edit_summary():
    tc = ToolCall(
        tool_call_id="t",
        name="edit",
        arguments={},
        has_result=True,
        result_content="File README.md updated with changes.",
        result_detailed="diff --git a/README.md b/README.md\n@@ -1 +1 @@\n-old\n+new",
    )
    assert "diff --git" in _pick_result_body(tc)


def test_pick_body_falls_back_when_one_missing():
    tc = ToolCall(
        tool_call_id="t", name="x", arguments={}, has_result=True,
        result_content="", result_detailed="diff --git ...",
    )
    assert "diff" in _pick_result_body(tc)
    tc.result_detailed = ""
    tc.result_content = "stdout"
    assert _pick_result_body(tc) == "stdout"


def test_is_mutation_summary_detects_known_prefixes():
    assert _is_mutation_summary("File foo.py updated.")
    assert _is_mutation_summary("Created file x.py with 5 chars")
    assert _is_mutation_summary("Wrote bar.txt")
    assert not _is_mutation_summary("1. # Hello")
    assert not _is_mutation_summary("file foo.py updated")  # case-sensitive
    # Multi-line content is the file itself, not a summary.
    assert not _is_mutation_summary("File 1\nFile 2")


# ── Header / sidebar / footer ────────────────────────────────────────────────


def test_render_includes_session_id_and_summary():
    out = render_session(
        _ns(session_id="abc-123", summary="My session"),
        RenderOptions(color=False, width=80),
    )
    assert "My session" in out
    assert "abc-123" in out


def test_render_active_status_visible():
    out = render_session(_ns(is_active=True), RenderOptions(color=False, width=80))
    assert "ACTIVE" in out


def test_render_footer_shows_session_totals():
    ns = _ns()
    ns.meta.total_premium_requests = 24
    ns.meta.total_api_duration_ms = 30_000
    ns.meta.code_changes = {"linesAdded": 5, "linesRemoved": 2, "filesModified": ["a.py"]}
    out = render_session(ns, RenderOptions(color=False, width=100))
    assert "Premium requests" in out and "24" in out
    assert "API duration" in out and "30.0s" in out
    assert "+5" in out and "-2" in out
    assert "a.py" in out


# ── Turns ────────────────────────────────────────────────────────────────────


def test_user_turn_renders_text():
    out = render_session(
        _ns(Turn(kind="user", user_text="hello world", timestamp="2026-04-10T06:17:28.000Z")),
        RenderOptions(color=False, width=80),
    )
    assert "You" in out
    assert "hello world" in out
    assert "06:17:28" in out  # short timestamp format


def test_assistant_turn_with_tool_call_brief_mode():
    tc = ToolCall(
        tool_call_id="x", name="bash", arguments={"command": "ls"},
        has_result=True, success=True, result_content="file1\nfile2",
    )
    out = render_session(
        _ns(Turn(kind="assistant", tool_calls=[tc], assistant_text="checking files")),
        RenderOptions(color=False, tools="brief", width=100),
    )
    assert "checking files" in out
    assert "bash" in out
    assert "ls" in out  # appears in the chip header (intent fallback to args)
    # In brief mode we should NOT see the result body.
    assert "file1" not in out


def test_assistant_turn_with_tool_call_full_mode():
    tc = ToolCall(
        tool_call_id="x", name="bash", arguments={"command": "ls"},
        has_result=True, success=True, result_content="file1\nfile2",
    )
    out = render_session(
        _ns(Turn(kind="assistant", tool_calls=[tc])),
        RenderOptions(color=False, tools="full", width=100),
    )
    assert "file1" in out and "file2" in out


def test_assistant_turn_with_tools_none_hides_calls():
    tc = ToolCall(tool_call_id="x", name="bash", arguments={"command": "ls"})
    out = render_session(
        _ns(Turn(kind="assistant", tool_calls=[tc], assistant_text="thinking")),
        RenderOptions(color=False, tools="none", width=80),
    )
    assert "thinking" in out
    assert "bash" not in out


def test_aborted_turn_marker():
    out = render_session(
        _ns(Turn(kind="assistant", aborted=True, abort_reason="user initiated")),
        RenderOptions(color=False, width=80),
    )
    assert "aborted" in out
    assert "user initiated" in out


def test_truncated_tool_call_pill():
    tc = ToolCall(
        tool_call_id="x", name="view", arguments={},
        has_result=True, success=True, truncated=True,
    )
    out = render_session(
        _ns(Turn(kind="assistant", tool_calls=[tc])),
        RenderOptions(color=False, width=100),
    )
    assert "[truncated]" in out


def test_failed_tool_glyph():
    tc = ToolCall(tool_call_id="x", name="bash", arguments={"command": "false"},
                  has_result=True, success=False)
    out = render_session(
        _ns(Turn(kind="assistant", tool_calls=[tc])),
        RenderOptions(color=False, width=80),
    )
    assert "✗" in out


def test_no_result_tool_glyph():
    tc = ToolCall(tool_call_id="x", name="bash", arguments={"command": "x"}, has_result=False)
    out = render_session(
        _ns(Turn(kind="assistant", tool_calls=[tc])),
        RenderOptions(color=False, width=80),
    )
    assert "⏳" in out


# ── Filtering ────────────────────────────────────────────────────────────────


def test_only_turn_filters_to_one_user_turn():
    out = render_session(
        _ns(
            Turn(kind="user", user_text="first prompt"),
            Turn(kind="assistant", assistant_text="first reply"),
            Turn(kind="user", user_text="second prompt"),
            Turn(kind="assistant", assistant_text="second reply"),
        ),
        RenderOptions(color=False, only_turn=2, width=80),
    )
    assert "second prompt" in out
    assert "second reply" in out
    assert "first prompt" not in out
    assert "first reply" not in out


def test_grep_filters_turns():
    out = render_session(
        _ns(
            Turn(kind="user", user_text="something about cats"),
            Turn(kind="assistant", assistant_text="reply about dogs"),
            Turn(kind="user", user_text="more cats"),
        ),
        RenderOptions(color=False, grep="cats", width=80),
    )
    assert "cats" in out
    assert "dogs" not in out


def test_no_system_hides_skill_invocations():
    out = render_session(
        _ns(
            Turn(kind="system", system_kind="skill_invoked", system_data={"name": "my-skill"}),
            Turn(kind="user", user_text="hi"),
        ),
        RenderOptions(color=False, show_system_events=False, width=80),
    )
    assert "my-skill" not in out


# ── Color / plain mode ───────────────────────────────────────────────────────


def test_plain_mode_emits_no_ansi():
    out = render_session(
        _ns(Turn(kind="user", user_text="hi"), Turn(kind="assistant", assistant_text="hello")),
        RenderOptions(color=False, width=80),
    )
    assert "\033[" not in out


def test_color_mode_emits_ansi():
    out = render_session(
        _ns(Turn(kind="user", user_text="hi")),
        RenderOptions(color=True, width=80),
    )
    assert "\033[" in out
    # When stripped, the visible text should still contain "hi".
    assert "hi" in _strip_codes(out)


# ── Sub-agent depth ──────────────────────────────────────────────────────────


def test_subagent_depth_indents_inner_call():
    outer = ToolCall(tool_call_id="o", name="task", arguments={}, depth=0,
                     has_result=True, success=True)
    inner = ToolCall(tool_call_id="i", name="bash", arguments={"command": "ls"}, depth=1,
                     parent_tool_call_id="o", has_result=True, success=True)
    out = render_session(
        _ns(Turn(kind="assistant", tool_calls=[outer, inner])),
        RenderOptions(color=False, width=100),
    )
    # The inner call should carry the depth-indent guide character │.
    lines = out.splitlines()
    outer_line = next(line for line in lines if "task" in line)
    inner_line = next(line for line in lines if "bash" in line)
    assert "│" not in outer_line
    assert "│" in inner_line
