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
    # The real screenshot must live outside /tmp/ — resolve_screenshots
    # treats /tmp/* as ephemeral, and pytest's tmp_path is itself under
    # /tmp on this system.
    import tempfile as _tempfile
    with _tempfile.TemporaryDirectory(dir=Path.home()) as shot_dir:
        real = Path(shot_dir) / "shot.png"
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


def test_resolve_screenshots_treats_tmp_paths_as_ephemeral(tmp_path):
    """Even if /tmp/foo.png exists on disk, treat it as ephemeral and prefer sweep_index."""
    tmp_shot = tmp_path / "tmp_real.png"
    tmp_shot.write_bytes(b"png")
    sweep_shot = tmp_path / "sweep.png"
    sweep_shot.write_bytes(b"png")

    cell = {"runs": [
        {"model": "m", "task": "t", "ts": "2026-05-01T00:00",
         # Note: this points to a real file at a /tmp-prefixed path.
         # The resolver should still skip it because /tmp paths are ephemeral.
         "final_screenshot": "/tmp/anything.png"},
    ]}
    sweep_index = {("m", "t"): [("2026-05-01T00:00", str(sweep_shot))]}
    resolved = resolve_screenshots(cell, sweep_index=sweep_index)
    assert resolved[0]["src_path"] == str(sweep_shot)


def test_build_sweep_index_sorts_entries_by_sweep_ts(tmp_path):
    """Per-(model, task) entries are sorted chronologically by sweep_ts."""
    import json
    for sweep_id in ["20260501-002", "20260501-001"]:  # written out of order
        sweep_dir = tmp_path / sweep_id / "ui-venus-1.5-8b_Q6_K" / "run-1"
        sweep_dir.mkdir(parents=True)
        (sweep_dir / "final.png").write_bytes(b"png")
        (tmp_path / sweep_id / "summary.json").write_text(json.dumps({
            "task": "t1",
            "results": [{
                "model": "ui-venus-1.5-8b",
                "screenshot_path": str(sweep_dir / "final.png"),
            }],
        }))
    index = build_sweep_index(tmp_path)
    timestamps = [ts for ts, _ in index[("ui-venus-1.5-8b", "t1")]]
    assert timestamps == sorted(timestamps), "entries must be in chronological order"
