from __future__ import annotations

import json
import os
import re
from pathlib import Path

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from scripts.project_manager import (
    PROJECTS_DIR,
    create_project,
    ensure_project_structure,
    get_project_dir,
    infer_source_type,
    list_output_files,
    list_projects,
    list_raw_files,
    load_project_context,
    load_use_intent_text,
    read_json_preview,
    read_jsonl_preview,
    read_text_preview,
    safe_project_id,
    save_project_context,
    save_use_intent_text,
)
from scripts.distillery_engine import run_pipeline
from scripts.packaging import generate_packaging_outputs


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = os.environ.get("DISTILLERY_SECRET_KEY", "local-dev-secret")

    @app.get("/")
    def index():
        projects = list_projects()
        return render_template(
            "index.html",
            projects=projects,
            projects_dir=str(PROJECTS_DIR),
        )

    @app.post("/create_project")
    def create_project_route():
        project_id_raw = request.form.get("project_id", "").strip()
        project_id = safe_project_id(project_id_raw)
        if not project_id:
            flash("Please enter a valid project name.", "error")
            return redirect(url_for("index"))

        project_dir = create_project(project_id)
        flash(f"Created project: {project_dir.name}", "success")
        return redirect(url_for("project_view", project_id=project_id))

    @app.get("/project/<project_id>")
    def project_view(project_id: str):
        project_id = safe_project_id(project_id)
        project_dir = get_project_dir(project_id)
        ensure_project_structure(project_dir)

        raw_files = [
            {"name": f.name, "source_type": infer_source_type(f.name), "size": f.stat().st_size}
            for f in list_raw_files(project_dir)
        ]
        output_files = [str(p.relative_to(project_dir)) for p in list_output_files(project_dir)]

        summary_md = read_text_preview(project_dir / "output" / "summary.md", max_chars=12000)
        project_json = read_json_preview(project_dir / "output" / "project.json", max_chars=12000)
        chunks_preview = read_jsonl_preview(
            project_dir / "output" / "chunks.jsonl", max_lines=40, max_chars=12000
        )

        llm_pack = read_text_preview(project_dir / "output" / "llm_context_pack.md", max_chars=12000)
        prompt_starter = read_text_preview(project_dir / "output" / "prompt_starter.md", max_chars=12000)

        report_path = project_dir / "output" / "report.html"
        report_exists = report_path.exists()

        project_context = load_project_context(project_dir)
        use_intent_text = load_use_intent_text(project_dir)

        return render_template(
            "project.html",
            project_id=project_id,
            project_dir=str(project_dir),
            structure={
                "raw": str(project_dir / "raw"),
                "processed": str(project_dir / "processed"),
                "output": str(project_dir / "output"),
            },
            project_context=project_context,
            use_intent_text=use_intent_text,
            raw_files=raw_files,
            output_files=output_files,
            summary_md=summary_md,
            project_json_preview=project_json,
            chunks_preview=chunks_preview,
            llm_context_pack_preview=llm_pack,
            prompt_starter_preview=prompt_starter,
            report_exists=report_exists,
        )

    @app.post("/project/<project_id>/save_context")
    def save_context(project_id: str):
        project_id = safe_project_id(project_id)
        project_dir = get_project_dir(project_id)
        ensure_project_structure(project_dir)

        project_context = request.form.get("project_context", "")
        use_intent_text = request.form.get("use_intent_text", "")

        if use_intent_text.strip():
            try:
                json.loads(use_intent_text)
            except json.JSONDecodeError as exc:
                flash(f"use_intent.json is not valid JSON: {exc}", "error")
                return redirect(url_for("project_view", project_id=project_id))

        save_project_context(project_dir, project_context)
        save_use_intent_text(project_dir, use_intent_text)
        flash("Saved context files.", "success")
        return redirect(url_for("project_view", project_id=project_id) + "#context")

    @app.post("/project/<project_id>/upload")
    def upload_files(project_id: str):
        project_id = safe_project_id(project_id)
        project_dir = get_project_dir(project_id)
        ensure_project_structure(project_dir)

        uploaded = request.files.getlist("files")
        if not uploaded or all((f is None or not f.filename) for f in uploaded):
            flash("No files selected for upload.", "error")
            return redirect(url_for("project_view", project_id=project_id) + "#sources")

        raw_dir = project_dir / "raw"
        raw_dir.mkdir(exist_ok=True)

        saved = 0
        for f in uploaded:
            if not f or not f.filename:
                continue
            filename = Path(f.filename).name
            filename = re.sub(r"[^A-Za-z0-9._ -]+", "_", filename).strip()
            if not filename:
                continue
            dest = raw_dir / filename
            f.save(dest)
            saved += 1

        flash(f"Uploaded {saved} file(s) into raw/.", "success")
        return redirect(url_for("project_view", project_id=project_id) + "#sources")

    @app.post("/project/<project_id>/run")
    def run_project(project_id: str):
        project_id = safe_project_id(project_id)
        project_dir = get_project_dir(project_id)
        ensure_project_structure(project_dir)

        chunk_words_str = request.form.get("chunk_words", "400").strip()
        use_llm = bool(request.form.get("use_llm"))
        llm_model = request.form.get("llm_model", "gpt-4o-mini").strip() or "gpt-4o-mini"

        try:
            chunk_words = int(chunk_words_str)
        except ValueError:
            flash("chunk_words must be an integer.", "error")
            return redirect(url_for("project_view", project_id=project_id) + "#run")

        progress: list[str] = []

        def progress_cb(msg: str) -> None:
            progress.append(msg)

        try:
            run_pipeline(
                project_dir=project_dir,
                chunk_words=chunk_words,
                use_llm=use_llm,
                llm_model=llm_model,
                progress_cb=progress_cb,
            )
            generate_packaging_outputs(project_dir, progress_cb=progress_cb)
            flash("Pipeline completed successfully.", "success")
        except Exception as exc:
            flash(f"Pipeline failed: {exc}", "error")

        log_path = project_dir / "output" / "_last_run.log"
        log_path.write_text("\n".join(progress).strip() + "\n", encoding="utf-8")

        return redirect(url_for("project_view", project_id=project_id) + "#run")

    @app.get("/project/<project_id>/download/<path:relpath>")
    def download_file(project_id: str, relpath: str):
        project_id = safe_project_id(project_id)
        project_dir = get_project_dir(project_id)
        ensure_project_structure(project_dir)

        relpath = relpath.replace("\\", "/")
        if not relpath.startswith("output/"):
            flash("Downloads are restricted to output/.", "error")
            return redirect(url_for("project_view", project_id=project_id) + "#outputs")

        file_path = (project_dir / relpath).resolve()
        if project_dir.resolve() not in file_path.parents:
            flash("Invalid path.", "error")
            return redirect(url_for("project_view", project_id=project_id) + "#outputs")

        if not file_path.exists() or not file_path.is_file():
            flash("File not found.", "error")
            return redirect(url_for("project_view", project_id=project_id) + "#outputs")

        return send_file(file_path, as_attachment=True)

    @app.get("/project/<project_id>/report")
    def open_report(project_id: str):
        project_id = safe_project_id(project_id)
        project_dir = get_project_dir(project_id)
        report_path = project_dir / "output" / "report.html"
        if not report_path.exists():
            flash("report.html not found yet. Run the pipeline first.", "error")
            return redirect(url_for("project_view", project_id=project_id) + "#pack")
        return send_file(report_path, mimetype="text/html")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)