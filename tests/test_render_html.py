"""Tests for the HTML renderer.

We don't try to validate the rendered HTML in a browser — that would need
a JS engine. Instead we verify:

1. The generated HTML is structurally sound (single doctype, contains the
   expected tags, closes them).
2. The embedded JSON payload parses back to the original session.
3. User-controlled strings can't break out of the JSON ``<script>`` tag.
4. The ``__TITLE__`` / ``__PAYLOAD__`` placeholders are fully substituted.
"""

from __future__ import annotations

import json
import re

from copsearch.normalize import (
    NormalizedSession,
    SessionMeta,
    ToolCall,
    Turn,
)
from copsearch.render_html import render_html


def _ns(*turns: Turn, **meta_kwargs) -> NormalizedSession:
    base = {"session_id": "test", "summary": "HTML test"}
    base.update(meta_kwargs)
    return NormalizedSession(meta=SessionMeta(**base), turns=list(turns))


def _extract_payload(html: str) -> dict:
    m = re.search(
        r'<script type="application/json" id="data">(.+?)</script>',
        html,
        re.DOTALL,
    )
    assert m, "JSON payload not found"
    raw = m.group(1).replace("<\\/", "</")
    return json.loads(raw)


def test_html_is_self_contained():
    html = render_html(_ns(Turn(kind="user", user_text="hi")))
    assert html.startswith("<!doctype html>") or html.startswith("<!DOCTYPE html>")
    assert "</html>" in html
    # Check for actual external resource loads, not arbitrary URL substrings
    # (XML namespace declarations like ``http://www.w3.org/2000/svg`` are
    # literal strings, not fetches).
    forbidden = (
        '<link rel="stylesheet" href="http',
        '<link rel="stylesheet" href="//',
        '<script src="http',
        '<script src="//',
        '<img src="http',
        "url(http",
        "@import",
        "//cdn",
    )
    for needle in forbidden:
        assert needle not in html, f"external resource leaked: {needle}"


def test_placeholders_replaced():
    html = render_html(_ns())
    assert "__TITLE__" not in html
    assert "__PAYLOAD__" not in html


def test_payload_roundtrip_matches_session():
    ns = _ns(
        Turn(kind="user", user_text="hello"),
        Turn(
            kind="assistant",
            assistant_text="hi back",
            tool_calls=[
                ToolCall(tool_call_id="x", name="bash", arguments={"command": "ls"})
            ],
        ),
    )
    html = render_html(ns)
    data = _extract_payload(html)
    assert data["meta"]["session_id"] == "test"
    assert len(data["turns"]) == 2
    assert data["turns"][0]["kind"] == "user"
    assert data["turns"][1]["tool_calls"][0]["name"] == "bash"


def test_script_tag_in_user_content_is_neutralized():
    """A user prompt containing </script> must not break the embedded JSON."""
    payload = "before</script><script>alert(1)</script>after"
    html = render_html(_ns(Turn(kind="user", user_text=payload)))
    # The data tag should still be a single tag — only one </script> followed
    # by the closing of our outer </script>.
    closing_script_count = html.count("</script>")
    # We have exactly two real </script> tags in the template (the data tag
    # and the bootstrap). The malicious "</script>" from user input must have
    # been escaped.
    assert closing_script_count == 2

    # And the payload must round-trip through JSON correctly.
    data = _extract_payload(html)
    assert data["turns"][0]["user_text"] == payload


def test_dangerous_html_in_summary_is_safe():
    html = render_html(_ns(summary='<img src=x onerror="alert(1)">'))
    # Title should be HTML-escaped in the <title> tag.
    title_match = re.search(r"<title>(.*?)</title>", html)
    assert title_match
    assert "<img" not in title_match.group(1)


def test_title_escapes_ampersand_and_gt():
    """`render_html` must escape & and > (not just <) so the <title> is well-formed."""
    html = render_html(_ns(summary="A & B > C"))
    title_match = re.search(r"<title>(.*?)</title>", html)
    assert title_match
    body = title_match.group(1)
    assert "&amp;" in body
    assert "&gt;" in body
    # Original characters must NOT appear unescaped.
    assert " & " not in body
    assert " > " not in body


