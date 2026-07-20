# Execution packet — finish AI Handoff Builder v1 on Windows

Выполняй сейчас.

## Goal

Turn the supplied MVP into a stable Windows portable application:

```text
ZIP / folder / files
→ one click
→ complete PROJECT_ANALYSIS_HANDOFF.zip
```

The application is separate from the large VIDEO MIX system. Do not add databases, AI models, final editing, or publishing in this task.

## Existing implementation

Already implemented:

- Tkinter GUI;
- CLI;
- safe ZIP extraction;
- recursive media registry;
- photo EXIF rotation and 1280px analysis copies;
- ffprobe metadata;
- optional 720p video proxies;
- FFmpeg scene-cut detection;
- one-scene treatment for videos ≤12 seconds;
- uniform coverage for long videos with no detected cuts;
- keyframes;
- short previews;
- per-video storyboards;
- contact sheets;
- JSON manifests;
- strict validation;
- final ZIP.

## Required Windows work

1. Create a clean branch.
2. Run the app against a real mixed folder and the JEFF BREANNA source set.
3. Fix all Windows path/Unicode/FFmpeg issues.
4. Ensure every one of 67 videos has:
   - at least one manifest scene/coverage segment;
   - at least one keyframe;
   - at least one preview;
   - a storyboard.
5. Ensure every photo from every source folder has an analysis copy.
6. Package a portable build with PyInstaller.
7. Bundle or clearly locate:
   - `ffmpeg.exe`;
   - `ffprobe.exe`.
8. Add bounded parallel processing (2 workers by default) only if it is stable.
9. Add cancel and retry-failed.
10. Add a final summary screen:

```text
67 videos found
67 videos represented
N photos found
N photos represented
0 lost files
Coverage OK
```

11. The Export result must never show green success when `coverage_ok=false`.
12. Add tests for:
   - ZIP traversal rejection;
   - short video single scene;
   - long no-cut video uniform coverage;
   - failed file remains visible in validation;
   - all artifact paths exist;
   - Unicode Windows paths.

## Acceptance criteria

- One-click workflow works on Windows 11.
- Input can be ZIP, folder, or selected files.
- Originals are never modified.
- No `shell=True`.
- No silent asset loss.
- The final ZIP opens and contains all required folders/manifests.
- `validation_report.json.coverage_ok=true` on a successful complete run.
- App remains responsive during processing.
- Portable EXE launches on a clean Windows user profile.
- Provide exact test commands, screenshots, final ZIP sample, and SHA-256.
- Do not merge without user authorization.
