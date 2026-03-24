#!/usr/bin/env python3
"""
ingest_project.py — The Distillery MVP Pipeline (CLI)

Usage:
    python scripts/ingest_project.py --project projects/example_project
"""

import argparse
import sys
from pathlib import Path

from scripts.distillery_engine import DistilleryError, run_pipeline


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="The Distillery — local knowledge distillation pipeline MVP"
    )
    parser.add_argument(
        "--project",
        required=True,
        help="Path to the project folder (e.g. projects/example_project)",
    )
    parser.add_argument(
        "--chunk-words",
        type=int,
        default=400,
        help="Approximate max words per chunk (default: 400)",
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help="Enable OpenAI-compatible LLM synthesis for summary.md",
    )
    parser.add_argument(
        "--llm-model",
        default="gpt-4o-mini",
        help="LLM model name used with --llm (default: gpt-4o-mini)",
    )
    args = parser.parse_args()

    project_dir = Path(args.project).resolve()
    if args.chunk_words < 50:
        print("ERROR: --chunk-words must be >= 50")
        sys.exit(1)
    try:
        run_pipeline(
            project_dir=project_dir,
            chunk_words=args.chunk_words,
            use_llm=args.llm,
            llm_model=args.llm_model,
            progress_cb=lambda m: print(m),
        )
    except DistilleryError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
