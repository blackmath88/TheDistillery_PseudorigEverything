from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional


ProgressCB = Optional[Callable[[str], None]]


class DistilleryError(Exception):
    pass


def _emit(progress_cb: ProgressCB, msg: str) -> None:
    if progress_cb:
        progress_cb(msg)


def _load_pypdf():
    try:
        from pypdf import PdfReader  # noqa: C0415
        return PdfReader
    except ImportError as exc:
        raise DistilleryError("Missing dependency: pypdf. Install with: pip install pypdf") from exc


def infer_source_type(filename: str) -> str:
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


def make_source_id(filename: str) -> str:
    stem = Path(filename).stem
    return re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_")


def extract_text(raw_dir: Path, project_id: str, progress_cb: ProgressCB = None) -> dict:
    supported = {".txt", ".md", ".pdf"}
    sources = []

    files = sorted(raw_dir.iterdir()) if raw_dir.exists() else []
    if not files:
        _emit(progress_cb, "WARNING: No files found in raw/")

    for filepath in files:
        if filepath.suffix.lower() not in supported:
            _emit(progress_cb, f"SKIP: {filepath.name} (unsupported extension)")
            continue

        _emit(progress_cb, f"Extracting: {filepath.name}")
        raw_text = _read_file(filepath)
        sources.append(
            {
                "source_id": make_source_id(filepath.name),
                "filename": filepath.name,
                "source_type": infer_source_type(filepath.name),
                "raw_text": raw_text,
            }
        )

    return {"project_id": project_id, "sources": sources}


def _read_file(filepath: Path) -> str:
    suffix = filepath.suffix.lower()
    if suffix in {".txt", ".md"}:
        return filepath.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        return _read_pdf(filepath)
    return ""


def _read_pdf(filepath: Path) -> str:
    PdfReader = _load_pypdf()
    try:
        reader = PdfReader(str(filepath))
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return "\n".join(pages)
    except Exception:
        return ""


def clean_text(extracted: dict) -> dict:
    cleaned_sources = []
    for source in extracted["sources"]:
        clean = _normalise(source["raw_text"])
        cleaned_sources.append({**source, "clean_text": clean})
    return {"project_id": extracted["project_id"], "sources": cleaned_sources}


