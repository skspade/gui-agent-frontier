"""Tests for sweep_orchestrator. Cover the fail-fast and patch behavior in
isolation — the actual model swap + custom_agent run aren't exercised
(those need a live llama-server)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.sweep_orchestrator as so


def test_ensure_task_exists_passes_for_real_task():
    so.ensure_task_exists("excalidraw_drag")  # must not raise


def test_ensure_task_exists_exits_for_bogus_task(capsys):
    with pytest.raises(SystemExit) as ei:
        so.ensure_task_exists("definitely_not_a_real_task")
    err = str(ei.value)
    assert "task module not found" in err
    assert "available tasks:" in err


def test_archive_and_patch_with_fresh_screenshot(tmp_path, monkeypatch):
    runs = tmp_path / "runs.jsonl"
    runs.write_text(json.dumps({"task": "t", "model": "m", "outcome": "done"}) + "\n")
    monkeypatch.setattr(so, "RUNS_JSONL", runs)

    fake_tmp = tmp_path / "fake_final.png"
    fake_tmp.write_bytes(b"\x89PNG\r\n" + b"\x00" * 100)
    monkeypatch.setattr(so, "TMP_FINAL", fake_tmp)

    run_dir = tmp_path / "run-1"
    run_dir.mkdir()

    so.archive_and_patch(
        run_dir, mtime_before=0, mtime_after=1,
        sweep_id="2026-05-01-test", target="local", quant=None,
    )

    archived = run_dir / "final.png"
    assert archived.is_file()
    row = json.loads(runs.read_text().splitlines()[-1])
    assert row["final_screenshot"] == str(archived)
    assert row["sweep_id"] == "2026-05-01-test"
    assert "thunder" not in row


def test_archive_and_patch_thunder_marker(tmp_path, monkeypatch):
    runs = tmp_path / "runs.jsonl"
    runs.write_text(json.dumps({"task": "t", "model": "m", "outcome": "done"}) + "\n")
    monkeypatch.setattr(so, "RUNS_JSONL", runs)

    fake_tmp = tmp_path / "fake_final.png"
    fake_tmp.write_bytes(b"\x89PNG\r\n" + b"\x00" * 100)
    monkeypatch.setattr(so, "TMP_FINAL", fake_tmp)

    run_dir = tmp_path / "run-1"
    run_dir.mkdir()

    so.archive_and_patch(
        run_dir, mtime_before=0, mtime_after=1,
        sweep_id="2026-05-01-test", target="thunder", quant="Q4_K_M",
    )

    row = json.loads(runs.read_text().splitlines()[-1])
    assert row["thunder"] is True
    assert row["quant"] == "Q4_K_M"


def test_archive_and_patch_skips_stale_screenshot(tmp_path, monkeypatch):
    runs = tmp_path / "runs.jsonl"
    runs.write_text(json.dumps({"task": "t", "model": "m", "outcome": "done"}) + "\n")
    monkeypatch.setattr(so, "RUNS_JSONL", runs)

    fake_tmp = tmp_path / "fake_final.png"
    fake_tmp.write_bytes(b"\x89PNG\r\n")
    monkeypatch.setattr(so, "TMP_FINAL", fake_tmp)

    run_dir = tmp_path / "run-1"
    run_dir.mkdir()

    # mtime_after == mtime_before → stale, screenshot must NOT be archived
    so.archive_and_patch(
        run_dir, mtime_before=100, mtime_after=100,
        sweep_id="2026-05-01-test", target="local", quant=None,
    )

    assert not (run_dir / "final.png").is_file()
    row = json.loads(runs.read_text().splitlines()[-1])
    assert "final_screenshot" not in row or not row["final_screenshot"].endswith("final.png")


def test_archive_and_patch_empty_runs_jsonl_is_noop(tmp_path, monkeypatch):
    runs = tmp_path / "runs.jsonl"
    runs.write_text("")
    monkeypatch.setattr(so, "RUNS_JSONL", runs)
    monkeypatch.setattr(so, "TMP_FINAL", tmp_path / "nonexistent.png")
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    so.archive_and_patch(run_dir, 0, 0, "sid", "local", None)
    assert runs.read_text() == ""
