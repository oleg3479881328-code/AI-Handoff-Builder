from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .models import BuilderConfig
from .pipeline import HandoffBuilder
from .v2.services import (
    apply_patch_in_workspace,
    import_package_into_workspace,
    list_plans,
    render_job,
    render_next_pending_job,
    voice_delegated_technical_approval,
    show_plan,
    voice_align,
    voice_approve,
    voice_generate,
    voice_generate_from_plan,
    voice_health,
    voice_job_status,
    voice_music_patch,
    voice_mix_preview,
    voice_profile_map,
    voice_profile_samples,
    voice_profiles,
    voice_report,
    voice_take_qc,
)
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
    init_parser.add_argument("workspace", help="Exact workspace directory to initialize or reopen.")
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

    apply_patch_parser = subparsers.add_parser("apply-patch", help="Apply an immutable edit patch in a v2 workspace.")
    apply_patch_parser.add_argument("patch_source", help="Path to AI_EDIT_PATCH.json or AI_EDIT_PATCH.zip")
    apply_patch_parser.add_argument("--workspace", required=True, help="Path to the initialized project workspace.")

    plan_list_parser = subparsers.add_parser("plan-list", help="List plan versions for a project.")
    plan_list_parser.add_argument("--workspace", required=True, help="Path to the initialized project workspace.")
    plan_list_parser.add_argument("--project-id", required=True, help="Project ID to filter by.")

    plan_show_parser = subparsers.add_parser("plan-show", help="Show one plan version and payload.")
    plan_show_parser.add_argument("plan_id", help="Plan ID.")
    plan_show_parser.add_argument("--workspace", required=True, help="Path to the initialized project workspace.")

    voice_health_parser = subparsers.add_parser("voice-health", help="Show local Voicebox runtime health.")
    voice_health_parser.add_argument("--base-url", default="http://127.0.0.1:17493", help="Voicebox base URL.")

    voice_profiles_parser = subparsers.add_parser("voice-profiles", help="List available local Voicebox profiles.")
    voice_profiles_parser.add_argument("--base-url", default="http://127.0.0.1:17493", help="Voicebox base URL.")

    voice_map_parser = subparsers.add_parser("voice-profile-map", help="Map a stable profile_key to a local Voicebox profile_id.")
    voice_map_parser.add_argument("--workspace", required=True, help="Path to the initialized project workspace.")
    voice_map_parser.add_argument("--profile-key", required=True, help="Stable profile key.")
    voice_map_parser.add_argument("--profile-id", required=True, help="Local Voicebox profile UUID.")
    voice_map_parser.add_argument("--base-url", default="http://127.0.0.1:17493", help="Voicebox base URL.")

    voice_samples_parser = subparsers.add_parser("voice-profile-samples", help="List samples for one local Voicebox profile.")
    voice_samples_parser.add_argument("--workspace", help="Workspace path when resolving by profile-key.")
    voice_samples_parser.add_argument("--profile-key", help="Stable profile key.")
    voice_samples_parser.add_argument("--profile-id", help="Local Voicebox profile UUID.")
    voice_samples_parser.add_argument("--base-url", default="http://127.0.0.1:17493", help="Voicebox base URL.")

    voice_generate_parser = subparsers.add_parser("voice-generate", help="Generate one multi-take voice job.")
    voice_generate_parser.add_argument("--workspace", required=True, help="Path to the initialized project workspace.")
    voice_generate_parser.add_argument("--profile-key", help="Stable profile key.")
    voice_generate_parser.add_argument("--text", help="Voiceover text.")
    voice_generate_parser.add_argument("--plan-id", help="Imported edit plan ID with voiceover.spec_path.")
    voice_generate_parser.add_argument("--language", default="en-US", help="Language tag.")
    voice_generate_parser.add_argument("--takes", type=int, default=3, help="Number of takes to generate.")
    voice_generate_parser.add_argument("--seeds", nargs="*", type=int, help="Optional explicit seeds.")
    voice_generate_parser.add_argument("--engine", default="qwen", help="Voicebox engine.")
    voice_generate_parser.add_argument("--model-size", default="0.6B", help="Voicebox model size.")
    voice_generate_parser.add_argument("--instruct", help="Optional style instruction.")
    voice_generate_parser.add_argument("--target-duration-ms", type=int, help="Optional target duration in milliseconds.")
    voice_generate_parser.add_argument("--duration-tolerance-percent", type=float, default=3.0, help="Allowed duration delta before correction.")
    voice_generate_parser.add_argument("--max-auto-tempo-percent", type=float, default=8.0, help="Maximum allowed automatic atempo correction.")
    voice_generate_parser.add_argument("--base-url", default="http://127.0.0.1:17493", help="Voicebox base URL.")

    voice_job_parser = subparsers.add_parser("voice-job-status", help="Show one voice job.")
    voice_job_parser.add_argument("voice_job_id", help="Voice job ID.")
    voice_job_parser.add_argument("--workspace", required=True, help="Path to the initialized project workspace.")

    voice_takes_parser = subparsers.add_parser("voice-takes", help="List takes for one voice job.")
    voice_takes_parser.add_argument("voice_job_id", help="Voice job ID.")
    voice_takes_parser.add_argument("--workspace", required=True, help="Path to the initialized project workspace.")

    voice_qc_parser = subparsers.add_parser("voice-qc", help="Show QC payload for one take.")
    voice_qc_parser.add_argument("take_id", help="Voice take ID.")
    voice_qc_parser.add_argument("--workspace", required=True, help="Path to the initialized project workspace.")

    voice_approve_parser = subparsers.add_parser("voice-approve", help="Approve or reject one take.")
    voice_approve_parser.add_argument("take_id", help="Voice take ID.")
    voice_approve_parser.add_argument("--workspace", required=True, help="Path to the initialized project workspace.")
    voice_approve_parser.add_argument("--approve", action="store_true", help="Approve this take as primary.")
    voice_approve_parser.add_argument("--similarity", type=int, default=3)
    voice_approve_parser.add_argument("--naturalness", type=int, default=3)
    voice_approve_parser.add_argument("--pronunciation", type=int, default=3)
    voice_approve_parser.add_argument("--pacing", type=int, default=3)
    voice_approve_parser.add_argument("--emotion-style-fit", type=int, default=3)
    voice_approve_parser.add_argument("--artifacts", default="minor")
    voice_approve_parser.add_argument("--notes", default="")

    voice_auto_approve_parser = subparsers.add_parser("voice-auto-approve", help="Select the best take using delegated technical approval.")
    voice_auto_approve_parser.add_argument("voice_job_id", help="Voice job ID.")
    voice_auto_approve_parser.add_argument("--workspace", required=True, help="Path to the initialized project workspace.")
    voice_auto_approve_parser.add_argument("--notes", default="", help="Optional delegated approval note.")

    voice_align_parser = subparsers.add_parser("voice-align", help="Attempt word alignment for one take.")
    voice_align_parser.add_argument("take_id", help="Voice take ID.")
    voice_align_parser.add_argument("--workspace", required=True, help="Path to the initialized project workspace.")

    voice_mix_parser = subparsers.add_parser("voice-mix-preview", help="Render a preview mix with one approved/generated take.")
    voice_mix_parser.add_argument("take_id", help="Voice take ID.")
    voice_mix_parser.add_argument("--workspace", required=True, help="Path to the initialized project workspace.")
    voice_mix_parser.add_argument("--video", required=True, help="Input video path.")
    voice_mix_parser.add_argument("--music", help="Optional music audio path.")
    voice_mix_parser.add_argument("--voice-gain-percent", type=int, default=100)
    voice_mix_parser.add_argument("--music-gain-percent", type=int, default=12)
    voice_mix_parser.add_argument("--original-audio-gain-percent", type=int, default=0)
    voice_mix_parser.add_argument("--ducking", action="store_true")
    voice_mix_parser.add_argument("--music-fade-out-ms", type=int, default=350)

    voice_music_patch_parser = subparsers.add_parser("voice-music-patch", help="Apply an immutable music-only patch and rerender.")
    voice_music_patch_parser.add_argument("voice_job_id", help="Voice job ID.")
    voice_music_patch_parser.add_argument("--workspace", required=True, help="Path to the initialized project workspace.")
    voice_music_patch_parser.add_argument("--video", required=True, help="Input video path.")
    voice_music_patch_parser.add_argument("--music", help="Optional music audio path.")
    voice_music_patch_parser.add_argument("--reduce-music-percent", type=float, help="Reduce current music level by a relative percent.")
    voice_music_patch_parser.add_argument("--music-gain-percent", type=float, help="Absolute music gain percent.")

    voice_report_parser = subparsers.add_parser("voice-report", help="Write one JSON report for a voice job.")
    voice_report_parser.add_argument("voice_job_id", help="Voice job ID.")
    voice_report_parser.add_argument("--workspace", required=True, help="Path to the initialized project workspace.")

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
    if args.command == "apply-patch":
        result = apply_patch_in_workspace(Path(args.patch_source), Path(args.workspace))
        _print_json(
            {
                "project_id": result.project_id,
                "package_id": result.package_id,
                "handoff_id": result.handoff_id,
                "patch_id": result.patch_id,
                "patch_sha256": result.patch_sha256,
                "base_plan_id": result.base_plan_id,
                "base_plan_hash": result.base_plan_hash,
                "new_plan_id": result.new_plan_id,
                "new_plan_hash": result.new_plan_hash,
                "render_job_id": result.render_job_id,
                "render_report_path": str(result.render_report_path),
                "patch_root": str(result.patch_root),
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
    if args.command == "voice-health":
        _print_json(voice_health(base_url=args.base_url))
        return 0
    if args.command == "voice-profiles":
        _print_json(voice_profiles(base_url=args.base_url))
        return 0
    if args.command == "voice-profile-map":
        _print_json(
            voice_profile_map(
                Path(args.workspace),
                profile_key=args.profile_key,
                profile_id=args.profile_id,
                base_url=args.base_url,
            )
        )
        return 0
    if args.command == "voice-profile-samples":
        _print_json(
            voice_profile_samples(
                Path(args.workspace) if args.workspace else None,
                profile_key=args.profile_key,
                profile_id=args.profile_id,
                base_url=args.base_url,
            )
        )
        return 0
    if args.command == "voice-generate":
        if args.plan_id:
            _print_json(
                voice_generate_from_plan(
                    Path(args.workspace),
                    plan_id=args.plan_id,
                    base_url=args.base_url,
                )
            )
            return 0
        if not args.profile_key or not args.text:
            raise SystemExit("--profile-key and --text are required unless --plan-id is used.")
        _print_json(
            voice_generate(
                Path(args.workspace),
                profile_key=args.profile_key,
                text=args.text,
                language=args.language,
                takes=args.takes,
                seeds=args.seeds,
                engine=args.engine,
                model_size=args.model_size,
                instruct=args.instruct,
                target_duration_ms=args.target_duration_ms,
                duration_tolerance_percent=args.duration_tolerance_percent,
                max_auto_tempo_percent=args.max_auto_tempo_percent,
                base_url=args.base_url,
            )
        )
        return 0
    if args.command == "voice-job-status":
        _print_json(voice_job_status(Path(args.workspace), args.voice_job_id))
        return 0
    if args.command == "voice-takes":
        _print_json(voice_job_status(Path(args.workspace), args.voice_job_id)["takes"])
        return 0
    if args.command == "voice-qc":
        _print_json(voice_take_qc(Path(args.workspace), args.take_id))
        return 0
    if args.command == "voice-approve":
        _print_json(
            voice_approve(
                Path(args.workspace),
                take_id=args.take_id,
                similarity=args.similarity,
                naturalness=args.naturalness,
                pronunciation=args.pronunciation,
                pacing=args.pacing,
                emotion_style_fit=args.emotion_style_fit,
                artifacts=args.artifacts,
                approve=args.approve,
                notes=args.notes,
            )
        )
        return 0
    if args.command == "voice-auto-approve":
        _print_json(
            voice_delegated_technical_approval(
                Path(args.workspace),
                voice_job_id=args.voice_job_id,
                notes=args.notes,
            )
        )
        return 0
    if args.command == "voice-align":
        _print_json(voice_align(Path(args.workspace), take_id=args.take_id))
        return 0
    if args.command == "voice-mix-preview":
        _print_json(
            voice_mix_preview(
                Path(args.workspace),
                take_id=args.take_id,
                video_path=Path(args.video),
                music_path=Path(args.music) if args.music else None,
                voice_gain_percent=args.voice_gain_percent,
                music_gain_percent=args.music_gain_percent,
                original_audio_gain_percent=args.original_audio_gain_percent,
                ducking=args.ducking,
                music_fade_out_ms=args.music_fade_out_ms,
            )
        )
        return 0
    if args.command == "voice-music-patch":
        _print_json(
            voice_music_patch(
                Path(args.workspace),
                voice_job_id=args.voice_job_id,
                video_path=Path(args.video),
                music_path=Path(args.music) if args.music else None,
                reduce_music_percent=args.reduce_music_percent,
                music_gain_percent=args.music_gain_percent,
            )
        )
        return 0
    if args.command == "voice-report":
        _print_json(voice_report(Path(args.workspace), voice_job_id=args.voice_job_id))
        return 0

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
        if args.command == "plan-list":
            _print_json(list_plans(Path(args.workspace), project_id=args.project_id))
            return 0
        if args.command == "plan-show":
            _print_json(show_plan(Path(args.workspace), args.plan_id))
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
