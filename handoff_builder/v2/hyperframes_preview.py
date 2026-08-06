from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from handoff_builder.utils import json_dump, slugify

from .plans.semantic import LOCAL_PHOTO_SCHEMA_VERSIONS, load_and_validate_local_photo_plan


@dataclass(frozen=True, slots=True)
class PreviewProjectInfo:
    project_dir: Path
    identity: dict[str, object]
    asset_count: int
    operation_count: int


def resolve_active_preview_plan_id(snapshot: dict | None, explicit_plan_id: str | None) -> str | None:
    if not snapshot:
        return None
    known_ids = {str(item["edit_plan_id"]) for item in snapshot.get("plans", [])}
    if explicit_plan_id and explicit_plan_id in known_ids:
        return explicit_plan_id
    latest = snapshot.get("latest_plan") or {}
    latest_id = latest.get("edit_plan_id")
    return str(latest_id) if latest_id else None


def previewable_plan(plan: dict) -> bool:
    payload = plan.get("payload") or {}
    schema_version = str(payload.get("schema_version") or "")
    return schema_version in LOCAL_PHOTO_SCHEMA_VERSIONS and payload.get("mode") == "preview"


def preview_project_dir(workspace: Path, plan: dict) -> Path:
    meta = plan["metadata"]
    project_id = slugify(str(meta["project_id"]), fallback="project")
    plan_id = slugify(str(meta["edit_plan_id"]), fallback="plan")
    plan_version = int(meta.get("plan_version") or 1)
    plan_hash = str(meta["plan_hash"])[:12]
    return (
        workspace.resolve()
        / "hyperframes"
        / "projects"
        / project_id
        / f"{plan_version:03d}_{plan_id}_{plan_hash}"
    )


def build_preview_project(workspace: Path, plan: dict) -> PreviewProjectInfo:
    workspace_root = workspace.resolve()
    if not previewable_plan(plan):
        raise ValueError("HyperFrames preview project generation supports only edit_plan 2.x preview plans.")

    validated = load_and_validate_local_photo_plan(
        Path(plan["metadata"]["plan_path"]),
        workspace_root,
    )
    target_root = preview_project_dir(workspace_root, plan)
    if target_root.exists():
        shutil.rmtree(target_root)
    assets_root = target_root / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)

    segments = []
    copied_assets = []
    start_ms = 0
    for index, segment in enumerate(validated.segments, start=1):
        asset = validated.assets[segment.asset_id]
        asset_name = f"{index:03d}_{slugify(asset.asset_id, fallback='asset')}{asset.path.suffix.lower() or '.jpg'}"
        asset_target = assets_root / asset_name
        shutil.copy2(asset.path, asset_target)
        clip = {
            "asset_id": segment.asset_id,
            "asset_file": asset_name,
            "overlay_text": segment.overlay_text,
            "start_ms": start_ms,
            "duration_ms": segment.duration_ms,
            "track_index": (index - 1) % 2,
        }
        segments.append(clip)
        copied_assets.append(
            {
                "asset_id": segment.asset_id,
                "target_path": str(asset_target),
                "sha256": asset.sha256,
                "size_bytes": asset.size_bytes,
            }
        )
        start_ms += segment.duration_ms

    identity = {
        "schema_version": "1.0",
        "project_id": str(plan["metadata"]["project_id"]),
        "handoff_id": str(plan["metadata"]["handoff_id"]),
        "plan_id": str(plan["metadata"]["edit_plan_id"]),
        "plan_version": int(plan["metadata"].get("plan_version") or 1),
        "plan_hash": str(plan["metadata"]["plan_hash"]),
        "planned_duration_ms": validated.planned_duration_ms,
        "asset_count": len(validated.assets),
        "operation_count": len(validated.payload.get("operations", [])),
    }
    json_dump(target_root / "preview_identity.json", identity)
    json_dump(target_root / "preview_segments.json", {"segments": segments, "copied_assets": copied_assets})
    _write_meta_files(target_root, identity)
    _write_index_html(target_root, validated, segments, identity)
    return PreviewProjectInfo(
        project_dir=target_root,
        identity=identity,
        asset_count=len(validated.assets),
        operation_count=len(validated.payload.get("operations", [])),
    )


