"""Render a NormalizedSession to a self-contained HTML file.

The output is one HTML document with all CSS, JS, SVG icons, and session
data inlined — safe to email, attach, or open directly from disk. No
external requests.

The data model::

    {meta, turns: [...]}

is embedded as a JSON blob inside a ``<script type="application/json">`` tag.
A small vanilla-JS bootstrap reads that blob and renders the conversation.

Design principles applied (after ui-ux-pro-max skill):

- Semantic color tokens, paired light + dark themes via ``prefers-color-scheme``
- 16 px body baseline, line-height 1.55, 4/8/12/16/24/32 spacing scale
- ``prefers-reduced-motion`` respected
- SVG icons (no emoji) keyed by tool category
- Card-based turn layout with consistent elevation scale
- Sticky session header + left-rail mini-map for jumping between turns
- Mobile-first: rail collapses, sidebar slides under main column
- All user-controlled strings rendered via ``textContent`` — no XSS surface
"""

from __future__ import annotations

import html
import json

from copsearch.normalize import NormalizedSession, to_dict


def render_html(ns: NormalizedSession) -> str:
    """Return a complete HTML document for the given normalized session."""
    payload = json.dumps(to_dict(ns), ensure_ascii=False)
    # ``</script>`` inside the payload would terminate our script tag early —
    # split the closing slash so the byte sequence never appears literally.
    safe_payload = payload.replace("</", "<\\/")
    raw_title = ns.meta.summary or ns.meta.session_id or "Copilot session"
    # Escape &, <, > so user-controlled summaries can't break the <title>.
    title = html.escape(raw_title, quote=False)
    return _TEMPLATE.replace("__TITLE__", title).replace("__PAYLOAD__", safe_payload)


# ── HTML template ────────────────────────────────────────────────────────────

