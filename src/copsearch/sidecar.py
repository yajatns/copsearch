"""Per-session copsearch metadata stored alongside Copilot's session files.

Why this exists
---------------
Copilot CLI rewrites :file:`workspace.yaml` whenever it touches a session,
preserving only the keys it knows about. Any custom fields we add (such as
``forked_from`` or ``throwaway``) are silently dropped on the next save.

To keep our metadata durable, we write it to a sibling JSON file
:file:`.copsearch.json` in the session directory. Copilot ignores unknown
files, so the sidecar survives every Copilot save.

The sidecar is the source of truth for fork provenance and the throw-away
flag. workspace.yaml may still carry these fields for newly-created forks
(before Copilot first rewrites it) — :func:`read_sidecar` is the only place
that should be queried for the canonical values.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SIDECAR_NAME = ".copsearch.json"
SCHEMA_VERSION = 1


def sidecar_path(session_dir: Path) -> Path:
    """Return the path to the sidecar file for a session directory."""
    return session_dir / SIDECAR_NAME


def read_sidecar(session_dir: Path) -> dict[str, Any]:
    """Load the sidecar for ``session_dir``. Returns ``{}`` when missing/invalid."""
    p = sidecar_path(session_dir)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def write_sidecar(session_dir: Path, data: dict[str, Any]) -> bool:
    """Write the sidecar atomically. Returns True on success."""
    p = sidecar_path(session_dir)
    payload = dict(data)
    payload.setdefault("schema", SCHEMA_VERSION)
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(p)
        return True
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False


def update_sidecar(session_dir: Path, **fields: Any) -> bool:
    """Merge ``fields`` into the sidecar, preserving other keys.

    Pass ``None`` for a field to remove it from the sidecar.
    """
    data = read_sidecar(session_dir)
    for k, v in fields.items():
        if v is None:
            data.pop(k, None)
        else:
            data[k] = v
    return write_sidecar(session_dir, data)
