from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .models import BuilderConfig
from .pipeline import HandoffBuilder
from .v2.services import import_package_into_workspace, render_job, render_next_pending_job
from .v2.storage.db import connect_workspace_db
from .v2.storage.repositories import SqliteRenderQueueRepository
from .v2.workspace import init_project_workspace


def _safe_print(message: object) -> None:
    text = str(message)
    try:
        print(text)
    except UnicodeEncodeError:
        stream = sys.stdout
        stream.buffer.write(text.encode(stream.encoding or "utf-8", errors="replace") + b"\n")
        stream.flush()


def _print_json(payload: dict | list) -> None:
    _safe_print(json.dumps(payload, ensure_ascii=False, indent=2))


def _main_v1(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build a ChatGPT analysis handoff ZIP.")
    parser.add_argument("--input", nargs="+", required=True, help="ZIP, folder, photo, or video paths")
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument("--project", required=True, help="Project name")
    parser.add_argument("--no-proxies", action="store_true", help="Do not include full video proxies")
    args = parser.parse_args(argv)

    config = BuilderConfig(
        project_name=args.project,
        output_dir=Path(args.output),
        include_video_proxies=not args.no_proxies,
    )
    builder = HandoffBuilder(
        config,
        progress=lambda value, message: _safe_print(f"{value * 100:6.1f}%  {message}"),
        log=_safe_print,
        project_root=Path(__file__).resolve().parents[1],
    )
    result = builder.build([Path(value) for value in args.input])
    _safe_print(result.archive_path)
    if not result.validation.get("coverage_ok", False):
        _safe_print("coverage_ok=false")
        return 2
    return 0


def _build_v2_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Handoff Builder v2 local edit runner commands.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-project", help="Initialize a v2 project workspace.")
    init_parser.add_argument("workspace", help="Root work directory where the project workspace will be created.")
    init_parser.add_argument("--project-id", required=True, help="Stable project ID.")

    import_parser = subparsers.add_parser("import-package", help="Import an AI edit package into a v2 workspace.")
    import_parser.add_argument("package_zip", help="Path to AI_EDIT_PACKAGE.zip")
    import_parser.add_argument("--workspace", required=True, help="Path to the initialized project workspace.")

    queue_list_parser = subparsers.add_parser("queue-list", help="List render jobs for a project.")
    queue_list_parser.add_argument("--workspace", required=True, help="Path to the initialized project workspace.")
    queue_list_parser.add_argument("--project-id", required=True, help="Project ID to filter by.")

    queue_show_parser = subparsers.add_parser("queue-show", help="Show one render job.")
    queue_show_parser.add_argument("job_id", help="Render job ID.")
    queue_show_parser.add_argument("--workspace", required=True, help="Path to the initialized project workspace.")

    render_next_parser = subparsers.add_parser("render-next", help="Render the next pending job.")
    render_next_parser.add_argument("--workspace", required=True, help="Path to the initialized project workspace.")
    render_next_parser.add_argument("--ffmpeg-path", help="Optional path to ffmpeg executable.")
    render_next_parser.add_argument("--ffprobe-path", help="Optional path to ffprobe executable.")

    render_job_parser = subparsers.add_parser("render-job", help="Render one job by ID.")
    render_job_parser.add_argument("job_id", help="Render job ID.")
    render_job_parser.add_argument("--workspace", required=True, help="Path to the initialized project workspace.")
    render_job_parser.add_argument("--ffmpeg-path", help="Optional path to ffmpeg executable.")
    render_job_parser.add_argument("--ffprobe-path", help="Optional path to ffprobe executable.")

    return parser


def _row_to_dict(row: object) -> dict:
    return dict(row)  # type: ignore[arg-type]


def _main_v2(argv: list[str]) -> int:
    parser = _build_v2_parser()
    args = parser.parse_args(argv)

    if args.command == "init-project":
        project_root = init_project_workspace(Path(args.workspace), args.project_id)
        _print_json(
            {
                "project_id": args.project_id,
                "workspace": str(project_root),
                "database_path": str(project_root / "project.sqlite"),
            }
        )
        return 0

    if args.command == "import-package":
        result = import_package_into_workspace(Path(args.package_zip), Path(args.workspace))
        _print_json(
            {
                "project_id": result.project_id,
                "package_id": result.package_id,
                "handoff_id": result.handoff_id,
                "edit_plan_id": result.edit_plan_id,
                "render_job_id": result.render_job_id,
                "render_report_path": str(result.render_report_path),
                "package_root": str(result.package_root),
                "package_sha256": result.package_sha256,
                "plan_hash": result.plan_hash,
                "duplicate": result.duplicate,
            }
        )
        return 0
    if args.command == "render-next":
        result = render_next_pending_job(
            Path(args.workspace),
            ffmpeg_path=args.ffmpeg_path,
            ffprobe_path=args.ffprobe_path,
        )
        _print_json(result)
        return 0 if result.get("status") != "failed" else 1
    if args.command == "render-job":
        try:
            result = render_job(
                Path(args.workspace),
                args.job_id,
                ffmpeg_path=args.ffmpeg_path,
                ffprobe_path=args.ffprobe_path,
            )
            _print_json(result)
            return 0
        except Exception as exc:
            _print_json(
                {
                    "job_id": args.job_id,
                    "status": "failed",
                    "error": str(exc),
                }
            )
            return 1

    connection = connect_workspace_db(Path(args.workspace) / "project.sqlite")
    try:
        queue_repo = SqliteRenderQueueRepository(connection)
        if args.command == "queue-list":
            rows = queue_repo.list_by_project(args.project_id)
            _print_json([_row_to_dict(row) for row in rows])
            return 0
        if args.command == "queue-show":
            row = queue_repo.get_by_id(args.job_id)
            _print_json(_row_to_dict(row))
            return 0
    finally:
        connection.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "v2":
        return _main_v2(argv[1:])
    return _main_v1(argv)


if __name__ == "__main__":
    raise SystemExit(main())
