from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

import hashlib

from handoff_builder.v2.packages.guards import compute_sha256
from handoff_builder.v2.packages.guards import ensure_allowed_package_path
from handoff_builder.v2.plans.schema import validate_payload
from handoff_builder.v2.plans.semantic import (
    load_and_validate_mixed_media_plan,
    ValidatedMixedMediaPlan,
)
from handoff_builder.v2.render.compiler import compile_mixed_media_render_plan
from handoff_builder.v2.render.ffmpeg_backend import FFmpegBackend
from handoff_builder.v2.errors import UnsafePackageError


def _create_minimal_mp4(path: Path) -> None:
    """Create a minimal valid MP4 file using ffmpeg."""
    ffmpeg = r"C:\Users\oleg3\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin\ffmpeg.exe"
    subprocess.run(
        [
            ffmpeg, "-y",
            "-f", "lavfi", "-i", "color=c=black:s=2x2:d=0.1:r=1",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            str(path),
        ],
        capture_output=True,
        check=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan_payload(
    *,
    project_id: str = "proj-mm-1",
    handoff_id: str = "handoff-mm-1",
    handoff_sha256: str = "a" * 64,
    plan_id: str = "plan-mm-1",
    assets: list | None = None,
    operations: list | None = None,
    audio_track: dict | None = None,
) -> dict:
    payload = {
        "schema_version": "3.0",
        "project_id": project_id,
        "handoff_id": handoff_id,
        "handoff_sha256": handoff_sha256,
        "plan_id": plan_id,
        "created_at": "2026-07-25T12:00:00Z",
        "mode": "preview",
        "output": {
            "width": 1080,
            "height": 1920,
            "fps": 30,
        },
        "media_type": ["photo", "video"],
        "assets": assets or [
            {
                "asset_id": "photo-1",
                "media_type": "photo",
                "source_path": "C:/Users/test/Pictures/photo1.jpg",
                "sha256": "d" * 64,
                "size_bytes": 1024,
            },
            {
                "asset_id": "video-1",
                "media_type": "video",
                "source_path": "C:/Users/test/Videos/clip1.mp4",
                "sha256": "e" * 64,
                "size_bytes": 2048,
            },
        ],
        "operations": operations or [
            {
                "op": "image_hold",
                "asset_id": "photo-1",
                "duration_ms": 3000,
            },
            {
                "op": "video_segment",
                "asset_id": "video-1",
                "source_in_ms": 0,
                "source_out_ms": 5000,
                "mute_original_audio": True,
            },
        ],
    }
    if audio_track is not None:
        payload["audio_track"] = audio_track
    return payload


def _make_manifest(
    *,
    project_id: str = "proj-mm-1",
    handoff_id: str = "handoff-mm-1",
    handoff_sha256: str = "a" * 64,
    plan_sha256: str = "b" * 64,
    plan_size: int = 500,
    audio_track: dict | None = None,
) -> dict:
    manifest = {
        "schema_version": "3.0",
        "project_id": project_id,
        "handoff_id": handoff_id,
        "handoff_sha256": handoff_sha256,
        "created_at": "2026-07-25T12:00:00Z",
        "plans": [
            {"plan_id": "plan-mm-1", "path": "plans/plan-mm-1.json", "sha256": plan_sha256},
        ],
    }
    if audio_track:
        manifest["audio_track"] = audio_track
    return manifest


def _make_audio_track(*, path: str = "audio/track.mp3") -> dict:
    return {
        "path": path,
        "sha256": "c" * 64,
        "size_bytes": 4096,
        "gain": 0.8,
    }


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestMixedMediaSchemaValidation:
    """Validate edit_plan 3.0 schema."""

    def test_valid_plan_passes_schema(self):
        payload = _make_plan_payload()
        validate_payload("edit_plan", "3.0", payload)

    def test_invalid_media_type_fails(self):
        payload = _make_plan_payload()
        payload["media_type"] = ["photo"]
        with pytest.raises(Exception):
            validate_payload("edit_plan", "3.0", payload)

    def test_missing_audio_track_is_valid(self):
        """audio_track is optional in edit_plan 3.0."""
        payload = _make_plan_payload(audio_track=None)
        validate_payload("edit_plan", "3.0", payload)

    def test_audio_track_passes_schema(self):
        payload = _make_plan_payload(audio_track=_make_audio_track())
        validate_payload("edit_plan", "3.0", payload)


# ---------------------------------------------------------------------------
# Semantic validation
# ---------------------------------------------------------------------------

class TestMixedMediaSemanticValidation:
    """Test load_and_validate_mixed_media_plan."""

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Path:
        ws = tmp_path / "workspace"
        ws.mkdir()
        # Create placeholder source files
        (ws / "photos").mkdir()
        (ws / "videos").mkdir()
        # Minimal valid JPEG (1x1 pixel, white)
        minimal_jpeg = bytes([
            0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46,
            0x49, 0x46, 0x00, 0x01, 0x01, 0x00, 0x00, 0x01,
            0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
            0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08,
            0x07, 0x07, 0x07, 0x09, 0x09, 0x08, 0x0A, 0x0C,
            0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
            0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D,
            0x1A, 0x1C, 0x1C, 0x20, 0x24, 0x2E, 0x27, 0x20,
            0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
            0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27,
            0x39, 0x3D, 0x38, 0x32, 0x3C, 0x2E, 0x33, 0x34,
            0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
            0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4,
            0x00, 0x1F, 0x00, 0x00, 0x01, 0x05, 0x01, 0x01,
            0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04,
            0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0xFF,
            0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01, 0x03,
            0x03, 0x02, 0x04, 0x03, 0x05, 0x05, 0x04, 0x04,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01,
            0x02, 0x03, 0x11, 0x04, 0x05, 0x21, 0x31, 0x12,
            0x41, 0x51, 0x06, 0x61, 0x71, 0x13, 0x22, 0x32,
            0x81, 0x08, 0x14, 0x42, 0x91, 0xA1, 0xB1, 0xC1,
            0x09, 0x23, 0x33, 0x52, 0xF0, 0x15, 0x62, 0x72,
            0xD1, 0x0A, 0x16, 0x24, 0x34, 0xE1, 0x25, 0xF1,
            0x17, 0x18, 0x19, 0x1A, 0x26, 0x27, 0x28, 0x29,
            0x2A, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3A, 0x43,
            0x44, 0x45, 0x46, 0x47, 0x48, 0x49, 0x4A, 0x53,
            0x54, 0x55, 0x56, 0x57, 0x58, 0x59, 0x5A, 0x63,
            0x64, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6A, 0x73,
            0x74, 0x75, 0x76, 0x77, 0x78, 0x79, 0x7A, 0x83,
            0x84, 0x85, 0x86, 0x87, 0x88, 0x89, 0x8A, 0x92,
            0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9A,
            0xA2, 0xA3, 0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xA9,
            0xAA, 0xB2, 0xB3, 0xB4, 0xB5, 0xB6, 0xB7, 0xB8,
            0xB9, 0xBA, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7,
            0xC8, 0xC9, 0xCA, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6,
            0xD7, 0xD8, 0xD9, 0xDA, 0xE1, 0xE2, 0xE3, 0xE4,
            0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xF1, 0xF2,
            0xF3, 0xF4, 0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0xFA,
            0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00,
            0x3F, 0x00, 0x7B, 0x94, 0x11, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0xFF, 0xD9,
        ])
        (ws / "photos" / "photo1.jpg").write_bytes(minimal_jpeg)
        # Create a minimal valid MP4 using ffmpeg
        _create_minimal_mp4(ws / "videos" / "clip1.mp4")
        # Compute real sha256 and size of the placeholder files
        photo_path = ws / "photos" / "photo1.jpg"
        video_path = ws / "videos" / "clip1.mp4"
        photo_sha = compute_sha256(photo_path)
        video_sha = compute_sha256(video_path)
        # Create a minimal local asset registry with correct checksums
        registry = {
            "version": "1.0",
            "assets": [
                {
                    "asset_id": "photo-1",
                    "source_path": str(photo_path),
                    "sha256": photo_sha,
                    "size_bytes": photo_path.stat().st_size,
                },
                {
                    "asset_id": "video-1",
                    "source_path": str(video_path),
                    "sha256": video_sha,
                    "size_bytes": video_path.stat().st_size,
                },
            ],
        }
        (ws / "analysis").mkdir(parents=True)
        (ws / "analysis" / "local_asset_registry.json").write_text(
            json.dumps(registry, ensure_ascii=False), encoding="utf-8"
        )
        return ws

    @pytest.fixture
    def package_root(self, tmp_path: Path) -> Path:
        pr = tmp_path / "package"
        pr.mkdir()
        (pr / "audio").mkdir(parents=True, exist_ok=True)
        (pr / "audio" / "track.mp3").write_bytes(b"fake-mp3")
        return pr

    @pytest.fixture
    def backend(self, workspace: Path) -> FFmpegBackend:
        return FFmpegBackend(project_root=workspace)

    def _write_plan(self, package_root: Path, payload: dict) -> Path:
        plan_dir = package_root / "plans"
        plan_dir.mkdir(exist_ok=True)
        plan_path = plan_dir / "plan-mm-1.json"
        plan_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return plan_path

    def test_valid_mixed_media_plan(self, workspace, package_root, backend):
        # Use correct sha256 and size from the actual workspace files
        photo_path = workspace / "photos" / "photo1.jpg"
        video_path = workspace / "videos" / "clip1.mp4"
        photo_sha = compute_sha256(photo_path)
        video_sha = compute_sha256(video_path)
        # The minimal MP4 is 100ms long, so trim must be within that range
        payload = _make_plan_payload(
            assets=[
                {
                    "asset_id": "photo-1",
                    "media_type": "photo",
                    "source_path": str(photo_path),
                    "sha256": photo_sha,
                    "size_bytes": photo_path.stat().st_size,
                },
                {
                    "asset_id": "video-1",
                    "media_type": "video",
                    "source_path": str(video_path),
                    "sha256": video_sha,
                    "size_bytes": video_path.stat().st_size,
                },
            ],
            operations=[
                {
                    "op": "image_hold",
                    "asset_id": "photo-1",
                    "duration_ms": 3000,
                },
                {
                    "op": "video_segment",
                    "asset_id": "video-1",
                    "source_in_ms": 0,
                    "source_out_ms": 100,  # 100ms video
                    "mute_original_audio": True,
                },
            ],
        )
        plan_path = self._write_plan(package_root, payload)
        manifest = _make_manifest()
        validated = load_and_validate_mixed_media_plan(
            plan_path, workspace, package_root, backend, manifest,
        )
        assert isinstance(validated, ValidatedMixedMediaPlan)
        assert len(validated.assets) == 2
        assert len(validated.operations) == 2
        assert validated.operations[0].op == "image_hold"
        assert validated.operations[1].op == "video_segment"
        assert validated.operations[1].mute_original_audio is True
        assert validated.planned_duration_ms == 3100  # 3000 + 100

    def test_plan_with_audio_track(self, workspace, package_root, backend):
        audio = _make_audio_track()
        photo_path = workspace / "photos" / "photo1.jpg"
        video_path = workspace / "videos" / "clip1.mp4"
        photo_sha = compute_sha256(photo_path)
        video_sha = compute_sha256(video_path)
        payload = _make_plan_payload(
            audio_track=audio,
            assets=[
                {
                    "asset_id": "photo-1",
                    "media_type": "photo",
                    "source_path": str(photo_path),
                    "sha256": photo_sha,
                    "size_bytes": photo_path.stat().st_size,
                },
                {
                    "asset_id": "video-1",
                    "media_type": "video",
                    "source_path": str(video_path),
                    "sha256": video_sha,
                    "size_bytes": video_path.stat().st_size,
                },
            ],
            operations=[
                {
                    "op": "image_hold",
                    "asset_id": "photo-1",
                    "duration_ms": 3000,
                },
                {
                    "op": "video_segment",
                    "asset_id": "video-1",
                    "source_in_ms": 0,
                    "source_out_ms": 100,  # 100ms video
                    "mute_original_audio": True,
                },
            ],
        )
        plan_path = self._write_plan(package_root, payload)
        manifest = _make_manifest(audio_track=audio)
        validated = load_and_validate_mixed_media_plan(
            plan_path, workspace, package_root, backend, manifest,
        )
        assert validated.audio_track is not None
        assert validated.audio_track["path"] == "audio/track.mp3"
        assert validated.audio_gain == 0.8

    def test_plan_without_audio_track(self, workspace, package_root, backend):
        photo_path = workspace / "photos" / "photo1.jpg"
        video_path = workspace / "videos" / "clip1.mp4"
        photo_sha = compute_sha256(photo_path)
        video_sha = compute_sha256(video_path)
        payload = _make_plan_payload(
            audio_track=None,
            assets=[
                {
                    "asset_id": "photo-1",
                    "media_type": "photo",
                    "source_path": str(photo_path),
                    "sha256": photo_sha,
                    "size_bytes": photo_path.stat().st_size,
                },
                {
                    "asset_id": "video-1",
                    "media_type": "video",
                    "source_path": str(video_path),
                    "sha256": video_sha,
                    "size_bytes": video_path.stat().st_size,
                },
            ],
            operations=[
                {
                    "op": "image_hold",
                    "asset_id": "photo-1",
                    "duration_ms": 3000,
                },
                {
                    "op": "video_segment",
                    "asset_id": "video-1",
                    "source_in_ms": 0,
                    "source_out_ms": 100,
                    "mute_original_audio": True,
                },
            ],
        )
        plan_path = self._write_plan(package_root, payload)
        manifest = _make_manifest()
        validated = load_and_validate_mixed_media_plan(
            plan_path, workspace, package_root, backend, manifest,
        )
        assert validated.audio_track is None
        assert validated.audio_gain == 1.0

    def test_missing_asset_in_registry_fails(self, workspace, package_root, backend):
        payload = _make_plan_payload(assets=[
            {
                "asset_id": "photo-unknown",
                "media_type": "photo",
                "source_path": "C:/nonexistent.jpg",
                "sha256": "f" * 64,
                "size_bytes": 999,
            },
        ])
        plan_path = self._write_plan(package_root, payload)
        manifest = _make_manifest()
        with pytest.raises(UnsafePackageError, match="missing asset_id"):
            load_and_validate_mixed_media_plan(
                plan_path, workspace, package_root, backend, manifest,
            )

    def test_invalid_trim_range_fails(self, workspace, package_root, backend):
        photo_path = workspace / "photos" / "photo1.jpg"
        video_path = workspace / "videos" / "clip1.mp4"
        photo_sha = compute_sha256(photo_path)
        video_sha = compute_sha256(video_path)
        payload = _make_plan_payload(
            assets=[
                {
                    "asset_id": "photo-1",
                    "media_type": "photo",
                    "source_path": str(photo_path),
                    "sha256": photo_sha,
                    "size_bytes": photo_path.stat().st_size,
                },
                {
                    "asset_id": "video-1",
                    "media_type": "video",
                    "source_path": str(video_path),
                    "sha256": video_sha,
                    "size_bytes": video_path.stat().st_size,
                },
            ],
            operations=[
                {
                    "op": "video_segment",
                    "asset_id": "video-1",
                    "source_in_ms": 5000,
                    "source_out_ms": 1000,  # negative duration (source_out < source_in)
                    "mute_original_audio": True,
                },
            ],
        )
        plan_path = self._write_plan(package_root, payload)
        manifest = _make_manifest()
        with pytest.raises(UnsafePackageError, match="source_out_ms"):
            load_and_validate_mixed_media_plan(
                plan_path, workspace, package_root, backend, manifest,
            )

    def test_forbidden_keys_rejected(self, workspace, package_root, backend):
        # Schema 3.0 has additionalProperties: false everywhere,
        # so forbidden keys are caught by schema validation before _reject_forbidden_keys.
        # This test verifies that _reject_forbidden_keys works on a payload
        # that passes schema validation but contains a forbidden key in a value.
        # We use a string value that contains a forbidden key name.
        photo_path = workspace / "photos" / "photo1.jpg"
        video_path = workspace / "videos" / "clip1.mp4"
        photo_sha = compute_sha256(photo_path)
        video_sha = compute_sha256(video_path)
        payload = _make_plan_payload(
            assets=[
                {
                    "asset_id": "photo-1",
                    "media_type": "photo",
                    "source_path": str(photo_path),
                    "sha256": photo_sha,
                    "size_bytes": photo_path.stat().st_size,
                },
                {
                    "asset_id": "video-1",
                    "media_type": "video",
                    "source_path": str(video_path),
                    "sha256": video_sha,
                    "size_bytes": video_path.stat().st_size,
                },
            ],
            operations=[
                {
                    "op": "image_hold",
                    "asset_id": "photo-1",
                    "duration_ms": 3000,
                },
                {
                    "op": "video_segment",
                    "asset_id": "video-1",
                    "source_in_ms": 0,
                    "source_out_ms": 100,
                    "mute_original_audio": True,
                },
            ],
        )
        # Add a forbidden key inside the payload dict (bypasses schema validation
        # because we add it after schema validation would check, but _reject_forbidden_keys
        # runs after schema validation). Actually schema validation catches it first.
        # Instead, test _reject_forbidden_keys directly.
        from handoff_builder.v2.plans.semantic import _reject_forbidden_keys
        with pytest.raises(UnsafePackageError, match="Forbidden"):
            _reject_forbidden_keys({"ffmpeg": "evil"})
        with pytest.raises(UnsafePackageError, match="Forbidden"):
            _reject_forbidden_keys({"nested": {"ffmpeg_args": "-i test"}})
        with pytest.raises(UnsafePackageError, match="Forbidden"):
            _reject_forbidden_keys({"list": [{"filter_complex": "overlay"}]})
        # Allowed keys should not raise
        _reject_forbidden_keys({"op": "image_hold", "duration_ms": 3000})


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------

class TestMixedMediaCompiler:
    """Test compile_mixed_media_render_plan."""

    @pytest.fixture
    def validated_plan(self, tmp_path) -> ValidatedMixedMediaPlan:
        from PIL import Image
        from handoff_builder.v2.plans.semantic import (
            ValidatedMixedMediaAsset,
            ValidatedMixedMediaOperation,
        )
        # Create real temporary files
        photo_path = tmp_path / "photo1.png"
        Image.new("RGB", (1, 1), color="white").save(photo_path, "PNG")
        video_path = tmp_path / "clip1.mp4"
        _create_minimal_mp4(video_path)

        assets = {
            "photo-1": ValidatedMixedMediaAsset(
                asset_id="photo-1",
                path=photo_path,
                media_type="photo",
                duration_ms=0,
                width=1,
                height=1,
                rotation=0,
                has_audio=False,
            ),
            "video-1": ValidatedMixedMediaAsset(
                asset_id="video-1",
                path=video_path,
                media_type="video",
                duration_ms=5000,
                width=2,
                height=2,
                rotation=0,
                has_audio=False,
            ),
        }
        operations = [
            ValidatedMixedMediaOperation(
                op="image_hold",
                asset_id="photo-1",
                duration_ms=3000,
                source_in_ms=None,
                source_out_ms=None,
                mute_original_audio=False,
            ),
            ValidatedMixedMediaOperation(
                op="video_segment",
                asset_id="video-1",
                source_in_ms=0,
                source_out_ms=5000,
                mute_original_audio=True,
                duration_ms=5000,
            ),
        ]
        return ValidatedMixedMediaPlan(
            payload={},
            assets=assets,
            operations=operations,
            planned_duration_ms=8000,
            output_width=1080,
            output_height=1920,
            output_fps=30,
            audio_track=None,
            audio_gain=1.0,
        )

    @pytest.fixture
    def validated_plan_with_audio(self, tmp_path) -> ValidatedMixedMediaPlan:
        from PIL import Image
        from handoff_builder.v2.plans.semantic import (
            ValidatedMixedMediaAsset,
            ValidatedMixedMediaOperation,
        )
        # Create real temporary files
        photo_path = tmp_path / "photo1.png"
        Image.new("RGB", (1, 1), color="white").save(photo_path, "PNG")
        video_path = tmp_path / "clip1.mp4"
        _create_minimal_mp4(video_path)

        assets = {
            "photo-1": ValidatedMixedMediaAsset(
                asset_id="photo-1",
                path=photo_path,
                media_type="photo",
                duration_ms=0,
                width=1,
                height=1,
                rotation=0,
                has_audio=False,
            ),
            "video-1": ValidatedMixedMediaAsset(
                asset_id="video-1",
                path=video_path,
                media_type="video",
                duration_ms=5000,
                width=2,
                height=2,
                rotation=0,
                has_audio=False,
            ),
        }
        operations = [
            ValidatedMixedMediaOperation(
                op="image_hold",
                asset_id="photo-1",
                duration_ms=3000,
                source_in_ms=None,
                source_out_ms=None,
                mute_original_audio=False,
            ),
            ValidatedMixedMediaOperation(
                op="video_segment",
                asset_id="video-1",
                source_in_ms=0,
                source_out_ms=5000,
                mute_original_audio=True,
                duration_ms=5000,
            ),
        ]
        return ValidatedMixedMediaPlan(
            payload={},
            assets=assets,
            operations=operations,
            planned_duration_ms=8000,
            output_width=1080,
            output_height=1920,
            output_fps=30,
            audio_track={"path": "audio/track.mp3", "sha256": "c" * 64, "size_bytes": 4096},
            audio_gain=0.8,
        )

    def test_compiler_returns_compiled_plan(self, validated_plan, tmp_path):
        output_path = tmp_path / "reel.mp4"
        compiled = compile_mixed_media_render_plan(
            validated_plan,
            ffmpeg_path="ffmpeg",
            output_path=output_path,
        )
        assert compiled.ffmpeg_args is not None
        assert len(compiled.ffmpeg_args) > 0
        assert compiled.ffmpeg_args[0] == "ffmpeg"
        assert "-y" in compiled.ffmpeg_args
        assert compiled.render_plan["output"]["width"] == 1080
        assert compiled.render_plan["output"]["height"] == 1920
        assert compiled.render_plan["output"]["fps"] == 30

    def test_compiler_with_audio_track(self, validated_plan_with_audio, tmp_path):
        output_path = tmp_path / "reel_with_audio.mp4"
        compiled = compile_mixed_media_render_plan(
            validated_plan_with_audio,
            ffmpeg_path="ffmpeg",
            output_path=output_path,
            package_root=tmp_path,
        )
        # Should include audio input args
        args_str = " ".join(compiled.ffmpeg_args)
        assert "volume" in args_str or "audio" in args_str.lower()

    def test_compiler_without_audio(self, validated_plan, tmp_path):
        output_path = tmp_path / "reel_no_audio.mp4"
        compiled = compile_mixed_media_render_plan(
            validated_plan,
            ffmpeg_path="ffmpeg",
            output_path=output_path,
        )
        args_str = " ".join(compiled.ffmpeg_args)
        # Should NOT reference audio
        assert "volume" not in args_str


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

class TestMixedMediaGuards:
    """Test that guards handle 3.0 correctly."""

    def test_reject_media_payloads_allows_audio_for_3_0(self, tmp_path):
        from handoff_builder.v2.packages.guards import reject_media_payloads
        # Create a minimal package dir with only audio (should be allowed for 3.0)
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "audio").mkdir()
        (pkg / "audio" / "track.mp3").write_bytes(b"fake-mp3")
        (pkg / "plans").mkdir()
        (pkg / "plans" / "plan.json").write_text("{}")
        # Should not raise for 3.0 with allow_audio=True
        reject_media_payloads(pkg, allow_audio=True)

    def test_reject_media_payloads_rejects_audio_for_2_0(self, tmp_path):
        from handoff_builder.v2.packages.guards import reject_media_payloads
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "audio").mkdir()
        (pkg / "audio" / "track.mp3").write_bytes(b"fake-mp3")
        (pkg / "plans").mkdir()
        (pkg / "plans" / "plan.json").write_text("{}")
        # Without allow_audio=True, audio files should be rejected
        with pytest.raises(UnsafePackageError):
            reject_media_payloads(pkg, allow_audio=False)

    def test_allowed_prefixes_includes_audio(self):
        from handoff_builder.v2.packages.guards import ensure_allowed_package_path
        # Should not raise for audio/ prefix
        ensure_allowed_package_path("audio/track.mp3")
        ensure_allowed_package_path("audio/subdir/track.wav")


