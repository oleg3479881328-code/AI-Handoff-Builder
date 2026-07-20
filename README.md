# AI Handoff Builder v1

A small standalone Windows application that prepares wedding photo/video materials for visual analysis and editing in ChatGPT.

## What it does

Input:

- ZIP archive;
- folder;
- several folders;
- individual photo/video files.

Output:

```text
PROJECT_ANALYSIS_HANDOFF.zip
├── handoff_manifest.json
├── scene_manifest.json
├── validation_report.json
├── README.txt
├── photo_analysis_copies/
├── video_proxies/
├── scene_keyframes/
├── scene_previews/
├── video_storyboards/
└── contact_sheets/
```

## Critical coverage rule

No video is allowed to disappear silently.

- Short video (≤12 seconds): one full-video scene, one keyframe, one preview.
- Longer video: detected cuts when available.
- If cuts are not found: uniform coverage segments across the entire duration.
- Every video must have at least one keyframe and one preview.
- Every photo must have one resized analysis copy.
- `validation_report.json` reports missing coverage.

## Windows quick start

1. Install Python 3.11+.
2. Install FFmpeg and add `ffmpeg.exe` / `ffprobe.exe` to PATH, or place them in `bin\`.
3. Double-click `run_windows.bat`.
4. Add ZIP/folder/files.
5. Select output directory.
6. Click **ПОДГОТОВИТЬ ДЛЯ CHATGPT**.

## Command line

```bash
python -m handoff_builder.cli ^
  --project "JEFF BREANNA" ^
  --output "C:\1VIDEO MIX\handoff" ^
  --input "C:\1VIDEO MIX\source"
```

Use `--no-proxies` to make a smaller ZIP.

## Current MVP boundaries

Implemented:

- safe ZIP extraction;
- recursive media scan;
- stable IDs;
- photo resize and EXIF rotation;
- ffprobe metadata;
- 720p proxy generation;
- FFmpeg scene-cut detection;
- uniform fallback coverage;
- keyframes;
- preview clips;
- per-video storyboards;
- global contact sheets;
- manifests;
- strict coverage validation;
- final ZIP;
- GUI and CLI.

Still recommended for the executor:

- package and test the Windows EXE;
- add cancel/retry/pause;
- persist job state after restart;
- add HEIC support bundle;
- add drag-and-drop shell integration;
- optimize speed with bounded parallel workers;
- add application icon and installer;
- browser-level/manual smoke test on the real 67-video wedding set.
