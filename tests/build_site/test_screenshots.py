"""Tests for screenshot resolution."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from build_site import build_sweep_index, resolve_screenshots  # noqa: E402


def test_build_sweep_index_groups_by_model_and_task(tmp_path):
    sweep = tmp_path / "20260501-001" / "ui-venus-1.5-8b_Q6_K" / "run-1"
    sweep.mkdir(parents=True)
    (sweep / "final.png").write_bytes(b"png")
    summary = tmp_path / "20260501-001" / "summary.json"
    summary.write_text(json.dumps({
        "task": "saucedemo_full_checkout",
        "results": [{
            "model": "ui-venus-1.5-8b",
            "quant": "Q6_K",
            "run_index": 1,
            "screenshot_path": str(sweep / "final.png"),
            "duration_s": 12.0,
        }],
    }))
    index = build_sweep_index(tmp_path)
    assert ("ui-venus-1.5-8b", "saucedemo_full_checkout") in index
    paths = [p for _, p in index[("ui-venus-1.5-8b", "saucedemo_full_checkout")]]
    assert paths == [str(sweep / "final.png")]


def test_resolve_screenshots_uses_runs_jsonl_path_when_real(tmp_path):
    real = tmp_path / "shot.png"
    real.write_bytes(b"png")
    cell = {"runs": [
        {"model": "m", "task": "t", "ts": "2026-05-01T00:00",
         "final_screenshot": str(real)},
    ]}
    resolved = resolve_screenshots(cell, sweep_index={})
    assert resolved[0]["src_path"] == str(real)


def test_resolve_screenshots_skips_missing_tmp_paths(tmp_path):
    cell = {"runs": [
        {"model": "m", "task": "t", "ts": "2026-05-01T00:00",
         "final_screenshot": "/tmp/does_not_exist.png"},
    ]}
    resolved = resolve_screenshots(cell, sweep_index={})
    assert resolved[0]["src_path"] is None


def test_resolve_screenshots_falls_back_to_sweep_index(tmp_path):
    sweep_shot = tmp_path / "sweep.png"
    sweep_shot.write_bytes(b"png")
    cell = {"runs": [
        {"model": "m", "task": "t", "ts": "2026-05-01T00:00",
         "final_screenshot": "/tmp/gone.png"},
    ]}
    sweep_index = {("m", "t"): [("2026-05-01T00:00", str(sweep_shot))]}
    resolved = resolve_screenshots(cell, sweep_index=sweep_index)
    assert resolved[0]["src_path"] == str(sweep_shot)
