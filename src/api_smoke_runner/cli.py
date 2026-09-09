"""Command-line adapter for api-smoke-runner.

File I/O and rendering stay here; request behavior is documented in
``docs/architecture-overview.md`` and implemented in ``core.py``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from .core import ConfigError, SuiteResult, load_cases, run_suite


def build_parser() -> argparse.ArgumentParser:
    """Build the public command-line argument parser."""

    parser = argparse.ArgumentParser(description="Run an HTTP API smoke suite from a JSON collection.")
    parser.add_argument("collection", type=Path, help="path to the JSON collection")
    parser.add_argument("--json", action="store_true", dest="as_json", help="emit a machine-readable JSON report")
    return parser


def render_text(result: SuiteResult) -> str:
    """Render suite counts and per-case failures without request secrets."""

    payload = result.to_dict()
    lines = [f"Requests: {payload['total']} | passed: {payload['passed']} | failed: {payload['failed']}"]
    for case in result.cases:
        status = case.status if case.status is not None else "no response"
        lines.append(f"{'PASS' if case.ok else 'FAIL'} {case.name} ({status}, {case.duration_ms} ms)")
        lines.extend(f"  - {failure}" for failure in case.failures)
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return ``0`` passed, ``1`` failed, or ``2`` config/I/O errors."""

    args = build_parser().parse_args(argv)
    try:
        with args.collection.open("r", encoding="utf-8") as source:
            payload = json.load(source)
        if not isinstance(payload, dict):
            raise ConfigError("collection root must be a JSON object")
        result = run_suite(load_cases(payload))
    except (OSError, UnicodeError, json.JSONDecodeError, ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(render_text(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
