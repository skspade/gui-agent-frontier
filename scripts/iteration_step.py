"""Iteration-loop decision logic. Pure functions exposed for unit testing;
CLI entry point at the bottom is invoked by iteration_loop.sh after each
claude --print call."""
from __future__ import annotations
import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _passes(doc: dict) -> set[str]:
    return {k for k, v in doc["tests"].items() if v["pass"]}


def _fails(doc: dict) -> set[str]:
    return {k for k, v in doc["tests"].items() if not v["pass"]}


def strict_improvement(before: dict, after: dict) -> bool:
    """Return True iff after's pass-set strictly contains before's, AND
    after's fail-set is a subset of before's fail-set (no new fails)."""
    pb, pa = _passes(before), _passes(after)
    fb, fa = _fails(before),  _fails(after)
    return pa > pb and fa.issubset(fb)


def format_suite_delta(before: dict, after: dict) -> str:
    keys = sorted(set(before["tests"]) | set(after["tests"]))
    lines = []
    for k in keys:
        b = before["tests"].get(k, {}).get("pass")
        a = after["tests"].get(k, {}).get("pass")
        bs = "pass" if b else ("fail" if b is False else "absent")
        as_ = "pass" if a else ("fail" if a is False else "absent")
        lines.append(f"  - {k}: {bs} → {as_}")
    return "\n".join(lines)


def render_learnings_block(
    *, iteration: int, verdict: str, hypothesis: str,
    change_files: list[str], suite_delta_text: str,
    outcome_line: str, invalidates: str | None,
) -> str:
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        f"## Iteration {iteration} — {ts} — {verdict}\n\n"
        f"**Hypothesis**: {hypothesis}\n"
        f"**Change**: {', '.join(change_files) if change_files else '(none)'}\n"
        f"**Suite delta**:\n{suite_delta_text}\n"
        f"**Outcome**: {outcome_line}\n"
        f"**Invalidates**: {invalidates or '(none)'}\n"
    )


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def _extract_inner(transcript: dict) -> dict:
    """The claude --print --output-format json envelope's `result` field is
    a JSON-encoded string of the model's final response. Some legacy stubs
    pass it as an already-decoded dict — accept both."""
    result_field = transcript.get("result")
    if isinstance(result_field, str):
        try:
            return json.loads(result_field)
        except json.JSONDecodeError:
            return {}
    if isinstance(result_field, dict):
        return result_field
    return {}


def _decide_and_act(*, iteration: int, before_path: Path, after_path: Path,
                    transcript_path: Path, learnings_path: Path,
                    workdir: Path) -> str:
    before = json.loads(before_path.read_text())
    after  = json.loads(after_path.read_text())
    transcript = json.loads(transcript_path.read_text()) if transcript_path.exists() else {}
    inner = _extract_inner(transcript)
    hypothesis = inner.get("hypothesis") or transcript.get("hypothesis") or "(not reported)"
    change_files = sorted(set(inner.get("change_files") or transcript.get("change_files") or []))

    delta = format_suite_delta(before, after)

    if after["all_green"] and not before["all_green"]:
        verdict = "GREEN"
    elif strict_improvement(before, after):
        verdict = "PARTIAL"
    elif _passes(after) == _passes(before) and _fails(after) == _fails(before):
        verdict = "NO-IMPROVEMENT"
    else:
        verdict = "REGRESSION"

    if verdict in ("GREEN", "PARTIAL"):
        # Scope git add to match the revert-clean scope below — keeps
        # IDE/watcher writes out of iteration commits during the race
        # window between add and commit.
        _git(["add", "scripts/", "tests/", "docs/", "prompts/"], workdir)
        msg = f"iter {iteration}: {hypothesis} [+suite {verdict.lower()}]"
        _git(["commit", "-m", msg], workdir)
        sha = _git(["rev-parse", "--short", "HEAD"], workdir)
        outcome_line = f"committed as `{sha}`"
    else:
        # Save the diff for forensic reference, then revert.
        diff_path = before_path.parent / f"iter_{iteration}.diff"
        diff_path.write_text(_git(["diff"], workdir))
        _git(["checkout", "--", "."], workdir)
        # Clean covers tests/, docs/, prompts/ in addition to scripts/ — the LLM
        # is restricted to scripts/* by the prompt + tool whitelist, but if it
        # escaped scope, untracked files in any of these dirs are LLM-authored
        # and should be removed. Out-of-scope dirs (data/, web/, .venv/) are
        # preserved.
        _git(["clean", "-fd", "scripts/", "tests/", "docs/", "prompts/"], workdir)
        outcome_line = f"reverted (verdict={verdict}); diff saved to {diff_path}"

    block = render_learnings_block(
        iteration=iteration, verdict=verdict, hypothesis=hypothesis,
        change_files=change_files, suite_delta_text=delta,
        outcome_line=outcome_line, invalidates=None,
    )
    learnings_path.parent.mkdir(parents=True, exist_ok=True)
    learnings_path.touch(exist_ok=True)
    with learnings_path.open("a") as f:
        f.write("\n" + block)
    return verdict


def _finalize_report(*, learnings_path: Path, report_path: Path) -> None:
    text = learnings_path.read_text() if learnings_path.exists() else "(no learnings)"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "# Harness Iteration Loop — Final Report\n\n"
        + f"Generated: {datetime.datetime.now(datetime.timezone.utc).isoformat()}\n\n"
        + "## Iteration log\n\n"
        + text + "\n"
    )


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    decide = sub.add_parser("decide")
    decide.add_argument("--iteration", type=int, required=True)
    decide.add_argument("--before", required=True)
    decide.add_argument("--after",  required=True)
    decide.add_argument("--transcript", required=True)
    decide.add_argument("--learnings", required=True)
    decide.add_argument("--workdir", required=True)
    final = sub.add_parser("finalize")
    final.add_argument("--learnings", required=True)
    final.add_argument("--report", required=True)
    args = p.parse_args()

    if args.cmd == "decide":
        verdict = _decide_and_act(
            iteration=args.iteration,
            before_path=Path(args.before),
            after_path=Path(args.after),
            transcript_path=Path(args.transcript),
            learnings_path=Path(args.learnings),
            workdir=Path(args.workdir),
        )
        sys.stdout.write(verdict + "\n")
    elif args.cmd == "finalize":
        _finalize_report(learnings_path=Path(args.learnings), report_path=Path(args.report))


if __name__ == "__main__":
    main()
