#!/usr/bin/env python3
"""
ingest_project.py — The Distillery MVP Pipeline

Processes a project folder containing raw files (txt, md, pdf) and produces:
  - processed/extracted_text.json
  - processed/cleaned_text.json
  - output/project.json
  - output/chunks.jsonl
  - output/summary.md

Usage:
    python scripts/ingest_project.py --project projects/example_project
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_pypdf():
    """Import pypdf lazily and raise a helpful error if it is not installed."""
    try:
        from pypdf import PdfReader  # noqa: C0415
        return PdfReader
    except ImportError:
        print(
            "ERROR: 'pypdf' is not installed. "
            "Run:  pip install pypdf"
        )
        sys.exit(1)


def _infer_source_type(filename: str) -> str:
    """Return a source-type label based on keywords in the filename."""
    name = filename.lower()
    if "transcript" in name:
        return "transcript"
    if "workbook" in name:
        return "workbook"
    if "platform" in name:
        return "platform_text"
    if "notes" in name:
        return "notes"
    if "reading" in name or "slides" in name:
        return "pdf_reference"
    return "unknown"


def _make_source_id(filename: str) -> str:
    """Return a slug-style identifier derived from the filename."""
    stem = Path(filename).stem
    return re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_")


# ---------------------------------------------------------------------------
# Step 1 — Extraction
# ---------------------------------------------------------------------------

def extract_text(raw_dir: Path, project_id: str) -> dict:
    """
    Scan *raw_dir* for .txt, .md, and .pdf files.
    Return a dict matching the extracted_text.json schema.
    """
    supported = {".txt", ".md", ".pdf"}
    sources = []

    files = sorted(raw_dir.iterdir())
    if not files:
        print("  WARNING: No files found in raw directory.")

    for filepath in files:
        if filepath.suffix.lower() not in supported:
            print(f"  SKIP: {filepath.name} (unsupported extension)")
            continue

        print(f"  Extracting: {filepath.name}")
        raw_text = _read_file(filepath)

        sources.append({
            "source_id": _make_source_id(filepath.name),
            "filename": filepath.name,
            "source_type": _infer_source_type(filepath.name),
            "raw_text": raw_text,
        })

    return {"project_id": project_id, "sources": sources}


def _read_file(filepath: Path) -> str:
    """Read a file and return its text content."""
    suffix = filepath.suffix.lower()
    if suffix in {".txt", ".md"}:
        return filepath.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        return _read_pdf(filepath)
    return ""


def _read_pdf(filepath: Path) -> str:
    """Extract text from a PDF using pypdf."""
    PdfReader = _load_pypdf()
    try:
        reader = PdfReader(str(filepath))
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return "\n".join(pages)
    except Exception as exc:
        print(f"  WARNING: Could not read PDF '{filepath.name}': {exc}")
        return ""


# ---------------------------------------------------------------------------
# Step 2 — Cleaning
# ---------------------------------------------------------------------------

def clean_text(extracted: dict) -> dict:
    """
    Produce a cleaned version of each source's raw text.
    Keeps raw_text unchanged; adds clean_text field.
    """
    cleaned_sources = []
    for source in extracted["sources"]:
        clean = _normalise(source["raw_text"])
        cleaned_sources.append({**source, "clean_text": clean})

    return {"project_id": extracted["project_id"], "sources": cleaned_sources}


def _normalise(text: str) -> str:
    """
    Normalise whitespace and remove excessive blank lines.
    - Collapse runs of spaces/tabs to a single space per line.
    - Collapse more than two consecutive newlines to two.
    - Strip leading/trailing whitespace.
    """
    # Normalise horizontal whitespace on each line
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    # Reassemble then collapse runs of blank lines
    joined = "\n".join(lines)
    joined = re.sub(r"\n{3,}", "\n\n", joined)
    return joined.strip()


# ---------------------------------------------------------------------------
# Step 3 — Project JSON
# ---------------------------------------------------------------------------

def build_project_json(project_dir: Path, cleaned: dict) -> dict:
    """
    Assemble the project.json structure, loading project_context.md and
    use_intent.json when present.
    """
    project_context = _load_text_file(project_dir / "project_context.md")
    use_intent = _load_json_file(project_dir / "use_intent.json")

    # Build lightweight source items (no raw text to keep the file lean)
    source_items = [
        {
            "source_id": s["source_id"],
            "filename": s["filename"],
            "source_type": s["source_type"],
            "char_count": len(s["raw_text"]),
        }
        for s in cleaned["sources"]
    ]

    return {
        "project_id": cleaned["project_id"],
        "project_context": project_context,
        "use_intent": use_intent,
        "source_items": source_items,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _load_text_file(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    print(f"  INFO: {path.name} not found — skipping.")
    return ""


def _load_json_file(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"  WARNING: Could not parse {path.name}: {exc}")
    else:
        print(f"  INFO: {path.name} not found — skipping.")
    return {}


# ---------------------------------------------------------------------------
# Step 4 — Chunking
# ---------------------------------------------------------------------------

def chunk_text(cleaned: dict, chunk_words: int = 400) -> list:
    """
    Split each source's clean_text into chunks of ~*chunk_words* words.
    Returns a list of chunk dicts ready for JSONL serialisation.
    """
    chunks = []
    chunk_index = 0

    for source in cleaned["sources"]:
        source_chunks = _split_into_chunks(
            text=source["clean_text"],
            chunk_words=chunk_words,
        )
        for chunk_text_part in source_chunks:
            chunks.append({
                "chunk_id": f"chunk_{chunk_index:04d}",
                "project_id": cleaned["project_id"],
                "source_id": source["source_id"],
                "text": chunk_text_part,
                "tags": [],
            })
            chunk_index += 1

    return chunks


def _split_into_chunks(text: str, chunk_words: int) -> list:
    """Split *text* into chunks of approximately *chunk_words* words.

    Uses simple whitespace tokenisation suitable for the MVP. Intra-word
    formatting (e.g. multiple spaces) is already normalised by the cleaning
    step before chunking, so this approach is appropriate for cleaned text.
    """
    words = text.split()
    if not words:
        return []

    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_words
        chunks.append(" ".join(words[start:end]))
        start = end

    return chunks


# ---------------------------------------------------------------------------
# Step 5 — Summary
# ---------------------------------------------------------------------------

def build_summary(extracted: dict, project_dir: Path) -> str:
    """
    Generate a human-readable Markdown summary of the project.
    """
    sources = extracted["sources"]
    project_id = extracted["project_id"]

    type_counts: dict[str, int] = {}
    total_chars = 0
    for s in sources:
        type_counts[s["source_type"]] = type_counts.get(s["source_type"], 0) + 1
        total_chars += len(s["raw_text"])

    lines = [
        f"# Summary — {project_id}",
        "",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "## Overview",
        "",
        f"- **Number of sources:** {len(sources)}",
        f"- **Total text size:** {total_chars:,} characters",
        "",
        "## Source Types",
        "",
    ]

    for stype, count in sorted(type_counts.items()):
        lines.append(f"- `{stype}`: {count} source(s)")

    lines += [
        "",
        "## Source Previews",
        "",
    ]

    for s in sources:
        preview = s["raw_text"][:500].replace("\n", " ").strip()
        if len(s["raw_text"]) > 500:
            preview += "…"
        lines += [
            f"### {s['filename']} (`{s['source_type']}`)",
            "",
            preview,
            "",
        ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Wrote: {path}")


def _write_jsonl(path: Path, records: list) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"  Wrote: {path}")


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    print(f"  Wrote: {path}")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_pipeline(project_dir: Path) -> None:
    """Execute all five pipeline stages for the given project directory."""

    # Validate project directory
    if not project_dir.exists():
        print(f"ERROR: Project directory not found: {project_dir}")
        sys.exit(1)

    raw_dir = project_dir / "raw"
    if not raw_dir.exists():
        print(f"ERROR: 'raw' sub-folder not found inside: {project_dir}")
        sys.exit(1)

    processed_dir = project_dir / "processed"
    output_dir = project_dir / "output"
    processed_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)

    project_id = project_dir.name

    # ------------------------------------------------------------------
    print(f"\n[1/5] Extracting text from '{raw_dir}' …")
    extracted = extract_text(raw_dir, project_id)
    _write_json(processed_dir / "extracted_text.json", extracted)

    # ------------------------------------------------------------------
    print(f"\n[2/5] Cleaning text for {len(extracted['sources'])} source(s) …")
    cleaned = clean_text(extracted)
    _write_json(processed_dir / "cleaned_text.json", cleaned)

    # ------------------------------------------------------------------
    print("\n[3/5] Building project.json …")
    project_json = build_project_json(project_dir, cleaned)
    _write_json(output_dir / "project.json", project_json)

    # ------------------------------------------------------------------
    print("\n[4/5] Chunking cleaned text …")
    chunks = chunk_text(cleaned)
    _write_jsonl(output_dir / "chunks.jsonl", chunks)
    print(f"  Total chunks: {len(chunks)}")

    # ------------------------------------------------------------------
    print("\n[5/5] Generating summary …")
    summary = build_summary(extracted, project_dir)
    _write_text(output_dir / "summary.md", summary)

    # ------------------------------------------------------------------
    print(f"\nDone! Outputs written to:\n"
          f"  {processed_dir}/extracted_text.json\n"
          f"  {processed_dir}/cleaned_text.json\n"
          f"  {output_dir}/project.json\n"
          f"  {output_dir}/chunks.jsonl\n"
          f"  {output_dir}/summary.md\n")


# ---------------------------------------------------------------------------
# CLI entry point
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
    args = parser.parse_args()

    project_dir = Path(args.project).resolve()
    run_pipeline(project_dir)


if __name__ == "__main__":
    main()
