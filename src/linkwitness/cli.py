from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ._io import load_json, preflight_output, write_new_text
from .core import analyze, render_json, render_markdown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a deterministic, reviewable report from explicit JSON input."
    )
    parser.add_argument("input", type=Path, help="UTF-8 JSON input file")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.output:
            preflight_output(args.output)
        data = load_json(args.input)
        report = analyze(data)
        rendered = render_json(report) if args.format == "json" else render_markdown(report)
        if args.output:
            write_new_text(args.output, rendered)
        else:
            sys.stdout.write(rendered)
    except (OSError, UnicodeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0
