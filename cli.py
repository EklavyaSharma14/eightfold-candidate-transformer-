#!/usr/bin/env python3
"""
Thin CLI surface for the candidate data transformer.

Usage:
    python cli.py run --manifest data/manifest.json [--config configs/recruiter_lite.json] [--out outputs/result.json] [--pretty]

Run with no --config to get the default output schema.
"""
import argparse
import json
import sys

sys.path.insert(0, "src")
from transformer.pipeline import run_pipeline  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Eightfold multi-source candidate data transformer")
    sub = parser.add_subparsers(dest="command", required=True)

    run_cmd = sub.add_parser("run", help="run the pipeline over a manifest")
    run_cmd.add_argument("--manifest", required=True, help="path to manifest.json")
    run_cmd.add_argument("--config", default=None, help="path to a custom output config (omit for default schema)")
    run_cmd.add_argument("--out", default=None, help="write JSON output to this path (else prints to stdout)")
    run_cmd.add_argument("--pretty", action="store_true", help="pretty-print JSON")

    args = parser.parse_args()

    if args.command == "run":
        result = run_pipeline(args.manifest, args.config)
        text = json.dumps(result, indent=2 if args.pretty else None)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"Wrote {len(result['results'])} candidate profile(s) to {args.out}")
            if result["run_errors"]:
                print(f"{len(result['run_errors'])} run-level issue(s):", file=sys.stderr)
                for e in result["run_errors"]:
                    print(f"  - {e}", file=sys.stderr)
        else:
            print(text)


if __name__ == "__main__":
    main()
