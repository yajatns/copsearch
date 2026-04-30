"""Tests for the events.jsonl normalizer."""

from __future__ import annotations

import json
from pathlib import Path

from copsearch.normalize import (
    SCHEMA_VERSION,
    SessionMeta,
    from_dict,
    normalize,
    normalize_events,
    to_dict,
)


def _meta(**kwargs) -> SessionMeta:
    base = {"session_id": "test", "cwd": "/tmp", "summary": "test session"}
    base.update(kwargs)
    return SessionMeta(**base)


def _ev(t: str, data: dict | None = None, **kwargs) -> dict:
    """Compact event-builder for tests."""
    out = {"type": t, "data": data or {}, "timestamp": "2026-04-10T06:17:28.000Z"}
    out.update(kwargs)
    return out


# ── Basic structure ──────────────────────────────────────────────────────────


def test_empty_events():
    ns = normalize([], _meta())
    assert ns.turns == []
    assert ns.schema_version == SCHEMA_VERSION


def test_user_message_becomes_user_turn():
    ns = normalize([_ev("user.message", {"content": "hello world"})], _meta())
    assert len(ns.turns) == 1
    assert ns.turns[0].kind == "user"
    assert ns.turns[0].user_text == "hello world"


def test_user_message_drops_transformed_content():
    """We don't keep transformedContent — it's bloat for renderers."""
    ev = _ev(
        "user.message",
        {"content": "real prompt", "transformedContent": "<reminder>...</reminder>real prompt"},
    )
    ns = normalize([ev], _meta())
    serialized = json.dumps(to_dict(ns))
    assert "transformed" not in serialized.lower()


def test_assistant_turn_groups_messages_and_tools():
    events = [
        _ev("user.message", {"content": "hi"}),
        _ev("assistant.turn_start", {"turnId": "0", "interactionId": "i1"}),
        _ev(
            "assistant.message",
            {
                "content": "Sure, let me check.",
                "toolRequests": [
                    {
                        "toolCallId": "tc1",
                        "name": "bash",
                        "arguments": {"command": "ls"},
                        "intentionSummary": "Listing files",
                    }
                ],
            },
        ),
        _ev("tool.execution_start", {"toolCallId": "tc1", "toolName": "bash"}),
        _ev(
            "tool.execution_complete",
            {
                "toolCallId": "tc1",
                "success": True,
                "model": "claude-haiku",
                "result": {"content": "file1\nfile2"},
                "interactionId": "i1",
            },
        ),
        _ev("assistant.turn_end", {"turnId": "0"}),
    ]
    ns = normalize(events, _meta())
    assert len(ns.turns) == 2
    user, assistant = ns.turns
    assert user.kind == "user"
    assert assistant.kind == "assistant"
    assert assistant.assistant_text == "Sure, let me check."
    assert len(assistant.tool_calls) == 1
    tc = assistant.tool_calls[0]
    assert tc.name == "bash"
    assert tc.intent == "Listing files"
    assert tc.has_result is True
    assert tc.success is True
    assert tc.result_content == "file1\nfile2"
    assert tc.model == "claude-haiku"


def test_multiple_assistant_messages_concatenate():
    events = [
        _ev("assistant.turn_start", {"turnId": "0"}),
        _ev("assistant.message", {"content": "First chunk. "}),
        _ev("assistant.message", {"content": "Second chunk."}),
        _ev("assistant.turn_end", {"turnId": "0"}),
    ]
    ns = normalize(events, _meta())
    assert ns.turns[0].assistant_text == "First chunk. Second chunk."


# ── Tool call merging ────────────────────────────────────────────────────────


def test_tool_call_with_diff_in_detailed_content():
    events = [
        _ev("assistant.turn_start", {"turnId": "0", "interactionId": "i1"}),
        _ev(
            "assistant.message",
            {
                "toolRequests": [
                    {"toolCallId": "tc1", "name": "edit", "arguments": {"path": "f.py"}}
                ]
            },
        ),
        _ev(
            "tool.execution_complete",
            {
                "toolCallId": "tc1",
                "success": True,
                "result": {
                    "content": "File f.py updated.",
                    "detailedContent": "diff --git a/f.py b/f.py\n@@ -1 +1 @@\n-old\n+new",
                },
                "toolTelemetry": {
                    "metrics": {"linesAdded": 1, "linesRemoved": 1},
                    "restrictedProperties": {"filePaths": '["f.py"]'},
                },
            },
        ),
    ]
    ns = normalize(events, _meta())
    tc = ns.turns[0].tool_calls[0]
    assert "diff --git" in tc.result_detailed
    assert tc.lines_added == 1
    assert tc.lines_removed == 1
    assert tc.file_paths == ["f.py"]


