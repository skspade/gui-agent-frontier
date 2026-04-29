"""Custom CDP agent runner — pairs UI-Venus with Chromium directly.

See docs/plans/2026-04-28-s1-custom-cdp-client-design.md for the design.
Stub — implementation lands in Task 7.
"""
from __future__ import annotations
import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", help="module name in scripts/custom_agent_tasks/")
    args = parser.parse_args()
    print(f"custom_agent: would run task {args.task!r} (not yet implemented)", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