def _write_meta_files(project_dir: Path, identity: dict[str, object]) -> None:
    slug = slugify(str(identity["project_id"]), fallback="project")
    json_dump(
        project_dir / "meta.json",
        {
            "id": f"ai-handoff-{slug}-{identity['plan_id']}",
            "name": f"AI Handoff {identity['project_id']} {identity['plan_id']}",
            "createdAt": "2026-07-26T00:00:00.000Z",
        },
    )
    json_dump(
        project_dir / "hyperframes.json",
        {
            "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
            "registry": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
            "paths": {
                "blocks": "compositions",
                "components": "compositions/components",
                "assets": "assets",
            },
            "media": {"autoProxy": True},
        },
    )
    json_dump(
        project_dir / "package.json",
        {
            "name": f"ai-handoff-{slug}-{identity['plan_id']}",
            "private": True,
            "type": "module",
            "scripts": {
                "dev": "npx --yes hyperframes@0.7.71 preview",
                "check": "npx --yes hyperframes@0.7.71 check",
                "lint": "npx --yes hyperframes@0.7.71 lint",
                "inspect": "npx --yes hyperframes@0.7.71 inspect",
            },
        },
    )


def _write_index_html(
    project_dir: Path,
    validated,
    segments: list[dict[str, object]],
    identity: dict[str, object],
) -> None:
    clip_lines: list[str] = []
    overlay_lines: list[str] = []
    for index, segment in enumerate(segments, start=1):
        start_seconds = float(segment["start_ms"]) / 1000
        duration_seconds = float(segment["duration_ms"]) / 1000
        clip_lines.append(
            f'    <img id="shot-{index}" class="clip shot" src="assets/{segment["asset_file"]}" alt="" '
            f'data-start="{start_seconds:.3f}" data-duration="{duration_seconds:.3f}" '
            f'data-track-index="{int(segment["track_index"])}">'
        )
        overlay_text = segment.get("overlay_text")
        if overlay_text:
            overlay_lines.append(
                f'    <div class="clip overlay" data-start="{start_seconds:.3f}" '
                f'data-duration="{duration_seconds:.3f}" data-track-index="3">{_escape_html(str(overlay_text))}</div>'
            )

    html = f"""<!DOCTYPE html>
<html lang="en" data-resolution="portrait">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width={validated.output_width}, height={validated.output_height}">
  <title>AI Handoff Builder - {identity["project_id"]} Preview</title>
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; width: {validated.output_width}px; height: {validated.output_height}px; overflow: hidden; background: #080808; }}
    body {{ font-family: Arial, Helvetica, sans-serif; }}
    #stage {{ position: relative; width: {validated.output_width}px; height: {validated.output_height}px; overflow: hidden; background: #05070b; color: #ffffff; }}
    .shot {{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }}
    .overlay {{
      position: absolute;
      left: 48px;
      right: 48px;
      bottom: 72px;
      padding: 18px 24px;
      border-radius: 18px;
      background: rgba(0, 0, 0, 0.72);
      color: #ffffff;
      font-size: 36px;
      font-weight: 700;
      letter-spacing: 0.02em;
    }}
    .project-badge {{
      position: absolute;
      top: 40px;
      left: 40px;
      padding: 10px 16px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.14);
      font-size: 18px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
  </style>
</head>
<body>
  <main id="stage" data-composition-id="{slugify(str(identity["project_id"]))}-{slugify(str(identity["plan_id"]))}" data-start="0" data-duration="{validated.planned_duration_ms / 1000:.3f}" data-width="{validated.output_width}" data-height="{validated.output_height}">
    <div class="project-badge">{_escape_html(str(identity["project_id"]))} / {int(identity["plan_version"])} / {_escape_html(str(identity["plan_hash"])[:12])}</div>
{chr(10).join(clip_lines)}
{chr(10).join(overlay_lines)}
  </main>
</body>
</html>
"""
    (project_dir / "index.html").write_text(html, encoding="utf-8")


def _escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