def test_tool_call_truncation_flag():
    """When result_length >= response_token_limit, mark truncated."""
    events = [
        _ev("assistant.turn_start", {"turnId": "0"}),
        _ev(
            "assistant.message",
            {"toolRequests": [{"toolCallId": "tc1", "name": "view", "arguments": {}}]},
        ),
        _ev(
            "tool.execution_complete",
            {
                "toolCallId": "tc1",
                "success": True,
                "result": {"content": "..."},
                "toolTelemetry": {"metrics": {"resultLength": 42000, "responseTokenLimit": 42000}},
            },
        ),
    ]
    ns = normalize(events, _meta())
    assert ns.turns[0].tool_calls[0].truncated is True


def test_tool_call_without_result_is_marked_no_result():
    events = [
        _ev("assistant.turn_start", {"turnId": "0"}),
        _ev(
            "assistant.message",
            {"toolRequests": [{"toolCallId": "tc1", "name": "bash", "arguments": {}}]},
        ),
        _ev("tool.execution_start", {"toolCallId": "tc1", "toolName": "bash"}),
        # No tool.execution_complete — call was aborted mid-flight
    ]
    ns = normalize(events, _meta())
    tc = ns.turns[0].tool_calls[0]
    assert tc.has_result is False
    assert tc.success is None
    assert tc.result_content == ""


def test_duration_ms_computed_from_timestamps():
    events = [
        _ev("assistant.turn_start", {"turnId": "0"}),
        _ev(
            "assistant.message",
            {"toolRequests": [{"toolCallId": "tc1", "name": "bash", "arguments": {}}]},
        ),
        {
            "type": "tool.execution_start",
            "data": {"toolCallId": "tc1", "toolName": "bash"},
            "timestamp": "2026-04-10T06:00:00.000Z",
        },
        {
            "type": "tool.execution_complete",
            "data": {"toolCallId": "tc1", "success": True, "result": {"content": ""}},
            "timestamp": "2026-04-10T06:00:01.500Z",
        },
    ]
    ns = normalize(events, _meta())
    assert ns.turns[0].tool_calls[0].duration_ms == 1500


# ── Sub-agent depth ──────────────────────────────────────────────────────────


def test_sub_agent_depth_handles_cycle_without_recursion_error():
    """A cycle in parentToolCallId chains must not crash the normalizer."""
    # A → B → A: a malformed log we shouldn't trust but shouldn't crash on either.
    events = [
        _ev("assistant.turn_start", {"turnId": "0", "interactionId": "i1"}),
        _ev(
            "assistant.message",
            {
                "toolRequests": [
                    {"toolCallId": "A", "name": "task", "arguments": {}},
                    {"toolCallId": "B", "name": "bash", "arguments": {}},
                ]
            },
        ),
        _ev(
            "tool.execution_complete",
            {
                "toolCallId": "A", "success": True,
                "result": {"content": ""}, "parentToolCallId": "B",
            },
        ),
        _ev(
            "tool.execution_complete",
            {
                "toolCallId": "B", "success": True,
                "result": {"content": ""}, "parentToolCallId": "A",
            },
        ),
    ]
    ns = normalize(events, _meta())  # must not raise RecursionError
    calls = {tc.tool_call_id: tc for tc in ns.turns[0].tool_calls}
    # Both calls get *some* finite depth; we don't care which is the "root".
    assert calls["A"].depth >= 0
    assert calls["B"].depth >= 0
    assert calls["A"].depth <= 10 and calls["B"].depth <= 10


def test_sub_agent_depth_assigned():
    """Tool calls with parentToolCallId pointing at another call get depth>0."""
    events = [
        _ev("assistant.turn_start", {"turnId": "0", "interactionId": "i1"}),
        _ev(
            "assistant.message",
            {
                "toolRequests": [
                    {"toolCallId": "outer", "name": "task", "arguments": {}},
                    {"toolCallId": "inner", "name": "bash", "arguments": {}},
                ]
            },
        ),
        _ev(
            "tool.execution_complete",
            {
                "toolCallId": "outer",
                "success": True,
                "result": {"content": "done"},
            },
        ),
        _ev(
            "tool.execution_complete",
            {
                "toolCallId": "inner",
                "success": True,
                "result": {"content": "ls output"},
                "parentToolCallId": "outer",
            },
        ),
    ]
    ns = normalize(events, _meta())
    calls = {tc.tool_call_id: tc for tc in ns.turns[0].tool_calls}
    assert calls["outer"].depth == 0
    assert calls["inner"].depth == 1


# ── Aborts and skills ────────────────────────────────────────────────────────


def test_abort_marks_current_assistant_turn():
    events = [
        _ev("assistant.turn_start", {"turnId": "0"}),
        _ev("assistant.message", {"content": "thinking..."}),
        _ev("abort", {"reason": "user initiated"}),
    ]
    ns = normalize(events, _meta())
    assistant = ns.turns[0]
    assert assistant.aborted is True
    assert assistant.abort_reason == "user initiated"


def test_skill_invoked_becomes_system_turn():
    events = [
        _ev(
            "skill.invoked",
            {
                "name": "my-skill",
                "path": "/path/to/SKILL.md",
                "content": "skill body",
            },
        ),
    ]
    ns = normalize(events, _meta())
    assert len(ns.turns) == 1
    assert ns.turns[0].kind == "system"
    assert ns.turns[0].system_kind == "skill_invoked"
    assert ns.turns[0].system_data["name"] == "my-skill"


