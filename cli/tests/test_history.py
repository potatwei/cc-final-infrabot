import json

from infrapilot import history


def test_record_appends(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_FILE", tmp_path / "h.jsonl")
    history.record("t1", "do thing", "pending")
    history.record("t2", "do another", "complete")
    rows = (tmp_path / "h.jsonl").read_text().splitlines()
    assert len(rows) == 2
    assert json.loads(rows[0])["task_id"] == "t1"
    assert json.loads(rows[1])["status"] == "complete"


def test_recent_returns_tail(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_FILE", tmp_path / "h.jsonl")
    for i in range(5):
        history.record(f"t{i}", f"prompt {i}", "pending")
    out = history.recent(limit=3)
    assert [e["task_id"] for e in out] == ["t2", "t3", "t4"]


def test_update_merges_into_latest(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_FILE", tmp_path / "h.jsonl")
    history.record("t1", "prompt", "pending")
    history.record("t1", "prompt-resubmitted", "pending")
    history.record("t2", "another", "pending")
    assert history.update("t1", apply_status="deployed", run_dir="/tmp/x") is True
    rows = [json.loads(l) for l in (tmp_path / "h.jsonl").read_text().splitlines()]
    # Only the last t1 entry got the merged fields
    t1_entries = [r for r in rows if r["task_id"] == "t1"]
    assert "apply_status" not in t1_entries[0]
    assert t1_entries[1]["apply_status"] == "deployed"
    assert t1_entries[1]["run_dir"] == "/tmp/x"


def test_update_unknown_id_returns_false(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "HISTORY_FILE", tmp_path / "h.jsonl")
    history.record("t1", "x", "ok")
    assert history.update("nope", apply_status="deployed") is False