def test_no_innerhtml_in_inline_script():
    """The bootstrap script should never use innerHTML (textContent only)."""
    html = render_html(_ns())
    # The inlined JS lives between two <script> markers; check the whole doc.
    assert "innerHTML" not in html


def test_theme_toggle_does_not_depend_on_unset_attribute():
    """Regression: CSS used to depend on data-resolved which JS never set."""
    html = render_html(_ns())
    # The buggy selectors all referenced data-resolved.
    assert "data-resolved" not in html


def test_mutation_prefixes_not_in_temporal_dead_zone():
    """Regression: ``const MUTATION_PREFIXES`` was declared after the rendering
    loop ran, so any session with an edit/create tool that produced a diff
    would crash with ``ReferenceError: Cannot access 'MUTATION_PREFIXES' before
    initialization``. The fix inlines the prefix list inside isMutationSummary.

    Lock that in: if anyone ever pulls the array back out as a top-level
    const, the test catches it.
    """
    html = render_html(_ns())
    assert "const MUTATION_PREFIXES" not in html
    # The function should still exist — sanity check on the renderer JS.
    assert "function isMutationSummary" in html


def test_render_with_edit_tool_carries_diff_data():
    """Sessions with edits used to lose every assistant turn after the first
    edit because of the TDZ bug. Verify the data is still present and the
    HTML is well-formed.
    """
    edit_tc = ToolCall(
        tool_call_id="t",
        name="edit",
        arguments={"path": "f.py"},
        has_result=True,
        success=True,
        result_content="File f.py updated.",
        result_detailed="diff --git a/f.py b/f.py\n@@ -1 +1 @@\n-old\n+new",
    )
    ns = _ns(
        Turn(kind="user", user_text="please change f.py"),
        Turn(kind="assistant", assistant_text="here you go", tool_calls=[edit_tc]),
        Turn(kind="user", user_text="thanks"),
        Turn(kind="assistant", assistant_text="you're welcome"),
    )
    html = render_html(ns)
    data = _extract_payload(html)
    # All four turns survive serialization with their text intact.
    assert len(data["turns"]) == 4
    assistant_texts = [t["assistant_text"] for t in data["turns"] if t["kind"] == "assistant"]
    assert "here you go" in assistant_texts
    assert "you're welcome" in assistant_texts


def test_tool_call_diff_payload_preserved():
    tc = ToolCall(
        tool_call_id="t",
        name="edit",
        arguments={"path": "f.py"},
        has_result=True,
        success=True,
        result_content="File f.py updated.",
        result_detailed="diff --git a/f.py b/f.py\n@@ -1 +1 @@\n-x\n+y",
    )
    html = render_html(_ns(Turn(kind="assistant", tool_calls=[tc])))
    data = _extract_payload(html)
    assert "diff --git" in data["turns"][0]["tool_calls"][0]["result_detailed"]


def test_empty_session_renders():
    html = render_html(_ns())
    assert "</html>" in html
    data = _extract_payload(html)
    assert data["turns"] == []


def test_session_metadata_in_payload():
    ns = _ns()
    ns.meta.cwd = "/Users/test/project"
    ns.meta.branch = "feat/x"
    ns.meta.copilot_version = "1.0.22"
    ns.meta.total_premium_requests = 7
    ns.meta.code_changes = {
        "linesAdded": 10, "linesRemoved": 4, "filesModified": ["a.py", "b.py"]
    }
    ns.meta.model_metrics = {
        "claude-opus-4.6": {"usage": {"inputTokens": 1000, "outputTokens": 50}}
    }
    html = render_html(ns)
    data = _extract_payload(html)
    assert data["meta"]["cwd"] == "/Users/test/project"
    assert data["meta"]["total_premium_requests"] == 7
    assert data["meta"]["code_changes"]["filesModified"] == ["a.py", "b.py"]
    assert data["meta"]["model_metrics"]["claude-opus-4.6"]["usage"]["inputTokens"] == 1000