def test_session_shutdown_enriches_meta_and_emits_system_turn():
    events = [
        _ev(
            "session.shutdown",
            {
                "shutdownType": "routine",
                "totalPremiumRequests": 24,
                "totalApiDurationMs": 306141,
                "currentModel": "claude-opus-4.6",
                "currentTokens": 67441,
                "codeChanges": {"linesAdded": 5, "linesRemoved": 2, "filesModified": ["a.py"]},
                "modelMetrics": {"claude-opus-4.6": {"requests": {"count": 30}}},
            },
        ),
    ]
    meta = _meta()
    ns = normalize(events, meta)
    assert meta.total_premium_requests == 24
    assert meta.code_changes["filesModified"] == ["a.py"]
    assert meta.model_metrics["claude-opus-4.6"]["requests"]["count"] == 30
    assert ns.turns[0].kind == "system"
    assert ns.turns[0].system_kind == "session_shutdown"


def test_session_start_captures_copilot_version():
    events = [_ev("session.start", {"copilotVersion": "1.0.22", "sessionId": "abc"})]
    meta = _meta()
    ns = normalize(events, meta)
    assert meta.copilot_version == "1.0.22"
    assert ns.turns[0].system_kind == "session_start"


def test_hook_events_are_dropped():
    """hook.start/hook.end are plumbing — don't surface as turns."""
    events = [
        _ev("hook.start", {"hookType": "userPromptSubmitted"}),
        _ev("user.message", {"content": "hi"}),
        _ev("hook.end", {"hookType": "userPromptSubmitted"}),
    ]
    ns = normalize(events, _meta())
    assert len(ns.turns) == 1
    assert ns.turns[0].kind == "user"


# ── File I/O ─────────────────────────────────────────────────────────────────


def test_normalize_events_from_disk(tmp_path: Path):
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(
        json.dumps({"type": "user.message", "data": {"content": "hi"}, "timestamp": "t"})
        + "\n"
        + "this is malformed\n"
        + json.dumps(
            {"type": "assistant.turn_start", "data": {"turnId": "0"}, "timestamp": "t"}
        )
        + "\n"
    )
    meta = _meta()
    ns = normalize_events(events_path, meta)
    assert len(ns.turns) == 2
    assert ns.turns[0].user_text == "hi"
    assert ns.turns[1].kind == "assistant"


# ── Round-trip serialization ─────────────────────────────────────────────────


def test_to_dict_from_dict_roundtrip():
    events = [
        _ev("user.message", {"content": "hello"}),
        _ev("assistant.turn_start", {"turnId": "0"}),
        _ev(
            "assistant.message",
            {
                "content": "Sure",
                "toolRequests": [
                    {
                        "toolCallId": "tc1",
                        "name": "bash",
                        "arguments": {"command": "ls"},
                        "intentionSummary": "list",
                    }
                ],
            },
        ),
        _ev(
            "tool.execution_complete",
            {
                "toolCallId": "tc1",
                "success": True,
                "result": {"content": "files"},
            },
        ),
    ]
    ns = normalize(events, _meta(session_id="rt"))
    d = to_dict(ns)
    # Make sure the dict is plain JSON-serializable.
    blob = json.dumps(d)
    rebuilt = from_dict(json.loads(blob))
    assert rebuilt.schema_version == ns.schema_version
    assert rebuilt.meta.session_id == "rt"
    assert len(rebuilt.turns) == 2
    assert rebuilt.turns[1].tool_calls[0].name == "bash"
    assert rebuilt.turns[1].tool_calls[0].intent == "list"


def test_from_dict_tolerates_unknown_fields():
    """Forward-compatibility: an older copsearch reading a newer cache shouldn't crash."""
    blob = {
        "schema_version": 999,
        "meta": {"session_id": "x", "cwd": "/tmp", "future_field": "ignored"},
        "turns": [
            {
                "kind": "user",
                "user_text": "hi",
                "future_turn_field": "also ignored",
                "tool_calls": [],
            }
        ],
    }
    ns = from_dict(blob)
    assert ns.meta.session_id == "x"
    assert ns.turns[0].user_text == "hi"


def test_assistant_turn_with_synthesized_request_for_late_tool_call():
    """Tool result without a matching toolRequests entry is still attached."""
    events = [
        _ev("assistant.turn_start", {"turnId": "0", "interactionId": "i1"}),
        _ev("assistant.message", {"content": "thinking", "toolRequests": []}),
        _ev(
            "tool.execution_complete",
            {
                "toolCallId": "orphan",
                "success": True,
                "result": {"content": "data"},
                "interactionId": "i1",
            },
        ),
    ]
    ns = normalize(events, _meta())
    assistant = next(t for t in ns.turns if t.kind == "assistant")
    assert len(assistant.tool_calls) == 1
    assert assistant.tool_calls[0].tool_call_id == "orphan"
    assert assistant.tool_calls[0].has_result is True
