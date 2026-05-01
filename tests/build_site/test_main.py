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

    # One run with a real screenshot
    shot = repo / "data" / "shot.png"
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