# ---------------------------------------------------------------------------
# Importer audio validation
# ---------------------------------------------------------------------------

class TestMixedMediaImporter:
    """Test that importer validates audio_track for 3.0."""

    def test_importer_validates_audio_checksum(self, tmp_path):
        from handoff_builder.v2.packages.importer import import_edit_package

        # Build a minimal 3.0 package with audio
        package_dir = tmp_path / "package_src"
        package_dir.mkdir()
        (package_dir / "plans").mkdir()
        (package_dir / "audio").mkdir()

        plan_payload = _make_plan_payload(audio_track=_make_audio_track())
        plan_bytes = json.dumps(plan_payload, ensure_ascii=False).encode("utf-8")
        plan_sha = hashlib.sha256(plan_bytes).hexdigest()
        (package_dir / "plans" / "plan-mm-1.json").write_bytes(plan_bytes)

        audio_bytes = b"fake-mp3-content"
        audio_sha = hashlib.sha256(audio_bytes).hexdigest()
        (package_dir / "audio" / "track.mp3").write_bytes(audio_bytes)

        manifest = _make_manifest(
            plan_sha256=plan_sha,
            plan_size=len(plan_bytes),
            audio_track=_make_audio_track(path="audio/track.mp3"),
        )
        # Fix audio sha256 in manifest to match actual content
        manifest["audio_track"]["sha256"] = audio_sha
        manifest["audio_track"]["size_bytes"] = len(audio_bytes)

        (package_dir / "ai_edit_package.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )

        # Zip it
        zip_path = tmp_path / "test_package.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in package_dir.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(package_dir))

        # Import (package_root will be created by import_edit_package)
        result = import_edit_package(
            zip_path,
            tmp_path / "packages",
            expected_project_id="proj-mm-1",
            package_root=tmp_path / "extracted",
        )
        assert result.schema_version == "3.0"
        assert result.package_id is not None

    def test_importer_rejects_checksum_mismatch(self, tmp_path):
        from handoff_builder.v2.packages.importer import import_edit_package

        package_dir = tmp_path / "package_src"
        package_dir.mkdir()
        (package_dir / "plans").mkdir()
        (package_dir / "audio").mkdir()

        plan_payload = _make_plan_payload(audio_track=_make_audio_track())
        plan_bytes = json.dumps(plan_payload, ensure_ascii=False).encode("utf-8")
        plan_sha = hashlib.sha256(plan_bytes).hexdigest()
        (package_dir / "plans" / "plan-mm-1.json").write_bytes(plan_bytes)

        audio_bytes = b"fake-mp3-content"
        (package_dir / "audio" / "track.mp3").write_bytes(audio_bytes)

        manifest = _make_manifest(
            plan_sha256=plan_sha,
            plan_size=len(plan_bytes),
            audio_track=_make_audio_track(path="audio/track.mp3"),
        )
        # Intentionally wrong checksum
        manifest["audio_track"]["sha256"] = "f" * 64

        (package_dir / "ai_edit_package.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )

        zip_path = tmp_path / "bad_audio_package.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in package_dir.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(package_dir))

        extract_root = tmp_path / "extracted_bad"
        extract_root.mkdir()
        with pytest.raises(UnsafePackageError, match="checksum|sha256|mismatch"):
            import_edit_package(
                zip_path,
                tmp_path / "packages_bad",
                expected_project_id="proj-mm-1",
                package_root=extract_root,
            )
