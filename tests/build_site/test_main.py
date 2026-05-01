"""End-to-end smoke test: run main against synthetic inputs, check the
html artifact contains the embedded payload."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import build_site  # noqa: E402


def test_main_writes_index_with_embedded_payload(tmp_path):
    repo = tmp_path
    (repo / "data").mkdir()
    (repo / "data" / "sweeps").mkdir()
    (repo / "web").mkdir()

    # Minimal config
    (repo / "web" / "config.yaml").write_text(
        "intro: hello\n"
        "class_labels: {B: 'long horizon'}\n"
        "models:\n"
        "  - {id: m1, label: 'M1', params: '8B'}\n"
        "tests:\n"
        "  B:\n"
        "    - {id: t1, label: 'T1', desc: 'test 1'}\n"
    )

    # One run with a real screenshot. The path must not be under /tmp/
    # (build_site.resolve_screenshots treats /tmp/* as ephemeral, so we
    # place the file outside pytest's default tmp_path which is itself
    # under /tmp on this system).
    import tempfile as _tempfile
    with _tempfile.TemporaryDirectory(dir=Path.home()) as shot_dir:
        shot = Path(shot_dir) / "shot.png"
        shot.write_bytes(b"png-bytes")
        (repo / "data" / "runs.jsonl").write_text(json.dumps({
            "task": "t1", "task_class": "B", "model": "m1",
            "harness": "uivenus", "outcome": "done", "category": "pass",
            "steps": 5, "elapsed_s": 10.0, "ts": "2026-05-01T00:00:00",
            "final_screenshot": str(shot),
        }) + "\n")

        build_site.main(repo_root=repo)

        html = (repo / "web" / "index.html").read_text()
        assert '<script type="application/json" id="app-data">' in html

        start = html.index('id="app-data">') + len('id="app-data">')
        end = html.index("</script>", start)
        payload = json.loads(html[start:end])
        assert payload["intro"] == "hello"
        assert payload["models"][0]["id"] == "m1"
        assert len(payload["cells"]) == 1
        cell = payload["cells"][0]
        assert (cell["model"], cell["test"]) == ("m1", "t1")
        assert cell["k"] == 1 and cell["n"] == 1
        assert cell["runs"][0]["screenshot"].startswith("screenshots/m1/t1/")

        copied = repo / "web" / cell["runs"][0]["screenshot"]
        assert copied.is_file()
        assert copied.read_bytes() == b"png-bytes"


def test_main_escapes_lt_in_payload(tmp_path):
    """A '</script>' substring in payload data must not break the inline JSON."""
    repo = tmp_path
    (repo / "data").mkdir()
    (repo / "data" / "sweeps").mkdir()
    (repo / "web").mkdir()
    (repo / "web" / "config.yaml").write_text(
        "intro: 'evil </script><script>alert(1)</script>'\n"
        "class_labels: {B: 'b'}\n"
        "models:\n  - {id: m1, label: 'M1', params: '8B'}\n"
        "tests:\n  B:\n    - {id: t1, label: 'T1', desc: 'd'}\n"
    )
    (repo / "data" / "runs.jsonl").write_text("")

    build_site.main(repo_root=repo)

    html = (repo / "web" / "index.html").read_text()
    # The literal `</script>` substring should NOT appear inside the embedded JSON
    # tag — it should be escaped as </script>.
    start = html.index('id="app-data">') + len('id="app-data">')
    end = html.index("</script>", start)  # the *closing* tag
    embedded = html[start:end]
    assert "</script>" not in embedded
    assert "\\u003c/script>" in embedded

    # And the JSON still parses cleanly with the original content recoverable.
    import json as _json
    payload = _json.loads(embedded)
    assert "</script>" in payload["intro"]


def test_main_emits_pass_field_consistent_with_python_aggregator(tmp_path):
    """The per-run `pass` field in the payload must use the same fallback as
    the Python aggregator (category=None + outcome='call_user' counts as pass)."""
    import json as _json
    repo = tmp_path
    (repo / "data").mkdir()
    (repo / "data" / "sweeps").mkdir()
    (repo / "web").mkdir()
    (repo / "web" / "config.yaml").write_text(
        "intro: x\n"
        "class_labels: {B: b}\n"
        "models:\n  - {id: m1, label: M1, params: 8B}\n"
        "tests:\n  B:\n    - {id: t1, label: T1, desc: d}\n"
    )
    # Legacy row with category=None and outcome=call_user — should be a pass.
    (repo / "data" / "runs.jsonl").write_text(_json.dumps({
        "task": "t1", "model": "m1", "outcome": "call_user", "category": None,
        "harness": "h", "ts": "2026-05-01T00:00",
    }) + "\n")

    build_site.main(repo_root=repo)

    html = (repo / "web" / "index.html").read_text()
    start = html.index('id="app-data">') + len('id="app-data">')
    end = html.index("</script>", start)
    payload = _json.loads(html[start:end])
    cell = payload["cells"][0]
    assert cell["k"] == 1 and cell["n"] == 1
    assert cell["runs"][0]["pass"] is True
    # Display label is preserved separately.
    assert cell["runs"][0]["outcome"] == "call_user"
