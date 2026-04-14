"""Tests for session filtering."""

from pathlib import Path

import yaml

from copsearch.filters import filter_sessions
from copsearch.session import load_sessions


def _make_session_dir(tmp_path: Path, session_id: str, **kwargs) -> Path:
    d = tmp_path / session_id
    d.mkdir()
    (d / "checkpoints").mkdir()
    (d / "files").mkdir()
    data = {
        "id": session_id,
        "cwd": str(tmp_path / kwargs.get("project_name", "project")),
        "summary_count": 0,
        "created_at": "2026-04-10T10:00:00Z",
        "updated_at": "2026-04-10T12:00:00Z",
        **{k: v for k, v in kwargs.items() if k != "project_name"},
    }
    (d / "workspace.yaml").write_text(yaml.dump(data))
    if "plan_text" in kwargs:
        (d / "plan.md").write_text(kwargs["plan_text"])
    return d


def test_filter_by_project(tmp_path: Path):
    _make_session_dir(tmp_path, "s1", cwd="/a/Integration")
    _make_session_dir(tmp_path, "s2", cwd="/a/FunTools")
    _make_session_dir(tmp_path, "s3", cwd="/a/Integration")

    sessions = load_sessions(tmp_path)
    result = filter_sessions(sessions, project="Integration")
    assert len(result) == 2
    assert all("Integration" in s.cwd for s in result)


def test_filter_by_branch_glob(tmp_path: Path):
    _make_session_dir(tmp_path, "s1", branch="yaj/feature-a")
    _make_session_dir(tmp_path, "s2", branch="main")
    _make_session_dir(tmp_path, "s3", branch="yaj/feature-b")

    sessions = load_sessions(tmp_path)
    result = filter_sessions(sessions, branch="yaj/*")
    assert len(result) == 2
    assert all(s.branch.startswith("yaj/") for s in result)


def test_filter_by_since(tmp_path: Path):
    _make_session_dir(tmp_path, "old", updated_at="2020-01-01T00:00:00Z")
    _make_session_dir(tmp_path, "new", updated_at="2026-04-10T00:00:00Z")

    sessions = load_sessions(tmp_path)
    result = filter_sessions(sessions, since="2026-01-01")
    assert len(result) == 1
    assert result[0].id == "new"


def test_filter_by_query(tmp_path: Path):
    _make_session_dir(tmp_path, "s1", summary="RSS throughput test")
    _make_session_dir(tmp_path, "s2", summary="DPC CLI improvements")
    _make_session_dir(tmp_path, "s3", summary="funeth RSS hash fix")

    sessions = load_sessions(tmp_path)
    result = filter_sessions(sessions, query="RSS")
    assert len(result) == 2


def test_filter_combined(tmp_path: Path):
    _make_session_dir(tmp_path, "s1", cwd="/a/Integration", branch="yaj/rss", summary="RSS test")
    _make_session_dir(tmp_path, "s2", cwd="/a/Integration", branch="main", summary="other")
    _make_session_dir(tmp_path, "s3", cwd="/a/FunTools", branch="yaj/rss", summary="RSS fix")

    sessions = load_sessions(tmp_path)
    result = filter_sessions(sessions, project="Integration", branch="yaj/*", query="RSS")
    assert len(result) == 1
    assert result[0].id == "s1"


def test_filter_empty_returns_all(tmp_path: Path):
    _make_session_dir(tmp_path, "s1")
    _make_session_dir(tmp_path, "s2")

    sessions = load_sessions(tmp_path)
    result = filter_sessions(sessions)
    assert len(result) == 2


def test_query_searches_plan_text(tmp_path: Path):
    _make_session_dir(
        tmp_path, "s1", summary="Some session", plan_text="# Fix WHLK certification"
    )
    _make_session_dir(tmp_path, "s2", summary="Other session")

    sessions = load_sessions(tmp_path)
    result = filter_sessions(sessions, query="WHLK")
    assert len(result) == 1
    assert result[0].id == "s1"
