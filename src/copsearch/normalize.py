"""Normalize a Copilot CLI events.jsonl into a canonical conversation.

The raw events.jsonl is a flat append-only log of every micro-event the agent
emits: hook starts/ends, individual assistant message chunks, tool execution
start/complete pairs, etc. Renderers don't want to think about any of that.

This module collapses the log into a list of :class:`Turn` objects:

- ``user`` turns carry the user prompt.
- ``assistant`` turns carry the assistant's prose and the tool calls issued
  during that turn (each tool call has its request *and* result merged).
- ``system`` turns carry session boundaries and skill invocations — things
  worth showing in the timeline but that aren't part of the conversation.

The output is JSON-serializable (see :func:`to_dict`) so it can be cached
and consumed by both the CLI and HTML renderers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

# Event types we read but never surface to renderers as their own turn.
_PLUMBING_EVENTS = {"hook.start", "hook.end"}


@dataclass
class ToolCall:
    """One tool invocation: request + result, merged."""

    tool_call_id: str
    name: str
    arguments: dict[str, Any]

    # Request-side hints
    intent: str = ""  # from assistant.message.toolRequests[].intentionSummary
    mcp_server: str = ""  # from .mcpServerName — empty for built-in tools
    tool_title: str = ""

    # Result-side
    has_result: bool = False
    success: bool | None = None
    result_content: str = ""
    result_detailed: str = ""  # often a unified diff for edit/create
    model: str = ""  # which model issued this call

    # Telemetry / display hints
    lines_added: int | None = None
    lines_removed: int | None = None
    file_paths: list[str] = field(default_factory=list)
    response_token_limit: int | None = None
    result_length: int | None = None
    truncated: bool = False

    # Nesting (sub-agents call tools "through" their parent task)
    parent_tool_call_id: str = ""
    depth: int = 0  # filled in after the full pass

    # Timing
    started_at: str = ""
    completed_at: str = ""
    duration_ms: int | None = None


@dataclass
class Turn:
    """One logical step in the conversation.

    ``kind`` is one of ``user``, ``assistant``, ``system``.
    """

    kind: str
    timestamp: str = ""

    # User turn
    user_text: str = ""

    # Assistant turn
    turn_id: str = ""
    interaction_id: str = ""
    assistant_text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    aborted: bool = False
    abort_reason: str = ""

    # System turn
    system_kind: str = ""  # "session_start" | "session_shutdown" | "skill_invoked"
    system_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionMeta:
    """Session-level metadata gathered from workspace.yaml + session.shutdown."""

    session_id: str = ""
    cwd: str = ""
    branch: str = ""
    repository: str = ""
    summary: str = ""
    created_at: str = ""
    updated_at: str = ""
    is_active: bool = False
    has_plan: bool = False
    plan_text: str = ""

    # From the session.start event
    copilot_version: str = ""

    # From the session.shutdown event (None if session never closed cleanly)
    total_premium_requests: int | None = None
    total_api_duration_ms: int | None = None
    current_model: str = ""
    current_tokens: int | None = None
    code_changes: dict[str, Any] = field(default_factory=dict)
    model_metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedSession:
    """Everything a renderer needs to draw a Copilot session."""

    meta: SessionMeta
    turns: list[Turn] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION


# ── Public API ───────────────────────────────────────────────────────────────


def normalize_events(events_path: Path, meta: SessionMeta) -> NormalizedSession:
    """Parse ``events.jsonl`` and return a :class:`NormalizedSession`.

    ``meta`` is filled in by the caller from workspace.yaml; we'll enrich it
    with anything we learn from session.start / session.shutdown along the way.
    """
    raw_events = list(_iter_events(events_path))
    return normalize(raw_events, meta)


def normalize(raw_events: list[dict], meta: SessionMeta) -> NormalizedSession:
    """Turn a list of raw event dicts into a :class:`NormalizedSession`.

    Pure function — exposed for tests and callers that already have events
    loaded from somewhere other than disk.
    """
    # First pass: index tool requests (from assistant messages) and tool
    # results (from tool.execution_complete). We need both sides before we
    # can attach the merged ToolCall to the right assistant turn.
    request_index: dict[str, dict] = {}  # toolCallId -> request dict
    result_index: dict[str, dict] = {}  # toolCallId -> tool.execution_complete event
    start_index: dict[str, dict] = {}  # toolCallId -> tool.execution_start event

    for ev in raw_events:
        t = ev.get("type")
        if t == "assistant.message":
            for tr in (ev.get("data") or {}).get("toolRequests") or []:
                tcid = tr.get("toolCallId")
                if tcid:
                    request_index[tcid] = tr
        elif t == "tool.execution_start":
            tcid = (ev.get("data") or {}).get("toolCallId")
            if tcid:
                start_index[tcid] = ev
        elif t == "tool.execution_complete":
            tcid = (ev.get("data") or {}).get("toolCallId")
            if tcid:
                result_index[tcid] = ev

    # Second pass: walk events in order, group into turns.
    turns: list[Turn] = []
    current_assistant: Turn | None = None
    seen_tool_calls: set[str] = set()  # avoid double-emitting if assistant.message repeats

    for ev in raw_events:
        t = ev.get("type")
        if t in _PLUMBING_EVENTS:
            continue
        ts = ev.get("timestamp", "")
        data = ev.get("data") or {}

        if t == "session.start":
            meta.copilot_version = data.get("copilotVersion", meta.copilot_version)
            turns.append(
                Turn(kind="system", timestamp=ts, system_kind="session_start", system_data=data)
            )

        elif t == "user.message":
            current_assistant = None
            turns.append(Turn(kind="user", timestamp=ts, user_text=data.get("content", "")))

        elif t == "assistant.turn_start":
            current_assistant = Turn(
                kind="assistant",
                timestamp=ts,
                turn_id=str(data.get("turnId", "")),
                interaction_id=data.get("interactionId", ""),
            )
            turns.append(current_assistant)

        elif t == "assistant.message":
            if current_assistant is None:
                # Stray message with no surrounding turn — synthesize one.
                current_assistant = Turn(kind="assistant", timestamp=ts)
                turns.append(current_assistant)
            content = data.get("content") or ""
            if content:
                current_assistant.assistant_text = (
                    current_assistant.assistant_text + content
                    if current_assistant.assistant_text
                    else content
                )
            for tr in data.get("toolRequests") or []:
                tcid = tr.get("toolCallId")
                if not tcid or tcid in seen_tool_calls:
                    continue
                seen_tool_calls.add(tcid)
                call = _build_tool_call(tr, start_index.get(tcid), result_index.get(tcid))
                current_assistant.tool_calls.append(call)

        elif t == "assistant.turn_end":
            current_assistant = None

        elif t == "abort":
            if current_assistant is not None:
                current_assistant.aborted = True
                current_assistant.abort_reason = data.get("reason", "")

        elif t == "skill.invoked":
            turns.append(
                Turn(
                    kind="system",
                    timestamp=ts,
                    system_kind="skill_invoked",
                    system_data={
                        "name": data.get("name", ""),
                        "path": data.get("path", ""),
                        "content": data.get("content", ""),
                    },
                )
            )

        elif t == "session.shutdown":
            meta.total_premium_requests = data.get("totalPremiumRequests")
            meta.total_api_duration_ms = data.get("totalApiDurationMs")
            meta.current_model = data.get("currentModel", meta.current_model)
            meta.current_tokens = data.get("currentTokens")
            meta.code_changes = data.get("codeChanges") or {}
            meta.model_metrics = data.get("modelMetrics") or {}
            turns.append(
                Turn(
                    kind="system",
                    timestamp=ts,
                    system_kind="session_shutdown",
                    system_data={
                        "shutdownType": data.get("shutdownType", ""),
                        "totalPremiumRequests": meta.total_premium_requests,
                        "codeChanges": meta.code_changes,
                    },
                )
            )

    # Third pass: stitch in any tool calls that arrived without showing up
    # in assistant.message.toolRequests (rare, but observed for inner-loop
    # tool calls fired by sub-agents). Attach them to the most recent
    # assistant turn with the same interactionId.
    for tcid, complete_ev in result_index.items():
        if tcid in seen_tool_calls:
            continue
        seen_tool_calls.add(tcid)
        complete_data = complete_ev.get("data") or {}
        host_turn = _find_assistant_turn(turns, complete_data.get("interactionId", ""))
        if host_turn is None:
            continue
        # Synthesize a request from the start event if we have one.
        synthetic_request = {
            "toolCallId": tcid,
            "name": (start_index.get(tcid, {}).get("data") or {}).get("toolName", "tool"),
            "arguments": (start_index.get(tcid, {}).get("data") or {}).get("arguments") or {},
        }
        host_turn.tool_calls.append(
            _build_tool_call(synthetic_request, start_index.get(tcid), complete_ev)
        )

    # Fourth pass: compute sub-agent depth for every tool call.
    _assign_depths(turns)

    return NormalizedSession(meta=meta, turns=turns)


# ── Serialization ────────────────────────────────────────────────────────────


def to_dict(ns: NormalizedSession) -> dict:
    """Return a plain-dict representation suitable for JSON / cache."""
    return {
        "schema_version": ns.schema_version,
        "meta": _dataclass_to_dict(ns.meta),
        "turns": [_dataclass_to_dict(t) for t in ns.turns],
    }


def from_dict(d: dict) -> NormalizedSession:
    """Inverse of :func:`to_dict`. Tolerates missing optional fields."""
    meta_fields = SessionMeta.__dataclass_fields__
    tc_fields = ToolCall.__dataclass_fields__
    turn_fields = Turn.__dataclass_fields__
    meta = SessionMeta(
        **{k: v for k, v in (d.get("meta") or {}).items() if k in meta_fields}
    )
    turns: list[Turn] = []
    for traw in d.get("turns") or []:
        tool_calls = [
            ToolCall(**{k: v for k, v in (tc or {}).items() if k in tc_fields})
            for tc in (traw.get("tool_calls") or [])
        ]
        kept = {
            k: v for k, v in traw.items() if k in turn_fields and k != "tool_calls"
        }
        turns.append(Turn(tool_calls=tool_calls, **kept))
    return NormalizedSession(
        meta=meta,
        turns=turns,
        schema_version=int(d.get("schema_version", SCHEMA_VERSION)),
    )


# ── Internals ────────────────────────────────────────────────────────────────


def _iter_events(events_path: Path):
    """Stream events from a JSONL file, skipping malformed lines."""
    with events_path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _build_tool_call(
    request: dict,
    start_ev: dict | None,
    complete_ev: dict | None,
) -> ToolCall:
    """Merge a tool request + start + complete into one :class:`ToolCall`."""
    call = ToolCall(
        tool_call_id=request.get("toolCallId", ""),
        name=request.get("name", ""),
        arguments=request.get("arguments") or {},
        intent=request.get("intentionSummary", "") or "",
        mcp_server=request.get("mcpServerName", "") or "",
        tool_title=request.get("toolTitle", "") or "",
    )

    if start_ev:
        call.started_at = start_ev.get("timestamp", "")

    if complete_ev:
        call.has_result = True
        cdata = complete_ev.get("data") or {}
        call.success = bool(cdata.get("success", False))
        call.model = cdata.get("model", "")
        call.parent_tool_call_id = cdata.get("parentToolCallId", "") or ""
        call.completed_at = complete_ev.get("timestamp", "")
        result = cdata.get("result") or {}
        if isinstance(result, dict):
            call.result_content = result.get("content", "") or ""
            call.result_detailed = result.get("detailedContent", "") or ""
        elif isinstance(result, str):
            call.result_content = result

        telemetry = cdata.get("toolTelemetry") or {}
        if not isinstance(telemetry, dict):
            telemetry = {}
        metrics = telemetry.get("metrics") or {}
        properties = telemetry.get("properties") or {}
        restricted = telemetry.get("restrictedProperties") or {}

        if "linesAdded" in metrics:
            call.lines_added = _coerce_int(metrics.get("linesAdded"))
        if "linesRemoved" in metrics:
            call.lines_removed = _coerce_int(metrics.get("linesRemoved"))
        if "responseTokenLimit" in metrics:
            call.response_token_limit = _coerce_int(metrics.get("responseTokenLimit"))
        if "resultLength" in metrics:
            call.result_length = _coerce_int(metrics.get("resultLength"))
        # File paths can be either a JSON-encoded list (string) or a real list.
        for key in ("filePaths", "filepath", "path"):
            for src in (restricted, properties):
                if key in src:
                    call.file_paths = _coerce_path_list(src[key])
                    break
            if call.file_paths:
                break

        # Heuristic: if the result hit the token limit, mark it truncated.
        if (
            call.result_length is not None
            and call.response_token_limit is not None
            and call.result_length >= call.response_token_limit
        ):
            call.truncated = True

        if call.started_at and call.completed_at:
            call.duration_ms = _diff_ms(call.started_at, call.completed_at)

    return call


def _find_assistant_turn(turns: list[Turn], interaction_id: str) -> Turn | None:
    """Return the most recent assistant turn matching ``interaction_id``."""
    if not interaction_id:
        return None
    for turn in reversed(turns):
        if turn.kind == "assistant" and turn.interaction_id == interaction_id:
            return turn
    return None


def _assign_depths(turns: list[Turn]) -> None:
    """Compute ``depth`` for every tool call based on parent_tool_call_id chains."""
    by_id: dict[str, ToolCall] = {}
    for turn in turns:
        for tc in turn.tool_calls:
            if tc.tool_call_id:
                by_id[tc.tool_call_id] = tc

    cache: dict[str, int] = {}

    def depth_of(tc: ToolCall) -> int:
        if tc.tool_call_id in cache:
            return cache[tc.tool_call_id]
        if not tc.parent_tool_call_id or tc.parent_tool_call_id not in by_id:
            cache[tc.tool_call_id] = 0
            return 0
        parent = by_id[tc.parent_tool_call_id]
        # Cycle guard: cap at depth 10.
        if parent is tc:
            cache[tc.tool_call_id] = 0
            return 0
        cache[tc.tool_call_id] = min(depth_of(parent) + 1, 10)
        return cache[tc.tool_call_id]

    for tc in by_id.values():
        tc.depth = depth_of(tc)


def _diff_ms(start_iso: str, end_iso: str) -> int | None:
    """Return ``end - start`` in milliseconds, or None if either is unparseable."""
    s = _parse_iso(start_iso)
    e = _parse_iso(end_iso)
    if s is None or e is None:
        return None
    return int((e - s).total_seconds() * 1000)


def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _coerce_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _coerce_path_list(v: Any) -> list[str]:
    """Turn a value that might be a JSON-encoded list, a real list, or a string into list[str]."""
    if isinstance(v, list):
        return [str(x) for x in v]
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("["):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return [str(x) for x in parsed]
            except json.JSONDecodeError:
                pass
        return [s] if s else []
    return []


def _dataclass_to_dict(obj: Any) -> dict:
    """Like dataclasses.asdict, but doesn't deep-copy nested dicts/lists.

    asdict() copies everything which is wasteful for our payloads; we don't
    need defensive copies because the caller serializes immediately.
    """
    out: dict[str, Any] = {}
    for f in obj.__dataclass_fields__:
        v = getattr(obj, f)
        if isinstance(v, list) and v and hasattr(v[0], "__dataclass_fields__"):
            out[f] = [_dataclass_to_dict(x) for x in v]
        else:
            out[f] = v
    return out
