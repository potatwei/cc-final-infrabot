from pathlib import Path

import pytest

from infrapilot import runs


def test_prepare_writes_files(tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path / "runs")
    files = [
        {"path": "main.tf", "content": "resource \"x\" \"y\" {}"},
        {"path": "infra/sub.tf", "content": "# nested"},
    ]
    out = runs.prepare("task-abc", files)
    assert out == tmp_path / "runs" / "task-abc"
    assert (out / "main.tf").read_text() == 'resource "x" "y" {}'
    assert (out / "infra" / "sub.tf").read_text() == "# nested"


def test_prepare_overwrites_tf_but_preserves_state(tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path / "runs")
    runs.prepare("t1", [{"path": "main.tf", "content": "v1"}])
    state = tmp_path / "runs" / "t1" / "terraform.tfstate"
    state.write_text("STATE")
    runs.prepare("t1", [{"path": "main.tf", "content": "v2"}])
    assert (tmp_path / "runs" / "t1" / "main.tf").read_text() == "v2"
    assert state.read_text() == "STATE"


def test_existing_returns_dir_or_none(tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path / "runs")
    assert runs.existing("nope") is None
    runs.prepare("t2", [{"path": "main.tf", "content": ""}])
    assert runs.existing("t2") == tmp_path / "runs" / "t2"


def test_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path / "runs")
    runs.prepare("t3", [{"path": "main.tf", "content": ""}])
    assert runs.delete("t3") is True
    assert runs.delete("t3") is False
    assert runs.existing("t3") is None


def test_prepare_requires_task_id():
    with pytest.raises(ValueError):
        runs.prepare("", [])


def test_prepare_skips_empty_path(tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "RUNS_DIR", tmp_path / "runs")
    out = runs.prepare("t4", [{"path": "", "content": "ignored"}, {"path": "ok.tf", "content": "v"}])
    assert (out / "ok.tf").read_text() == "v"
    assert list(out.iterdir()) == [out / "ok.tf"]