def _normalise(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    joined = "\n".join(lines)
    joined = re.sub(r"\n{3,}", "\n\n", joined)
    return joined.strip()


def build_project_json(project_dir: Path, cleaned: dict, progress_cb: ProgressCB = None) -> dict:
    project_context = _load_text_file(project_dir / "project_context.md", progress_cb=progress_cb)
    use_intent = _load_json_file(project_dir / "use_intent.json", progress_cb=progress_cb)

    source_items = [
        {
            "source_id": s["source_id"],
            "filename": s["filename"],
            "source_type": s["source_type"],
            "char_count": len(s.get("raw_text", "")),
        }
        for s in cleaned["sources"]
    ]

    return {
        "project_id": cleaned["project_id"],
        "project_context": project_context,
        "use_intent": use_intent,
        "core_concepts": [],
        "themes": [],
        "user_notes": [],
        "application_ideas": [],
        "open_questions": [],
        "derived_summary": [],
        "source_items": source_items,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _load_text_file(path: Path, progress_cb: ProgressCB = None) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    _emit(progress_cb, f"INFO: {path.name} not found — skipping.")
    return ""


def _load_json_file(path: Path, progress_cb: ProgressCB = None) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            _emit(progress_cb, f"WARNING: Could not parse {path.name}: {exc}")
            return {}
    _emit(progress_cb, f"INFO: {path.name} not found — skipping.")
    return {}


def chunk_text(cleaned: dict, chunk_words: int = 400) -> list:
    chunks = []
    chunk_index = 0

    for source in cleaned["sources"]:
        source_chunks = _split_into_chunks(text=source["clean_text"], chunk_words=chunk_words)
        for chunk_text_part in source_chunks:
            chunks.append(
                {
                    "chunk_id": f"chunk_{chunk_index:04d}",
                    "project_id": cleaned["project_id"],
                    "source_id": source["source_id"],
                    "section_title": "",
                    "source_type": source["source_type"],
                    "text": chunk_text_part,
                    "tags": [],
                    "keywords": [],
                }
            )
            chunk_index += 1

    return chunks


def _split_into_chunks(text: str, chunk_words: int) -> list:
    if not text.strip():
        return []

    chunks = []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    for paragraph in paragraphs:
        words = paragraph.split()
        if not words:
            continue

        if len(words) <= chunk_words:
            chunks.append(" ".join(words))
            continue

        start = 0
        while start < len(words):
            end = start + chunk_words
            chunks.append(" ".join(words[start:end]))
            start = end

    return chunks


def build_summary(extracted: dict, llm_summary: str = "") -> str:
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

    if llm_summary.strip():
        lines += ["", "## Knowledge Synthesis", "", llm_summary.strip(), ""]
    else:
        lines += ["", "## Source Previews", ""]
        for s in sources:
            preview = s["raw_text"][:500].replace("\n", " ").strip()
            if len(s["raw_text"]) > 500:
                preview += "…"
            lines += [f"### {s['filename']} (`{s['source_type']}`)", "", preview, ""]

    return "\n".join(lines)


def generate_llm_summary(cleaned: dict, project_json: dict, model: str, progress_cb: ProgressCB = None) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        _emit(progress_cb, "WARNING: --llm enabled but OPENAI_API_KEY is not set; using fallback summary.")
        return ""

    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    endpoint = base_url.rstrip("/") + "/chat/completions"

    source_blocks = []
    for source in cleaned["sources"]:
        source_blocks.append(f"[SOURCE: {source['filename']} | {source['source_type']}]\n{source['clean_text']}")

    corpus = "\n\n".join(source_blocks)
    max_chars = 120000
    if len(corpus) > max_chars:
        corpus = corpus[:max_chars]

    system_prompt = "You are a concise research distillation assistant. Return clear markdown with section headers and short bullets."
    user_prompt = (
        "Synthesize this project corpus into practical knowledge for future retrieval.\n\n"
        f"Project ID: {cleaned['project_id']}\n"
        f"Project context: {project_json.get('project_context', '')}\n"
        f"Use intent: {json.dumps(project_json.get('use_intent', {}), ensure_ascii=False)}\n\n"
        "Required sections:\n"
        "1) Core concepts\n"
        "2) Key themes\n"
        "3) Practical application ideas\n"
        "4) Open questions\n"
        "5) One-paragraph executive summary\n\n"
        "Use only the provided corpus. If uncertain, say so explicitly.\n\n"
        f"Corpus:\n{corpus}"
    )

    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            body = json.loads(response.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        _emit(progress_cb, f"WARNING: LLM summary request failed ({exc.code}): {details}")
    except Exception as exc:
        _emit(progress_cb, f"WARNING: LLM summary request failed: {exc}")

    return ""


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def write_jsonl(path: Path, records: list) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def run_pipeline(
    project_dir: Path,
    chunk_words: int = 400,
    use_llm: bool = False,
    llm_model: str = "gpt-4o-mini",
    progress_cb: ProgressCB = None,
) -> None:
    project_dir = Path(project_dir).resolve()

    if not project_dir.exists():
        raise DistilleryError(f"Project directory not found: {project_dir}")

    raw_dir = project_dir / "raw"
    if not raw_dir.exists():
        raise DistilleryError(f"'raw' sub-folder not found inside: {project_dir}")

    processed_dir = project_dir / "processed"
    output_dir = project_dir / "output"
    processed_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)

    project_id = project_dir.name

    _emit(progress_cb, f"[1/5] Extracting text from '{raw_dir}' …")
    extracted = extract_text(raw_dir, project_id, progress_cb=progress_cb)
    write_json(processed_dir / "extracted_text.json", extracted)
    _emit(progress_cb, f"Wrote: {processed_dir / 'extracted_text.json'}")

    _emit(progress_cb, f"[2/5] Cleaning text for {len(extracted['sources'])} source(s) …")
    cleaned = clean_text(extracted)
    write_json(processed_dir / "cleaned_text.json", cleaned)
    _emit(progress_cb, f"Wrote: {processed_dir / 'cleaned_text.json'}")

    _emit(progress_cb, "[3/5] Building project.json …")
    project_json = build_project_json(project_dir, cleaned, progress_cb=progress_cb)
    write_json(output_dir / "project.json", project_json)
    _emit(progress_cb, f"Wrote: {output_dir / 'project.json'}")

    _emit(progress_cb, "[4/5] Chunking cleaned text …")
    chunks = chunk_text(cleaned, chunk_words=chunk_words)
    write_jsonl(output_dir / "chunks.jsonl", chunks)
    _emit(progress_cb, f"Wrote: {output_dir / 'chunks.jsonl'} (chunks={len(chunks)}, chunk_words={chunk_words})")

    _emit(progress_cb, "[5/5] Generating summary …")
    llm_summary = ""
    if use_llm:
        _emit(progress_cb, f"LLM synthesis enabled (model={llm_model})")
        llm_summary = generate_llm_summary(cleaned, project_json, llm_model, progress_cb=progress_cb)

    summary = build_summary(extracted, llm_summary=llm_summary)
    write_text(output_dir / "summary.md", summary)
    _emit(progress_cb, f"Wrote: {output_dir / 'summary.md'}")