_TEMPLATE = r"""<!doctype html>
<html lang="en" data-theme="auto">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
/* ── Tokens ───────────────────────────────────────────────────────────────
   Semantic naming, paired light & dark. Override via [data-theme="dark"]
   or [data-theme="light"]; default follows the OS. */
:root {
  --bg-canvas: #fafafa;
  --bg-elev-1: #ffffff;
  --bg-elev-2: #f4f4f5;
  --bg-elev-3: #e9e9ec;
  --bg-code:   #f4f4f5;
  --border:    #e4e4e7;
  --border-strong: #d4d4d8;

  --text-primary:   #18181b;
  --text-secondary: #52525b;
  --text-muted:     #a1a1aa;
  --text-on-accent: #ffffff;

  --accent:      #6366f1;
  --accent-hover:#5258e5;
  --accent-soft: rgba(99,102,241,0.10);
  --accent-ring: rgba(99,102,241,0.35);

  --user-accent:      #2563eb;
  --user-soft:        rgba(37,99,235,0.10);
  --assistant-accent: #7c3aed;
  --assistant-soft:   rgba(124,58,237,0.10);

  --success: #16a34a;
  --success-soft: rgba(22,163,74,0.12);
  --warn:    #d97706;
  --warn-soft: rgba(217,119,6,0.14);
  --error:   #dc2626;
  --error-soft: rgba(220,38,38,0.12);
  --diff-add-bg: rgba(22,163,74,0.10);
  --diff-add-fg: #15803d;
  --diff-del-bg: rgba(220,38,38,0.08);
  --diff-del-fg: #b91c1c;
  --diff-hunk:   #4338ca;

  --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.04);
  --shadow-md: 0 4px 12px -2px rgb(0 0 0 / 0.06), 0 2px 4px -1px rgb(0 0 0 / 0.04);
  --shadow-lg: 0 12px 32px -8px rgb(0 0 0 / 0.10), 0 6px 12px -4px rgb(0 0 0 / 0.06);

  --radius-sm: 6px;
  --radius:    8px;
  --radius-lg: 12px;

  --font-body: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI",
               Inter, Roboto, "Helvetica Neue", Arial, sans-serif;
  --font-mono: ui-monospace, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg-canvas: #0a0a0c;
    --bg-elev-1: #131318;
    --bg-elev-2: #1c1c22;
    --bg-elev-3: #25252d;
    --bg-code:   #0e0e12;
    --border:    #27272f;
    --border-strong: #3a3a44;

    --text-primary:   #f4f4f5;
    --text-secondary: #a1a1aa;
    --text-muted:     #71717a;
    --text-on-accent: #ffffff;

    --accent:      #818cf8;
    --accent-hover:#a5b4fc;
    --accent-soft: rgba(129,140,248,0.14);
    --accent-ring: rgba(129,140,248,0.45);

    --user-accent:      #60a5fa;
    --user-soft:        rgba(96,165,250,0.14);
    --assistant-accent: #c4b5fd;
    --assistant-soft:   rgba(196,181,253,0.14);

    --success: #4ade80;
    --success-soft: rgba(74,222,128,0.16);
    --warn:    #fbbf24;
    --warn-soft: rgba(251,191,36,0.16);
    --error:   #f87171;
    --error-soft: rgba(248,113,113,0.16);
    --diff-add-bg: rgba(74,222,128,0.10);
    --diff-add-fg: #4ade80;
    --diff-del-bg: rgba(248,113,113,0.10);
    --diff-del-fg: #f87171;
    --diff-hunk:   #a5b4fc;

    --shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.30);
    --shadow-md: 0 4px 12px -2px rgb(0 0 0 / 0.40), 0 2px 4px -1px rgb(0 0 0 / 0.30);
    --shadow-lg: 0 12px 32px -8px rgb(0 0 0 / 0.55), 0 6px 12px -4px rgb(0 0 0 / 0.40);
  }
}

/* Manual overrides */
html[data-theme="light"] {
  color-scheme: light;
  --bg-canvas: #fafafa;
  --bg-elev-1: #ffffff;
  --bg-elev-2: #f4f4f5;
  --bg-elev-3: #e9e9ec;
  --bg-code:   #f4f4f5;
  --border:    #e4e4e7;
  --border-strong: #d4d4d8;
  --text-primary:   #18181b;
  --text-secondary: #52525b;
  --text-muted:     #a1a1aa;
  --accent:      #6366f1;
  --accent-soft: rgba(99,102,241,0.10);
  --user-accent:      #2563eb;
  --user-soft:        rgba(37,99,235,0.10);
  --assistant-accent: #7c3aed;
  --assistant-soft:   rgba(124,58,237,0.10);
  --diff-add-fg: #15803d;
  --diff-del-fg: #b91c1c;
  --diff-hunk:   #4338ca;
}
html[data-theme="dark"] {
  color-scheme: dark;
  --bg-canvas: #0a0a0c;
  --bg-elev-1: #131318;
  --bg-elev-2: #1c1c22;
  --bg-elev-3: #25252d;
  --bg-code:   #0e0e12;
  --border:    #27272f;
  --border-strong: #3a3a44;
  --text-primary:   #f4f4f5;
  --text-secondary: #a1a1aa;
  --text-muted:     #71717a;
  --accent:      #818cf8;
  --accent-soft: rgba(129,140,248,0.14);
  --user-accent:      #60a5fa;
  --user-soft:        rgba(96,165,250,0.14);
  --assistant-accent: #c4b5fd;
  --assistant-soft:   rgba(196,181,253,0.14);
  --diff-add-fg: #4ade80;
  --diff-del-fg: #f87171;
  --diff-hunk:   #a5b4fc;
}

/* ── Reset ────────────────────────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  background: var(--bg-canvas);
  color: var(--text-primary);
  font-family: var(--font-body);
  font-size: 16px;
  line-height: 1.55;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
button {
  font-family: inherit;
  font-size: inherit;
  cursor: pointer;
  background: none;
  border: 0;
  color: inherit;
  padding: 0;
}
button:focus-visible {
  outline: 2px solid var(--accent-ring);
  outline-offset: 2px;
  border-radius: var(--radius-sm);
}

/* ── Layout ───────────────────────────────────────────────────────────── */
.app {
  display: grid;
  grid-template-columns: 200px minmax(0, 1fr) 320px;
  min-height: 100vh;
  max-width: 1440px;
  margin: 0 auto;
}
@media (max-width: 1100px) {
  .app { grid-template-columns: minmax(0, 1fr) 300px; }
  .rail { display: none; }
}
@media (max-width: 760px) {
  .app { grid-template-columns: 1fr; }
  .sidebar { position: static; height: auto; border-left: 0;
    border-top: 1px solid var(--border); }
}

/* ── Mini-map rail ───────────────────────────────────────────────────── */
.rail {
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-y: auto;
  padding: 24px 12px;
  border-right: 1px solid var(--border);
  background: var(--bg-canvas);
}
.rail h3 {
  margin: 0 0 12px;
  padding: 0 8px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-muted);
}
.rail-list { list-style: none; margin: 0; padding: 0; display: flex;
  flex-direction: column; gap: 2px; }
.rail-item {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 8px; border-radius: var(--radius-sm);
  font-size: 13px; color: var(--text-secondary);
  text-decoration: none;
  transition: background-color 120ms ease, color 120ms ease;
}
.rail-item:hover { background: var(--bg-elev-2); color: var(--text-primary); }
.rail-item.active { background: var(--accent-soft); color: var(--accent); font-weight: 500; }
.rail-item .num {
  font-variant-numeric: tabular-nums;
  font-size: 11px; color: var(--text-muted);
  min-width: 18px;
}
.rail-item .preview {
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  flex: 1;
}
.rail-item.active .num { color: var(--accent); }

/* ── Main column ─────────────────────────────────────────────────────── */
main {
  padding: 32px clamp(24px, 4vw, 48px) 80px;
  min-width: 0;
}

/* Title + meta header */
.title-bar { margin-bottom: 32px; }
.title-bar h1 {
  margin: 0 0 8px;
  font-size: 26px;
  line-height: 1.2;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--text-primary);
}
.title-bar .subtitle {
  display: flex; flex-wrap: wrap; gap: 16px;
  font-size: 13px; color: var(--text-secondary);
  align-items: center;
}
.title-bar .subtitle .id {
  font-family: var(--font-mono); font-size: 12px;
  background: var(--bg-elev-2); padding: 2px 8px; border-radius: var(--radius-sm);
}
.title-bar .actions { margin-left: auto; display: flex; gap: 8px; }
.btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 12px; border-radius: var(--radius-sm);
  background: var(--bg-elev-1); border: 1px solid var(--border);
  font-size: 13px; color: var(--text-secondary);
  transition: all 120ms ease;
  min-height: 32px;
}
.btn:hover { background: var(--bg-elev-2); color: var(--text-primary);
  border-color: var(--border-strong); }
.btn .icon { width: 16px; height: 16px; }

/* Stats row under title */
.stats {
  display: grid; gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  margin-bottom: 32px;
}
.stat {
  background: var(--bg-elev-1); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 12px 16px;
}
.stat .lbl {
  font-size: 11px; font-weight: 500; color: var(--text-muted);
  text-transform: uppercase; letter-spacing: 0.06em;
  margin-bottom: 4px;
}
.stat .val {
  font-size: 18px; font-weight: 600; color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.stat .val.diff-pos { color: var(--success); }
.stat .val.diff-neg { color: var(--error); }

/* ── Turn cards ───────────────────────────────────────────────────────── */
.turn {
  background: var(--bg-elev-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  margin-bottom: 16px;
  overflow: hidden;
  scroll-margin-top: 24px;
  transition: border-color 120ms ease;
}
.turn:hover { border-color: var(--border-strong); }
.turn.user { border-left: 3px solid var(--user-accent); }
.turn.assistant { border-left: 3px solid var(--assistant-accent); }
.turn.system { border-left: 3px solid var(--text-muted); background: transparent; }

.turn-head {
  display: flex; align-items: center; gap: 12px;
  padding: 14px 20px;
  border-bottom: 1px solid var(--border);
}
.turn.system .turn-head { border-bottom: 0; padding: 10px 20px; }
.turn-head .avatar {
  width: 28px; height: 28px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.turn.user .turn-head .avatar { background: var(--user-soft); color: var(--user-accent); }
.turn.assistant .turn-head .avatar { background: var(--assistant-soft); color: var(--assistant-accent); }
.turn.system .turn-head .avatar { background: var(--bg-elev-2); color: var(--text-muted); }
.turn-head .role {
  font-weight: 600; font-size: 14px;
  color: var(--text-primary);
}
.turn.system .turn-head .role { color: var(--text-secondary); font-weight: 500; font-size: 13px; }
.turn-head .num {
  font-size: 12px; color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
.turn-head .ts {
  margin-left: auto;
  font-size: 12px; color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  font-family: var(--font-mono);
}
.turn.aborted .turn-head .role::after {
  content: "aborted";
  margin-left: 8px;
  background: var(--warn-soft); color: var(--warn);
  padding: 2px 8px; border-radius: 9999px;
  font-size: 11px; font-weight: 500; letter-spacing: 0.02em;
  text-transform: uppercase;
}

.turn-body { padding: 16px 20px 20px; }
.turn.system .turn-body { padding: 0 20px 12px; }

/* Message-text bubble. User prose and assistant prose each get a
   tinted background so they're easy to scan past the tool-call noise.
   Tool calls within an assistant turn keep their own neutral cards. */
.turn-body > .text {
  white-space: pre-wrap; word-wrap: break-word;
  color: var(--text-primary);
  font-size: 15.5px;
  line-height: 1.6;
  padding: 14px 18px;
  border-radius: var(--radius);
}
.turn.user .turn-body > .text {
  background: var(--user-soft);
  border-left: 3px solid var(--user-accent);
}
.turn.assistant .turn-body > .text {
  background: var(--assistant-soft);
  border-left: 3px solid var(--assistant-accent);
}
.turn.system .turn-body .text {
  white-space: pre-wrap; word-wrap: break-word;
  color: var(--text-secondary);
  font-size: 14px;
}

.turn-body > .text + .tools { margin-top: 16px; }
.tools { display: flex; flex-direction: column; gap: 8px; }

/* ── Tool calls ───────────────────────────────────────────────────────── */
.tool {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-elev-1);
  overflow: hidden;
  transition: border-color 120ms ease;
}
.tool[data-depth="1"] { margin-left: 24px; }
.tool[data-depth="2"] { margin-left: 48px; }
.tool[data-depth="3"] { margin-left: 72px; }
.tool:hover { border-color: var(--border-strong); }

.tool-head {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 14px;
  user-select: none;
  min-height: 44px;
}
.tool-head:hover { background: var(--bg-elev-2); }
.tool[data-success="true"]  .tool-head .status { color: var(--success); }
.tool[data-success="false"] .tool-head .status { color: var(--error); }
.tool[data-success="null"]  .tool-head .status { color: var(--warn); }
.tool-head .status { width: 16px; height: 16px; flex-shrink: 0; }
.tool-head .icon {
  width: 18px; height: 18px; flex-shrink: 0;
  color: var(--text-secondary);
}
.tool-head .name {
  font-family: var(--font-mono);
  font-size: 13px; font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
}
.tool-head .mcp {
  color: var(--text-muted);
  font-family: var(--font-mono); font-size: 12px;
}
.tool-head .intent {
  flex: 1; min-width: 0;
  font-size: 13px; color: var(--text-secondary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.tool-head .pill {
  font-size: 11px; padding: 2px 8px; border-radius: 9999px;
  font-weight: 500;
}
.tool-head .pill.warn  { background: var(--warn-soft);  color: var(--warn); }
.tool-head .pill.muted { background: var(--bg-elev-2);   color: var(--text-muted);
  font-variant-numeric: tabular-nums; font-family: var(--font-mono); }
.tool-head .chevron {
  width: 14px; height: 14px; flex-shrink: 0;
  color: var(--text-muted);
  transition: transform 180ms ease;
}
@media (prefers-reduced-motion: reduce) { .tool-head .chevron { transition: none; } }
.tool.open .tool-head .chevron { transform: rotate(90deg); }

.tool-body {
  display: none;
  padding: 0 14px 14px;
  border-top: 1px solid var(--border);
  background: var(--bg-elev-2);
}
.tool.open .tool-body { display: block; }
.tool-body section { margin-top: 12px; }
.tool-body section:first-child { margin-top: 12px; }
.tool-body h5 {
  font-size: 11px; font-weight: 600; letter-spacing: 0.06em;
  text-transform: uppercase; color: var(--text-muted);
  margin: 0 0 6px;
}

/* Argument rows */
.args { display: grid; gap: 4px; }
.arg-row {
  display: grid;
  grid-template-columns: minmax(70px, max-content) 1fr;
  gap: 12px;
  padding: 6px 0;
  border-bottom: 1px solid var(--border);
}
.arg-row:last-child { border-bottom: 0; }
.arg-row .k {
  font-size: 12px; font-family: var(--font-mono);
  color: var(--text-muted);
}
.arg-row .v {
  font-size: 13px; font-family: var(--font-mono);
  color: var(--text-primary);
  white-space: pre-wrap; word-break: break-word;
  min-width: 0;
}

/* Result block */
.result {
  background: var(--bg-code);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.5;
  max-height: 480px;
  overflow: auto;
}
.result pre {
  margin: 0; padding: 12px 14px;
  white-space: pre;
}
.result.diff pre { white-space: pre; }
.result .add  { color: var(--diff-add-fg); background: var(--diff-add-bg); display: block; }
.result .del  { color: var(--diff-del-fg); background: var(--diff-del-bg); display: block; }
.result .hunk { color: var(--diff-hunk); display: block; }
.result .meta { color: var(--text-muted); display: block; }

.result-meta {
  display: flex; flex-wrap: wrap; gap: 8px;
  margin-top: 8px;
  font-size: 12px; color: var(--text-muted);
}
.result-meta .badge {
  padding: 2px 8px; border-radius: 9999px;
  background: var(--bg-elev-3);
  font-variant-numeric: tabular-nums;
}
.result-meta .badge.add { background: var(--success-soft); color: var(--success); }
.result-meta .badge.del { background: var(--error-soft); color: var(--error); }

/* Skill / system body */
.system-body { display: flex; flex-direction: column; gap: 6px;
  font-size: 13px; color: var(--text-secondary); }
.system-body code {
  font-family: var(--font-mono); font-size: 12.5px;
  background: var(--bg-elev-2); padding: 1px 6px;
  border-radius: var(--radius-sm);
  color: var(--text-primary);
}

/* ── Sidebar ──────────────────────────────────────────────────────────── */
.sidebar {
  position: sticky; top: 0; height: 100vh; overflow-y: auto;
  background: var(--bg-elev-1);
  border-left: 1px solid var(--border);
  padding: 32px 24px;
}
.sidebar h2 {
  margin: 0 0 16px;
  font-size: 12px; font-weight: 600; letter-spacing: 0.06em;
  text-transform: uppercase; color: var(--text-muted);
}
.sidebar h2:not(:first-child) { margin-top: 28px; }

.meta-list dt {
  font-size: 11px; font-weight: 500;
  text-transform: uppercase; letter-spacing: 0.06em;
  color: var(--text-muted);
  margin-bottom: 2px;
}
.meta-list dd {
  margin: 0 0 12px;
  font-size: 13px;
  color: var(--text-primary);
  word-break: break-word;
}
.meta-list dd .mono {
  font-family: var(--font-mono); font-size: 12px;
}
.tag {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 2px 8px; border-radius: 9999px;
  font-size: 11px; font-weight: 500;
}
.tag.live {
  background: var(--success-soft); color: var(--success);
}
.tag.live::before {
  content: ""; width: 6px; height: 6px; border-radius: 50%;
  background: currentColor;
  animation: pulse 1.8s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
@media (prefers-reduced-motion: reduce) {
  .tag.live::before { animation: none; }
}

.usage-row {
  display: flex; justify-content: space-between; align-items: baseline;
  padding: 6px 0;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
}
.usage-row:last-child { border-bottom: 0; }
.usage-row .lbl { color: var(--text-secondary); }
.usage-row .val {
  font-family: var(--font-mono); color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}

/* Files-modified list */
.files-list { list-style: none; margin: 0; padding: 0; }
.files-list li {
  display: flex; align-items: center; gap: 6px;
  padding: 4px 0;
  font-size: 12px; font-family: var(--font-mono);
  color: var(--text-secondary);
}
.files-list li .icon { width: 12px; height: 12px; flex-shrink: 0; opacity: 0.7; }

.plan-block {
  background: var(--bg-elev-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 12px;
  font-size: 12.5px;
  white-space: pre-wrap;
  max-height: 280px;
  overflow-y: auto;
  font-family: var(--font-mono);
  color: var(--text-secondary);
}

/* Theme toggle. The icon shown reflects the *current effective* theme:
   in auto mode we mirror the OS preference via prefers-color-scheme,
   so a media query picks the right icon for us. Manual overrides via
   [data-theme="light"|"dark"] win because they're more specific. */
.theme-toggle .icon { width: 16px; height: 16px; }
.theme-toggle .sun  { display: block; }
.theme-toggle .moon { display: none;  }
@media (prefers-color-scheme: dark) {
  html[data-theme="auto"] .theme-toggle .sun  { display: none;  }
  html[data-theme="auto"] .theme-toggle .moon { display: block; }
}
html[data-theme="dark"]  .theme-toggle .sun  { display: none;  }
html[data-theme="dark"]  .theme-toggle .moon { display: block; }
html[data-theme="light"] .theme-toggle .sun  { display: block; }
html[data-theme="light"] .theme-toggle .moon { display: none;  }

/* Empty state */
.empty {
  padding: 48px 24px;
  text-align: center;
  color: var(--text-muted);
}

/* Print */
@media print {
  .rail, .sidebar, .title-bar .actions { display: none; }
  .app { grid-template-columns: 1fr; max-width: none; }
  .turn { box-shadow: none; break-inside: avoid; }
  .tool-body { display: block !important; border-top: 1px solid #ccc; }
}
</style>
</head>
<body>
<!-- Inline SVG sprite — referenced via <use> below. -->
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
  <defs>
    <symbol id="i-user" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="8" r="4"/><path d="M4 21v-1a8 8 0 0 1 16 0v1"/>
    </symbol>
    <symbol id="i-bot" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <rect x="4" y="6" width="16" height="14" rx="3"/><circle cx="9" cy="13" r="1.2" fill="currentColor"/><circle cx="15" cy="13" r="1.2" fill="currentColor"/><path d="M12 2v4M9 18h6"/>
    </symbol>
    <symbol id="i-system" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3h0a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8v0a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>
    </symbol>
    <symbol id="i-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M20 6 9 17l-5-5"/>
    </symbol>
    <symbol id="i-x" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="M18 6 6 18M6 6l12 12"/>
    </symbol>
    <symbol id="i-clock" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>
    </symbol>
    <symbol id="i-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="m9 18 6-6-6-6"/>
    </symbol>
    <symbol id="i-terminal" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="m4 17 6-6-6-6"/><path d="M12 19h8"/>
    </symbol>
    <symbol id="i-file" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>
    </symbol>
    <symbol id="i-edit" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 1 1 3 3L7 19l-4 1 1-4Z"/>
    </symbol>
    <symbol id="i-plus-file" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M12 18v-6M9 15h6"/>
    </symbol>
    <symbol id="i-search" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>
    </symbol>
    <symbol id="i-globe" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a14 14 0 0 1 0 20 14 14 0 0 1 0-20Z"/>
    </symbol>
    <symbol id="i-folder" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
    </symbol>
    <symbol id="i-zap" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M13 2 3 14h9l-1 8 10-12h-9z"/>
    </symbol>
    <symbol id="i-cpu" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 15h3M1 9h3M1 15h3"/>
    </symbol>
    <symbol id="i-database" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v6c0 1.7 4 3 9 3s9-1.3 9-3V5"/><path d="M3 12v6c0 1.7 4 3 9 3s9-1.3 9-3v-6"/>
    </symbol>
    <symbol id="i-puzzle" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M19.4 7H17V4.6A2.6 2.6 0 0 0 14.4 2h-1.2a2.4 2.4 0 0 0 0 4.8H13V8H7v3.4a2.4 2.4 0 1 0 0 4.4V19a2 2 0 0 0 2 2h3.4a2.4 2.4 0 0 1 4.4 0H20a2 2 0 0 0 2-2v-3.4a2.4 2.4 0 0 0 0-4.4V9a2 2 0 0 0-2-2z"/>
    </symbol>
    <symbol id="i-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/>
    </symbol>
    <symbol id="i-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>
    </symbol>
    <symbol id="i-target" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>
    </symbol>
    <symbol id="i-hourglass" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M5 22h14M5 2h14M17 22v-4.2a3 3 0 0 0-1-2.3l-3-2.5a2 2 0 0 1 0-3l3-2.5A3 3 0 0 0 17 6.2V2H7v4.2a3 3 0 0 0 1 2.3l3 2.5a2 2 0 0 1 0 3l-3 2.5A3 3 0 0 0 7 17.8V22"/>
    </symbol>
  </defs>
</svg>

<div class="app">
  <nav class="rail" aria-label="Conversation map">
    <h3>Turns</h3>
    <ol class="rail-list" id="rail" role="list"></ol>
  </nav>

  <main>
    <header class="title-bar">
      <h1 id="title"></h1>
      <div class="subtitle">
        <span class="id mono" id="session-id"></span>
        <span id="header-tags"></span>
        <div class="actions">
          <button class="btn theme-toggle" type="button" id="theme-btn" aria-label="Toggle theme">
            <svg class="icon sun" aria-hidden="true"><use href="#i-sun"/></svg>
            <svg class="icon moon" aria-hidden="true"><use href="#i-moon"/></svg>
          </button>
          <button class="btn" type="button" id="expand-all" aria-label="Expand all tool calls">
            <svg class="icon" aria-hidden="true"><use href="#i-chevron"/></svg>
            <span>Expand all</span>
          </button>
        </div>
      </div>
    </header>

    <section class="stats" id="stats" aria-label="Session statistics"></section>
    <div id="turns"></div>
  </main>

  <aside class="sidebar" aria-label="Session metadata">
    <h2>Session</h2>
    <dl class="meta-list" id="meta-list"></dl>

    <div id="totals-block" hidden>
      <h2>Token usage</h2>
      <div id="usage-list"></div>
    </div>

    <div id="files-block" hidden>
      <h2>Files modified</h2>
      <ul class="files-list" id="files-list"></ul>
    </div>

    <div id="plan-block" hidden>
      <h2>Plan</h2>
      <div class="plan-block" id="plan-text"></div>
    </div>
  </aside>
</div>

<script type="application/json" id="data">__PAYLOAD__</script>
<script>
(() => {
  "use strict";
  const data  = JSON.parse(document.getElementById("data").textContent);
  const meta  = data.meta || {};
  const turns = data.turns || [];

  // ── Theme handling ─────────────────────────────────────────────────
  const THEME_KEY = "copsearch:theme";
  const root = document.documentElement;
  const stored = (() => { try { return localStorage.getItem(THEME_KEY); } catch (_) { return null; } })();
  if (stored === "light" || stored === "dark") root.dataset.theme = stored;
  document.getElementById("theme-btn").addEventListener("click", () => {
    const cur = root.dataset.theme;
    const next = cur === "dark" ? "light" : (cur === "light" ? "auto" : "dark");
    if (next === "auto") {
      root.dataset.theme = "auto";
      try { localStorage.removeItem(THEME_KEY); } catch (_) {}
    } else {
      root.dataset.theme = next;
      try { localStorage.setItem(THEME_KEY, next); } catch (_) {}
    }
  });

  // ── Title + ID ─────────────────────────────────────────────────────
  document.title = meta.summary || meta.session_id || "Copilot session";
  document.getElementById("title").textContent = meta.summary || "(no summary)";
  document.getElementById("session-id").textContent = meta.session_id || "";

  // Header tags (model, branch, active)
  const headerTags = document.getElementById("header-tags");
  const tagBits = [];
  if (meta.is_active) tagBits.push({ cls: "tag live", text: "active" });
  for (const b of tagBits) {
    const el = document.createElement("span");
    el.className = b.cls;
    el.textContent = b.text;
    headerTags.appendChild(el);
  }

  // ── Stats ──────────────────────────────────────────────────────────
  const statsBox = document.getElementById("stats");
  function statCard(lbl, val, klass) {
    const card = document.createElement("div");
    card.className = "stat";
    const l = document.createElement("div");
    l.className = "lbl"; l.textContent = lbl;
    const v = document.createElement("div");
    v.className = "val" + (klass ? " " + klass : "");
    v.textContent = val;
    card.appendChild(l); card.appendChild(v);
    return card;
  }
  const userCount = turns.filter(t => t.kind === "user").length;
  const asstCount = turns.filter(t => t.kind === "assistant").length;
  let toolCount = 0;
  for (const t of turns) toolCount += (t.tool_calls || []).length;
  statsBox.appendChild(statCard("Prompts", String(userCount)));
  statsBox.appendChild(statCard("Replies", String(asstCount)));
  statsBox.appendChild(statCard("Tool calls", String(toolCount)));
  if (meta.total_premium_requests != null) {
    statsBox.appendChild(statCard("Premium reqs", String(meta.total_premium_requests)));
  }
  if (meta.total_api_duration_ms != null) {
    statsBox.appendChild(statCard("API time", (meta.total_api_duration_ms/1000).toFixed(1) + " s"));
  }
  const cc = meta.code_changes || {};
  if (cc.linesAdded || cc.linesRemoved) {
    const node = document.createElement("div");
    node.className = "stat";
    const l = document.createElement("div"); l.className = "lbl"; l.textContent = "Code changes";
    const v = document.createElement("div"); v.className = "val";
    const add = document.createElement("span"); add.className = "diff-pos"; add.textContent = "+" + (cc.linesAdded||0);
    const sep = document.createElement("span"); sep.style.color = "var(--text-muted)"; sep.textContent = " / ";
    const rem = document.createElement("span"); rem.className = "diff-neg"; rem.textContent = "-" + (cc.linesRemoved||0);
    v.appendChild(add); v.appendChild(sep); v.appendChild(rem);
    node.appendChild(l); node.appendChild(v);
    statsBox.appendChild(node);
  }

  // ── Sidebar ────────────────────────────────────────────────────────
  const metaList = document.getElementById("meta-list");
  function metaRow(label, val, mono) {
    if (val == null || val === "") return;
    const dt = document.createElement("dt"); dt.textContent = label;
    const dd = document.createElement("dd");
    if (mono) {
      const span = document.createElement("span");
      span.className = "mono"; span.textContent = String(val);
      dd.appendChild(span);
    } else {
      dd.textContent = String(val);
    }
    metaList.appendChild(dt); metaList.appendChild(dd);
  }
  if (meta.is_active) {
    const dt = document.createElement("dt"); dt.textContent = "Status";
    const dd = document.createElement("dd");
    const tag = document.createElement("span"); tag.className = "tag live"; tag.textContent = "Live";
    dd.appendChild(tag);
    metaList.appendChild(dt); metaList.appendChild(dd);
  }
  metaRow("Directory", meta.cwd, true);
  metaRow("Repository", meta.repository);
  metaRow("Branch", meta.branch);
  metaRow("Created", fmtDate(meta.created_at));
  metaRow("Updated", fmtDate(meta.updated_at));
  metaRow("Copilot version", meta.copilot_version);
  metaRow("Current model", meta.current_model);

  // Token usage
  if (meta.model_metrics && Object.keys(meta.model_metrics).length) {
    const block = document.getElementById("totals-block");
    const list = document.getElementById("usage-list");
    block.hidden = false;
    for (const [model, m] of Object.entries(meta.model_metrics)) {
      const u = (m && m.usage) || {};
      const head = document.createElement("div");
      head.style.fontSize = "12px"; head.style.color = "var(--text-secondary)";
      head.style.marginTop = "10px"; head.style.fontWeight = "500";
      head.textContent = model;
      list.appendChild(head);
      const fields = [
        ["Input",      u.inputTokens],
        ["Output",     u.outputTokens],
        ["Cache read", u.cacheReadTokens],
      ];
      for (const [lbl, val] of fields) {
        if (val == null) continue;
        const row = document.createElement("div");
        row.className = "usage-row";
        const l = document.createElement("span"); l.className = "lbl"; l.textContent = lbl;
        const v = document.createElement("span"); v.className = "val"; v.textContent = (val||0).toLocaleString();
        row.appendChild(l); row.appendChild(v);
        list.appendChild(row);
      }
    }
  }

  // Files modified
  if (cc.filesModified && cc.filesModified.length) {
    document.getElementById("files-block").hidden = false;
    const list = document.getElementById("files-list");
    for (const fp of cc.filesModified) {
      const li = document.createElement("li");
      const ic = svgIcon("i-file"); ic.classList.add("icon");
      li.appendChild(ic);
      const span = document.createElement("span"); span.textContent = fp;
      li.appendChild(span);
      list.appendChild(li);
    }
  }

  // Plan
  if (meta.has_plan && meta.plan_text) {
    document.getElementById("plan-block").hidden = false;
    document.getElementById("plan-text").textContent = meta.plan_text;
  }

  // ── Turns ──────────────────────────────────────────────────────────
  const turnsBox = document.getElementById("turns");
  const railList = document.getElementById("rail");
  let userN = 0;

  if (!turns.length) {
    const e = document.createElement("div");
    e.className = "empty";
    e.textContent = "This session has no captured events.";
    turnsBox.appendChild(e);
  }

  turns.forEach((t, idx) => {
    if (t.kind === "user") userN++;
    const turnId = "t" + idx;
    const el = renderTurn(t, userN, turnId);
    if (el) turnsBox.appendChild(el);
    addRailItem(t, userN, turnId);
  });

  // ── Expand all ─────────────────────────────────────────────────────
  let allOpen = false;
  document.getElementById("expand-all").addEventListener("click", (e) => {
    allOpen = !allOpen;
    for (const tool of document.querySelectorAll(".tool")) {
      tool.classList.toggle("open", allOpen);
    }
    e.currentTarget.querySelector("span").textContent = allOpen ? "Collapse all" : "Expand all";
  });

  // ── Rail active-on-scroll ──────────────────────────────────────────
  if ("IntersectionObserver" in window) {
    const map = new Map();
    for (const item of railList.querySelectorAll(".rail-item")) {
      map.set(item.dataset.target, item);
    }
    const obs = new IntersectionObserver((entries) => {
      for (const ent of entries) {
        if (!ent.isIntersecting) continue;
        const item = map.get(ent.target.id);
        if (!item) continue;
        for (const i of railList.querySelectorAll(".rail-item.active")) i.classList.remove("active");
        item.classList.add("active");
      }
    }, { rootMargin: "-30% 0px -65% 0px" });
    for (const t of document.querySelectorAll(".turn")) obs.observe(t);
  }

  // ── helpers ────────────────────────────────────────────────────────

  function renderTurn(t, userN, turnId) {
    const el = document.createElement("article");
    el.className = "turn " + t.kind;
    el.id = turnId;
    if (t.aborted) el.classList.add("aborted");

    // Head
    const head = document.createElement("header"); head.className = "turn-head";
    const av = document.createElement("span"); av.className = "avatar";
    const avIcon = svgIcon(avatarIconFor(t)); avIcon.style.width = "16px"; avIcon.style.height = "16px";
    av.appendChild(avIcon);
    head.appendChild(av);
    const role = document.createElement("span"); role.className = "role";
    role.textContent = roleLabel(t, userN);
    head.appendChild(role);
    if (t.kind === "user") {
      const num = document.createElement("span"); num.className = "num"; num.textContent = "#" + userN;
      head.appendChild(num);
    } else if (t.kind === "assistant" && t.turn_id !== "" && t.turn_id != null) {
      const num = document.createElement("span"); num.className = "num"; num.textContent = "t" + t.turn_id;
      head.appendChild(num);
    }
    if (t.timestamp) {
      const ts = document.createElement("span"); ts.className = "ts"; ts.textContent = shortTs(t.timestamp);
      head.appendChild(ts);
    }
    el.appendChild(head);

    // Body
    const body = document.createElement("div"); body.className = "turn-body";
    if (t.kind === "user" && t.user_text) {
      body.appendChild(textBlock(t.user_text));
    } else if (t.kind === "assistant") {
      if (t.assistant_text) body.appendChild(textBlock(t.assistant_text));
      const calls = t.tool_calls || [];
      if (calls.length) {
        const tools = document.createElement("div"); tools.className = "tools";
        for (const tc of calls) tools.appendChild(renderTool(tc));
        body.appendChild(tools);
      }
    } else if (t.kind === "system") {
      body.appendChild(renderSystemBody(t));
    }
    el.appendChild(body);
    return el;
  }

  function addRailItem(t, userN, turnId) {
    const a = document.createElement("a");
    a.className = "rail-item";
    a.href = "#" + turnId;
    a.dataset.target = turnId;
    const num = document.createElement("span");
    num.className = "num";
    num.textContent = (t.kind === "user") ? "#" + userN : "·";
    a.appendChild(num);
    const prev = document.createElement("span");
    prev.className = "preview";
    prev.textContent = railPreview(t);
    a.appendChild(prev);
    railList.appendChild(a);
  }

  function railPreview(t) {
    if (t.kind === "user") return (t.user_text || "(empty prompt)").slice(0, 64);
    if (t.kind === "assistant") {
      if (t.assistant_text) return t.assistant_text.slice(0, 64);
      const calls = t.tool_calls || [];
      if (calls.length) {
        return calls.slice(0, 2).map(c => c.name).join(", ") +
               (calls.length > 2 ? ` +${calls.length - 2}` : "");
      }
      return "(no text)";
    }
    if (t.system_kind === "skill_invoked") return "skill: " + ((t.system_data||{}).name || "");
    if (t.system_kind === "session_start") return "session start";
    if (t.system_kind === "session_shutdown") return "session end";
    return t.system_kind || "system";
  }

  function avatarIconFor(t) {
    if (t.kind === "user") return "i-user";
    if (t.kind === "assistant") return "i-bot";
    return "i-system";
  }

  function roleLabel(t, userN) {
    if (t.kind === "user") return "You";
    if (t.kind === "assistant") return "Assistant";
    if (t.system_kind === "skill_invoked") return "Skill invoked";
    if (t.system_kind === "session_start") return "Session start";
    if (t.system_kind === "session_shutdown") return "Session end";
    return "System";
  }

  function textBlock(s) {
    const p = document.createElement("div"); p.className = "text"; p.textContent = s; return p;
  }

  function labelledLine(label, valueText) {
    const div = document.createElement("div");
    const strong = document.createElement("strong");
    strong.textContent = label;
    div.appendChild(strong);
    div.appendChild(document.createTextNode(" "));
    const code = document.createElement("code");
    code.textContent = valueText || "";
    div.appendChild(code);
    return div;
  }
  function renderSystemBody(t) {
    const wrap = document.createElement("div"); wrap.className = "system-body";
    const d = t.system_data || {};
    if (t.system_kind === "skill_invoked") {
      wrap.appendChild(labelledLine("Skill:", d.name));
      if (d.path) wrap.appendChild(labelledLine("Path:", d.path));
    } else if (t.system_kind === "session_shutdown") {
      const cc = d.codeChanges || {};
      const txt = document.createElement("div");
      txt.textContent =
        `${cc.linesAdded||0} lines added, ${cc.linesRemoved||0} lines removed across ${(cc.filesModified||[]).length} file(s)`;
      wrap.appendChild(txt);
    } else if (t.system_kind === "session_start") {
      const v = document.createElement("div");
      v.textContent = "Copilot " + (d.copilotVersion || "—") + " · " + (d.context && d.context.cwd || "");
      wrap.appendChild(v);
    }
    return wrap;
  }

  function renderTool(tc) {
    const wrap = document.createElement("div");
    wrap.className = "tool";
    wrap.dataset.depth = String(Math.min(tc.depth || 0, 3));
    // Explicit "true" | "false" | "null" — keep the value stable for the
    // CSS selector ``.tool[data-success="..."]`` regardless of how
    // ``tc.success`` is represented in JSON (true/false/null/undefined).
    wrap.dataset.success =
      tc.success === true ? "true" :
      tc.success === false ? "false" : "null";

    const head = document.createElement("button");
    head.type = "button";
    head.className = "tool-head";
    head.setAttribute("aria-expanded", "false");
    head.addEventListener("click", () => {
      const open = wrap.classList.toggle("open");
      head.setAttribute("aria-expanded", String(open));
    });

    const status = svgIcon(statusIconFor(tc));
    status.classList.add("status");
    head.appendChild(status);

    const icon = svgIcon(toolIconFor(tc));
    icon.classList.add("icon");
    head.appendChild(icon);

    if (tc.mcp_server) {
      const m = document.createElement("span"); m.className = "mcp";
      m.textContent = tc.mcp_server + "::"; head.appendChild(m);
    }
    const name = document.createElement("span"); name.className = "name";
    name.textContent = tc.name; head.appendChild(name);

    const intent = document.createElement("span"); intent.className = "intent";
    intent.textContent = tc.intent || summarizeArgs(tc.arguments) || "";
    head.appendChild(intent);

    if (tc.truncated) {
      const p = document.createElement("span"); p.className = "pill warn";
      p.textContent = "truncated"; head.appendChild(p);
    }
    if (tc.duration_ms != null && tc.duration_ms >= 100) {
      const d = document.createElement("span"); d.className = "pill muted";
      d.textContent = formatDuration(tc.duration_ms); head.appendChild(d);
    }

    const chev = svgIcon("i-chevron"); chev.classList.add("chevron");
    head.appendChild(chev);
    wrap.appendChild(head);

    // Body
    const body = document.createElement("div"); body.className = "tool-body";

    if (tc.arguments && Object.keys(tc.arguments).length) {
      const sec = document.createElement("section");
      const h = document.createElement("h5"); h.textContent = "Arguments"; sec.appendChild(h);
      const grid = document.createElement("div"); grid.className = "args";
      for (const [k, v] of Object.entries(tc.arguments)) {
        const row = document.createElement("div"); row.className = "arg-row";
        const kEl = document.createElement("span"); kEl.className = "k"; kEl.textContent = k;
        const vEl = document.createElement("span"); vEl.className = "v";
        vEl.textContent = (typeof v === "string") ? v : JSON.stringify(v, null, 2);
        row.appendChild(kEl); row.appendChild(vEl);
        grid.appendChild(row);
      }
      sec.appendChild(grid);
      body.appendChild(sec);
    }

    if (tc.has_result) {
      const sec = document.createElement("section");
      const h = document.createElement("h5"); h.textContent = "Result"; sec.appendChild(h);
      const blob = pickResultBody(tc);
      if (blob) sec.appendChild(renderResult(blob));
      const meta = resultMeta(tc);
      if (meta) sec.appendChild(meta);
      body.appendChild(sec);
    } else if (tc.has_result === false) {
      const sec = document.createElement("section");
      const note = document.createElement("div");
      note.style.color = "var(--text-muted)";
      note.style.fontStyle = "italic";
      note.style.fontSize = "13px";
      note.textContent = "(no result captured — call may have been aborted)";
      sec.appendChild(note);
      body.appendChild(sec);
    }
    wrap.appendChild(body);
    return wrap;
  }

  function statusIconFor(tc) {
    if (!tc.has_result) return "i-hourglass";
    return tc.success ? "i-check" : "i-x";
  }

  function toolIconFor(tc) {
    const n = (tc.name || "").toLowerCase();
    if (tc.mcp_server) return "i-puzzle";
    if (n === "bash" || n.includes("bash") || n.includes("shell")) return "i-terminal";
    if (n === "edit" || n.includes("edit") || n.includes("replace")) return "i-edit";
    if (n === "create" || n === "write" || n.includes("create_")) return "i-plus-file";
    if (n === "view" || n === "read" || n.includes("read")) return "i-file";
    if (n === "grep" || n.includes("search") || n === "glob") return "i-search";
    if (n.includes("web") || n.includes("fetch") || n.includes("url")) return "i-globe";
    if (n === "task" || n === "agent" || n.includes("agent")) return "i-cpu";
    if (n.includes("sql") || n.includes("database") || n.includes("query")) return "i-database";
    if (n.includes("intent") || n.includes("report")) return "i-target";
    if (n === "skill" || n.includes("skill")) return "i-puzzle";
    if (n.includes("memor") || n.includes("scratch")) return "i-folder";
    return "i-zap";
  }

  function resultMeta(tc) {
    const bits = [];
    if (tc.lines_added != null && tc.lines_added > 0) bits.push({ cls: "badge add", text: "+" + tc.lines_added });
    if (tc.lines_removed != null && tc.lines_removed > 0) bits.push({ cls: "badge del", text: "-" + tc.lines_removed });
    if ((tc.file_paths || []).length) {
      for (const fp of tc.file_paths.slice(0, 3)) bits.push({ cls: "badge", text: fp });
      if (tc.file_paths.length > 3) bits.push({ cls: "badge", text: "+" + (tc.file_paths.length - 3) + " more" });
    }
    if (!bits.length) return null;
    const wrap = document.createElement("div"); wrap.className = "result-meta";
    for (const b of bits) {
      const span = document.createElement("span");
      span.className = b.cls; span.textContent = b.text;
      wrap.appendChild(span);
    }
    return wrap;
  }

  // NOTE: keep the prefix list inline. Hoisting a `const` here would put
  // it in the temporal dead zone when isMutationSummary is invoked from
  // the rendering loop above (function decls hoist, `const` doesn't —
  // and pickResultBody runs eagerly during initial render).
  function isMutationSummary(s) {
    s = (s || "").trim();
    if (!s || s.indexOf("\n") >= 0) return false;
    const prefixes = [
      "File ", "Created file ", "Created ", "Wrote ",
      "Modified ", "Updated ", "Edited ", "Replaced ",
    ];
    for (const p of prefixes) if (s.startsWith(p)) return true;
    return false;
  }
  function pickResultBody(tc) {
    const content  = tc.result_content || "";
    const detailed = tc.result_detailed || "";
    if (!detailed) return content;
    if (!content)  return detailed;
    const isDiff = detailed.indexOf("diff --git") >= 0 ||
      detailed.trimStart().startsWith("@@ ") ||
      detailed.trimStart().startsWith("+++ ");
    if (isDiff && isMutationSummary(content)) return detailed;
    return content;
  }

  function renderResult(text) {
    const wrap = document.createElement("div"); wrap.className = "result";
    const isDiff = /^diff --git|^@@|^\+\+\+|^---/m.test(text.slice(0, 200));
    const pre = document.createElement("pre");
    if (isDiff) {
      wrap.classList.add("diff");
      for (const line of text.split("\n")) {
        const span = document.createElement("span");
        if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("diff ") || line.startsWith("index ")) span.className = "meta";
        else if (line.startsWith("+")) span.className = "add";
        else if (line.startsWith("-")) span.className = "del";
        else if (line.startsWith("@@")) span.className = "hunk";
        span.textContent = line + "\n";
        pre.appendChild(span);
      }
    } else {
      pre.textContent = text;
    }
    wrap.appendChild(pre);
    return wrap;
  }

  function summarizeArgs(args) {
    if (!args) return "";
    for (const k of ["command","path","query","url","intent","description"]) {
      if (typeof args[k] === "string" && args[k]) return args[k];
    }
    const parts = [];
    for (const [k, v] of Object.entries(args)) {
      if (parts.length >= 3) break;
      if (typeof v === "string" && v.length < 60) parts.push(`${k}=${v}`);
      else if (["number","boolean"].includes(typeof v)) parts.push(`${k}=${v}`);
    }
    return parts.join(", ");
  }

  function shortTs(s) {
    if (!s) return "";
    const i = s.indexOf("T");
    if (i < 0) return s;
    return s.slice(i + 1).split(".")[0].replace("Z", "");
  }
  function fmtDate(s) {
    if (!s) return "";
    try {
      const d = new Date(s);
      if (isNaN(d.getTime())) return s;
      return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
    } catch (_) { return s; }
  }
  function formatDuration(ms) {
    if (ms < 1000) return ms + " ms";
    if (ms < 60_000) return (ms/1000).toFixed(1) + " s";
    const m = Math.floor(ms / 60000); const s = Math.round((ms % 60000) / 1000);
    return `${m}m ${s}s`;
  }
  function svgIcon(id) {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS(ns, "use");
    use.setAttribute("href", "#" + id);
    svg.appendChild(use);
    return svg;
  }
})();
</script>
</body>
</html>
"""
