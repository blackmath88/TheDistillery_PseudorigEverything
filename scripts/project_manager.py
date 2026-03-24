from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECTS_DIR = REPO_ROOT / "projects"


def safe_project_id(name: str) -> str:
    name = (name or "").strip()
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", name)
    name = name.strip("_").strip()
    return name


def list_projects() -> list[str]:
    PROJECTS_DIR.mkdir(exist_ok=True)
    projects: list[str] = []
    for p in sorted(PROJECTS_DIR.iterdir()):
        if p.is_dir() and not p.name.startswith("."):
            projects.append(p.name)
    return projects


def get_project_dir(project_id: str) -> Path:
    project_id = safe_project_id(project_id)
    if not project_id:
        raise ValueError("Invalid project id.")
    project_dir = (PROJECTS_DIR / project_id).resolve()
    if PROJECTS_DIR.resolve() not in project_dir.parents:
        raise ValueError("Invalid project path.")
    if not project_dir.exists():
        raise FileNotFoundError(f"Project not found: {project_id}")
    return project_dir


def create_project(project_id: str) -> Path:
    PROJECTS_DIR.mkdir(exist_ok=True)
    project_id = safe_project_id(project_id)
    if not project_id:
        raise ValueError("Invalid project name.")
    project_dir = PROJECTS_DIR / project_id
    project_dir.mkdir(exist_ok=False)
    ensure_project_structure(project_dir)
    (project_dir / "project_context.md").write_text("", encoding="utf-8")
    (project_dir / "use_intent.json").write_text(
        '{\n  "purpose": "",\n  "audience": "",\n  "desired_outputs": []\n}\n',
        encoding="utf-8",
    )
    return project_dir


def ensure_project_structure(project_dir: Path) -> None:
    (project_dir / "raw").mkdir(exist_ok=True)
    (project_dir / "processed").mkdir(exist_ok=True)
    (project_dir / "output").mkdir(exist_ok=True)


def load_project_context(project_dir: Path) -> str:
    p = project_dir / "project_context.md"
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def save_project_context(project_dir: Path, content: str) -> None:
    (project_dir / "project_context.md").write_text(content or "", encoding="utf-8")


def load_use_intent_text(project_dir: Path) -> str:
    p = project_dir / "use_intent.json"
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def save_use_intent_text(project_dir: Path, content: str) -> None:
    (project_dir / "use_intent.json").write_text(content or "{}", encoding="utf-8")


def list_raw_files(project_dir: Path) -> list[Path]:
    raw_dir = project_dir / "raw"
    if not raw_dir.exists():
        return []
    return [p for p in sorted(raw_dir.iterdir()) if p.is_file() and not p.name.startswith(".")]


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


def list_output_files(project_dir: Path) -> list[Path]:
    out_dir = project_dir / "output"
    if not out_dir.exists():
        return []
    return [p for p in sorted(out_dir.rglob("*")) if p.is_file()]


def read_text_preview(path: Path, max_chars: int = 8000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > max_chars:
        return text[:max_chars] + "\n\n…(truncated)…\n"
    return text


def read_json_preview(path: Path, max_chars: int = 8000) -> str:
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        text = json.dumps(data, indent=2, ensure_ascii=False)
    except Exception:
        text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > max_chars:
        return text[:max_chars] + "\n\n…(truncated)…\n"
    return text


def read_jsonl_preview(path: Path, max_lines: int = 40, max_chars: int = 8000) -> str:
    if not path.exists():
        return ""
    lines: list[str] = []
    total = 0
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            if i >= max_lines:
                lines.append("…(truncated)…")
                break
            line = line.rstrip("\n")
            lines.append(line)
            total += len(line)
            if total > max_chars:
                lines.append("…(truncated)…")
                break
    return "\n".join(lines).strip() + "\n"