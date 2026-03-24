from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional


ProgressCB = Optional[Callable[[str], None]]


def _emit(progress_cb: ProgressCB, msg: str) -> None:
    if progress_cb:
        progress_cb(msg)


def generate_packaging_outputs(project_dir: Path, progress_cb: ProgressCB = None) -> None:
    project_dir = Path(project_dir).resolve()
    output_dir = project_dir / "output"
    output_dir.mkdir(exist_ok=True)

    project_json_path = output_dir / "project.json"
    summary_path = output_dir / "summary.md"
    chunks_path = output_dir / "chunks.jsonl"

    project_json = {}
    if project_json_path.exists():
        project_json = json.loads(project_json_path.read_text(encoding="utf-8"))

    summary_md = summary_path.read_text(encoding="utf-8", errors="replace") if summary_path.exists() else ""

    excerpts: list[str] = []
    if chunks_path.exists():
        with chunks_path.open("r", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= 8:
                    break
                try:
                    obj = json.loads(line)
                    text = (obj.get("text") or "").strip()
                    if text:
                        excerpts.append(text[:600].strip() + ("…" if len(text) > 600 else ""))
                except Exception:
                    continue

    llm_pack = build_llm_context_pack_md(project_json=project_json, summary_md=summary_md, excerpts=excerpts)
    (output_dir / "llm_context_pack.md").write_text(llm_pack, encoding="utf-8")
    _emit(progress_cb, f"Wrote: {output_dir / 'llm_context_pack.md'}")

    prompt_starter = build_prompt_starter_md(project_json=project_json)
    (output_dir / "prompt_starter.md").write_text(prompt_starter, encoding="utf-8")
    _emit(progress_cb, f"Wrote: {output_dir / 'prompt_starter.md'}")

    report_html = build_report_html(
        project_json=project_json,
        summary_md=summary_md,
        llm_pack_md=llm_pack,
        excerpts=excerpts,
    )
    (output_dir / "report.html").write_text(report_html, encoding="utf-8")
    _emit(progress_cb, f"Wrote: {output_dir / 'report.html'}")


def build_llm_context_pack_md(project_json: dict, summary_md: str, excerpts: list[str]) -> str:
    project_id = project_json.get("project_id", "")
    created_at = project_json.get("created_at", "")
    project_context = (project_json.get("project_context") or "").strip()
    use_intent = project_json.get("use_intent") or {}
    source_items = project_json.get("source_items") or []

    use_intent_pretty = json.dumps(use_intent, indent=2, ensure_ascii=False)

    lines: list[str] = []
    lines += [f"# LLM Context Pack — {project_id}".strip(), ""]
    lines += [f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", ""]
    if created_at:
        lines += [f"**Project created_at:** {created_at}", ""]

    lines += ["## Project Metadata", ""]
    lines += [f"- **Project ID:** `{project_id}`", f"- **Sources:** {len(source_items)}", ""]

    lines += ["## Project Context", ""]
    lines += [project_context if project_context else "_(No project_context.md provided yet.)_", ""]

    lines += ["## Use Intent (JSON)", ""]
    lines += ["```json", use_intent_pretty, "```", ""]

    lines += ["## Source Overview", ""]
    if source_items:
        for s in source_items:
            lines.append(
                f"- `{s.get('filename','')}` ({s.get('source_type','unknown')}, {s.get('char_count',0)} chars)"
            )
        lines.append("")
    else:
        lines += ["_(No sources detected yet. Add files to raw/ and re-run.)_", ""]

    lines += ["## Distilled Summary", ""]
    lines += [summary_md.strip() if summary_md.strip() else "_(No summary.md yet. Run distillation.)_", ""]

    lines += ["## Core Concepts", "", "- _(To be extracted / enriched)_", ""]
    lines += ["## Themes", "", "- _(To be extracted / enriched)_", ""]
    lines += ["## Open Questions", "", "- _(To be extracted / enriched)_", ""]

    lines += ["## Important Excerpts (sample)", ""]
    if excerpts:
        for ex in excerpts:
            lines += ["```text", ex.strip(), "```", ""]
    else:
        lines += ["_(No excerpts yet.)_", ""]

    lines += ["## Suggested Next Prompts", ""]
    lines += [
        "- “Give me a 1-page brief of this project for a new teammate.”",
        "- “Extract a list of stakeholders, roles, and responsibilities (if present).”",
        "- “Identify contradictions, missing info, and open questions.”",
        "- “Propose a next-step plan and what additional sources would help.”",
        "- “Turn this into a clean, structured outline for a document or wiki page.”",
        "",
    ]

    return "\n".join(lines).strip() + "\n"


def build_prompt_starter_md(project_json: dict) -> str:
    project_id = project_json.get("project_id", "")
    use_intent = project_json.get("use_intent") or {}
    use_intent_pretty = json.dumps(use_intent, indent=2, ensure_ascii=False)

    return (
        f"# Prompt Starter — {project_id}\n\n"
        "Use these prompts with `output/llm_context_pack.md` attached.\n\n"
        "## Use Intent\n\n"
        "```json\n"
        f"{use_intent_pretty}\n"
        "```\n\n"
        "## Prompts\n\n"
        "### 1) Summarize this project\n"
        "Give me a crisp summary (executive + technical) of this project. Highlight key entities, goals, and constraints.\n\n"
        "### 2) Generate a whitepaper draft\n"
        "Create a structured whitepaper outline and a 1–2 page first draft based only on the provided context.\n\n"
        "### 3) Create an HTML prototype brief\n"
        "Write a practical brief for an HTML prototype: required pages, data model, flows, and acceptance criteria.\n\n"
        "### 4) Identify open questions\n"
        "List missing information and open questions. For each, propose what source artifact would resolve it.\n\n"
        "### 5) Stakeholder messaging\n"
        "Create stakeholder-friendly messaging: elevator pitch, benefits, risks, and next steps.\n"
    ).strip() + "\n"


def build_report_html(project_json: dict, summary_md: str, llm_pack_md: str, excerpts: list[str]) -> str:
    project_id = html.escape(project_json.get("project_id", ""))
    source_items = project_json.get("source_items") or []

    summary_escaped = html.escape(summary_md.strip())
    llm_pack_escaped = html.escape(llm_pack_md.strip())

    if source_items:
        rows = []
        for s in source_items:
            rows.append(
                "<tr>"
                f"<td>{html.escape(str(s.get('filename','')))}</td>"
                f"<td><code>{html.escape(str(s.get('source_type','unknown')))}</code></td>"
                f"<td style='text-align:right'>{html.escape(str(s.get('char_count',0)))}</td>"
                "</tr>"
            )
        sources_html = (
            "<table class='table'>"
            "<thead><tr><th>Filename</th><th>Type</th><th style='text-align:right'>Chars</th></tr></thead>"
            "<tbody>" + "".join(rows) + "</tbody></table>"
        )
    else:
        sources_html = "<p class='muted'>(No sources yet.)</p>"

    if excerpts:
        blocks = [f"<pre class='code'>{html.escape(ex.strip())}</pre>" for ex in excerpts]
        excerpts_html = "\n".join(blocks)
    else:
        excerpts_html = "<p class='muted'>(No excerpts yet.)</p>"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Distillery Report — {project_id}</title>
  <style>
    :root {{
      --bg: #0b0f14;
      --panel: #101826;
      --text: #e7eefc;
      --muted: #a9b7d0;
      --border: rgba(255,255,255,0.08);
      --accent: #7aa2ff;
      --code: #0a1220;
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      --sans: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
    }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: var(--sans);
      margin: 0;
      padding: 24px;
      line-height: 1.45;
    }}
    .wrap {{ max-width: 1100px; margin: 0 auto; }}
    h1 {{ margin: 0 0 8px; font-size: 22px; }}
    .muted {{ color: var(--muted); }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px;
      margin: 16px 0;
    }}
    .row {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }}
    @media (max-width: 900px) {{
      .row {{ grid-template-columns: 1fr; }}
    }}
    .table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    .table th, .table td {{
      border-bottom: 1px solid var(--border);
      padding: 8px 10px;
    }}
    .code {{
      background: var(--code);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px;
      overflow: auto;
      font-family: var(--mono);
      font-size: 12px;
      white-space: pre-wrap;
    }}
    .btn {{
      background: transparent;
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 8px 10px;
      cursor: pointer;
    }}
    .btn:hover {{ border-color: rgba(255,255,255,0.18); }}
    .btn.primary {{ border-color: rgba(122,162,255,0.6); }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Distillery Report — {project_id}</h1>
    <div class="muted">Single-file report generated by The Distillery (local-first).</div>

    <div class="panel">
      <h2 style="margin-top:0;">Source Overview</h2>
      {sources_html}
    </div>

    <div class="panel">
      <h2 style="margin-top:0;">Summary</h2>
      <pre class="code">{summary_escaped}</pre>
    </div>

    <div class="panel">
      <div class="row">
        <div>
          <h2 style="margin-top:0;">LLM Context Pack</h2>
          <p class="muted">Copy/paste into your LLM tool, or use the web UI copy button.</p>
        </div>
        <div style="text-align:right;">
          <button class="btn primary" onclick="copyText('llmPack')">Copy context pack</button>
        </div>
      </div>
      <pre id="llmPack" class="code">{llm_pack_escaped}</pre>
    </div>

    <div class="panel">
      <h2 style="margin-top:0;">Key Excerpts (sample)</h2>
      {excerpts_html}
    </div>
  </div>

  <script>
    function copyText(id) {{
      const el = document.getElementById(id);
      const text = el ? el.innerText : '';
      navigator.clipboard.writeText(text);
    }}
  </script>
</body>
</html>
"""