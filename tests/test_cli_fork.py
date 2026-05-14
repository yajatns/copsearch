"""Tests for `copsearch fork` CLI subcommand."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]


def _run(args: list[str], env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Invoke the copsearch CLI in a subprocess with HOME redirected to a tmp dir.

    On Windows, ``Path.home()`` reads ``USERPROFILE`` (not ``HOME``), so when
    callers redirect ``HOME`` we mirror it to ``USERPROFILE`` as well.
    """
    import os
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
        if "HOME" in env_extra and "USERPROFILE" not in env_extra:
            env["USERPROFILE"] = env_extra["HOME"]
    return subprocess.run(
        [sys.executable, "-m", "copsearch.cli", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO),
    )


def _make_session(home: Path, sid: str, **ws_extra) -> Path:
    sdir = home / ".copilot" / "session-state" / sid
    sdir.mkdir(parents=True)
    ws = {"id": sid, "cwd": str(home), "branch": "main",
          "created_at": "2026-04-01T10:00:00Z",
          "updated_at": "2026-04-01T11:00:00Z",
          "name": "Original", "user_named": True}
    ws.update(ws_extra)
    (sdir / "workspace.yaml").write_text(yaml.dump(ws))
    (sdir / "events.jsonl").write_text(
        '{"type": "user.message", "id": "ev-1"}\n'
    )
    return sdir


def test_fork_subcommand_prints_new_id(tmp_path: Path):
    sid = "33333333-3333-3333-3333-333333333333"
    _make_session(tmp_path, sid)

    result = _run(["fork", sid[:8], "--json"], env_extra={"HOME": str(tmp_path)})
    assert result.returncode == 0, result.stderr

    out = json.loads(result.stdout)
    assert out["source_id"] == sid
    assert out["new_id"] != sid
    # Default: throw-away (no --keep, no --name).
    assert out["throwaway"] is True
    # New session dir exists.
    new_dir = tmp_path / ".copilot" / "session-state" / out["new_id"]
    assert new_dir.exists()


def test_fork_subcommand_keep_flag(tmp_path: Path):
    sid = "44444444-4444-4444-4444-444444444444"
    _make_session(tmp_path, sid)

    result = _run(
        ["fork", sid[:8], "--keep", "--json"], env_extra={"HOME": str(tmp_path)}
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["throwaway"] is False


def test_fork_subcommand_name_implies_keep(tmp_path: Path):
    sid = "55555555-5555-5555-5555-555555555555"
    _make_session(tmp_path, sid)

    result = _run(
        ["fork", sid[:8], "--name", "My fork", "--json"],
        env_extra={"HOME": str(tmp_path)},
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["throwaway"] is False
    assert out["name"] == "My fork"

    new_ws = yaml.safe_load(
        (tmp_path / ".copilot" / "session-state" / out["new_id"] / "workspace.yaml").read_text()
    )
    assert new_ws["name"] == "My fork"


def test_fork_subcommand_throwaway_overrides_name(tmp_path: Path):
    sid = "66666666-6666-6666-6666-666666666666"
    _make_session(tmp_path, sid)

    result = _run(
        ["fork", sid[:8], "--name", "Risky", "--throwaway", "--json"],
        env_extra={"HOME": str(tmp_path)},
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["throwaway"] is True


def test_fork_subcommand_unknown_id(tmp_path: Path):
    result = _run(["fork", "no-such-prefix"], env_extra={"HOME": str(tmp_path)})
    assert result.returncode != 0
    assert "No session" in result.stderr or "No sessions" in result.stderr


def test_throwaway_filter_legacy_flag(tmp_path: Path):
    keep_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    toss_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    _make_session(tmp_path, keep_id)
    _make_session(tmp_path, toss_id, throwaway=True)

    # Default: both shown.
    result = _run(["--list"], env_extra={"HOME": str(tmp_path)})
    assert result.returncode == 0
    assert "2 session" in result.stdout

    # --throwaway: only the toss one.
    result = _run(["--throwaway"], env_extra={"HOME": str(tmp_path)})
    assert result.returncode == 0
    assert "1 session" in result.stdout
