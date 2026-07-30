from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
import ctypes
import ctypes.wintypes as wt
from pathlib import Path

import pyautogui
import pygetwindow as gw
from PIL import Image

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.2


EXE_PATH = Path(r"C:\Users\oleg3\Documents\AI Handoff Builder issue25\dist\AI Handoff Builder\AI Handoff Builder.exe")
REPO_ROOT = Path(r"C:\Users\oleg3\Documents\AI Handoff Builder issue25")
SEED_IMAGE = REPO_ROOT / "tmp_issue27_one_json_acceptance" / "source" / "cover.jpg"
TEMP_ROOT = Path(r"C:\Users\oleg3\Documents\AIHB_issue27_packaged_acceptance_final")
PROJECT_NAME = "Каролина And RÖB"
SOURCE_ZIP = TEMP_ROOT / f"{PROJECT_NAME}.zip"
OVERSIZE_JSON = TEMP_ROOT / f"{PROJECT_NAME}_oversized.json"
VALID_JSON = TEMP_ROOT / f"{PROJECT_NAME}.json"
EVIDENCE_DIR = TEMP_ROOT / "evidence"
STATUS_PATH = TEMP_ROOT / "_packaged_acceptance" / "status.json"
EVENTS_PATH = TEMP_ROOT / "_packaged_acceptance" / "events.jsonl"
REPORT_PATH = EVIDENCE_DIR / "acceptance_report.json"

PW_RENDERFULLCONTENT = 2
DIB_RGB_COLORS = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD),
        ("biWidth", wt.LONG),
        ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD),
        ("biBitCount", wt.WORD),
        ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD),
        ("biXPelsPerMeter", wt.LONG),
        ("biYPelsPerMeter", wt.LONG),
        ("biClrUsed", wt.DWORD),
        ("biClrImportant", wt.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wt.DWORD * 3),
    ]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def kill_process(name: str) -> None:
    image_name = f"{name}.exe" if not name.lower().endswith(".exe") else name
    subprocess.run(
        ["taskkill", "/IM", image_name, "/F", "/T"],
        check=False,
        capture_output=True,
        text=True,
    )


def _visible_window_for_pid(pid: int):
    user32 = ctypes.windll.user32
    windows: list[int] = []
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def callback(hwnd, lparam):
        current_pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(current_pid))
        if current_pid.value == pid and user32.IsWindowVisible(hwnd):
            windows.append(int(hwnd))
        return True

    user32.EnumWindows(enum_proc(callback), 0)
    for hwnd in windows:
        title = gw.Win32Window(hwnd).title.strip()
        if title == "AI Handoff Builder":
            return gw.Win32Window(hwnd)
    if windows:
        return gw.Win32Window(windows[0])
    return None


def wait_for_window(title: str, timeout: float = 20.0, pid: int | None = None):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pid is not None:
            window = _visible_window_for_pid(pid)
            if window is not None:
                return window
        windows = [window for window in gw.getWindowsWithTitle(title) if window.title == title]
        if windows:
            return windows[0]
        time.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for window: {title}")


def wait_for_file(path: Path, timeout: float = 60.0) -> Path:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            return path
        time.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for file: {path}")


def wait_for_status(stages: set[str], timeout: float = 180.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if STATUS_PATH.exists():
            payload = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
            if payload.get("stage") in stages:
                return payload
        time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for stages {sorted(stages)}")


def _capture_hwnd_to_path(hwnd: int, path: Path) -> None:
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    rect = wt.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise OSError(f"GetWindowRect failed for hwnd={hwnd}")
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        raise OSError(f"Invalid capture size for hwnd={hwnd}: {width}x{height}")
    window_dc = user32.GetWindowDC(hwnd)
    if not window_dc:
        raise OSError(f"GetWindowDC failed for hwnd={hwnd}")
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    previous = gdi32.SelectObject(memory_dc, bitmap)
    try:
        ok = user32.PrintWindow(hwnd, memory_dc, PW_RENDERFULLCONTENT)
        if ok != 1:
            raise OSError(f"PrintWindow failed for hwnd={hwnd}")
        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0
        buffer = ctypes.create_string_buffer(width * height * 4)
        bits = gdi32.GetDIBits(
            memory_dc,
            bitmap,
            0,
            height,
            buffer,
            ctypes.byref(info),
            DIB_RGB_COLORS,
        )
        if bits != height:
            raise OSError(f"GetDIBits failed for hwnd={hwnd}: expected {height}, got {bits}")
        image = Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1)
        image.save(path)
    finally:
        gdi32.SelectObject(memory_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, window_dc)


def discover_capture_hwnd(exclude_titles: set[str] | None = None) -> int:
    exclude_titles = exclude_titles or set()
    foreground = int(ctypes.windll.user32.GetForegroundWindow())
    if foreground:
        return foreground
    for window in gw.getAllWindows():
        title = (window.title or "").strip()
        if not title or title in exclude_titles:
            continue
        return int(window._hWnd)
    raise OSError("No window available for capture.")


def screenshot(name: str, hwnd: int | None = None) -> Path:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE_DIR / name
    if hwnd is None:
        hwnd = discover_capture_hwnd(exclude_titles={"AI Handoff Builder"})
    _capture_hwnd_to_path(hwnd, path)
    return path


def window_point(window, dx: int, dy: int) -> tuple[int, int]:
    return (window.left + dx, window.top + dy)


def launch_app(env: dict[str, str] | None = None):
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.Popen([str(EXE_PATH)], env=merged_env)


def close_foreground_dialog() -> None:
    pyautogui.press("esc")
    time.sleep(1.0)


def prepare_inputs() -> None:
    kill_process("AI Handoff Builder")
    kill_process("shotcut")
    if TEMP_ROOT.exists():
        shutil.rmtree(TEMP_ROOT)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SEED_IMAGE, TEMP_ROOT / "cover.jpg")
    with zipfile.ZipFile(SOURCE_ZIP, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(TEMP_ROOT / "cover.jpg", arcname="cover.jpg")
    OVERSIZE_JSON.write_text('{"padding":"' + ("X" * (10 * 1024 * 1024 + 1024)) + '"}', encoding="utf-8")


def collect_normal_dialog_evidence() -> dict[str, str]:
    process = launch_app()
    time.sleep(4)
    window = wait_for_window("AI Handoff Builder", pid=process.pid)
    try:
        window.restore()
    except Exception:
        pass
    pyautogui.click(window.left + 120, window.top + 40)
    time.sleep(1)
    screenshot("01-packaged-app-normal.png", hwnd=int(window._hWnd))

    pyautogui.click(*window_point(window, 220, 323))
    time.sleep(2)
    v1_dialog = screenshot("02-v1-native-file-dialog.png")
    close_foreground_dialog()

    pyautogui.doubleClick(*window_point(window, 320, 180))
    time.sleep(1)
    pyautogui.click(*window_point(window, 210, 407))
    time.sleep(2)
    v2_dialog = screenshot("03-v2-native-json-dialog.png")
    close_foreground_dialog()
    kill_process("AI Handoff Builder")
    process.wait(timeout=10)
    return {
        "v1_dialog": str(v1_dialog),
        "v2_dialog": str(v2_dialog),
    }


def run_acceptance_mode(plan_path: Path, screenshot_name: str, terminal_stages: set[str]) -> dict:
    kill_process("AI Handoff Builder")
    if STATUS_PATH.exists():
        STATUS_PATH.unlink()
    if EVENTS_PATH.exists():
        EVENTS_PATH.unlink()
    env = {
        "AIHB_PACKAGED_ACCEPTANCE": "1",
        "AIHB_ACCEPTANCE_SOURCE_ZIP": str(SOURCE_ZIP),
        "AIHB_ACCEPTANCE_EDIT_PLAN_JSON": str(plan_path),
        "AIHB_ACCEPTANCE_OUTPUT_DIR": str(TEMP_ROOT),
    }
    process = launch_app(env)
    status = wait_for_status(terminal_stages, timeout=240)
    time.sleep(2)
    screenshot(screenshot_name)
    kill_process("AI Handoff Builder")
    process.wait(timeout=10)
    return status


def latest_handoff_manifest() -> Path:
    manifests = sorted(TEMP_ROOT.rglob("handoff_manifest.json"), key=lambda path: path.stat().st_mtime)
    if not manifests:
        raise FileNotFoundError("handoff_manifest.json not found under acceptance temp root.")
    return manifests[-1]


def build_valid_plan_from_manifest(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    asset = manifest["asset_selection"]["assets"][0]
    return {
        "schema_version": "3.0",
        "document_type": "edit_plan",
        "project_id": manifest["project_id"],
        "project_name": manifest["project_name"],
        "handoff_id": manifest["handoff_id"],
        "handoff_content_hash": manifest["content_hash"],
        "plan_id": "plan-packaged-acceptance-1",
        "plan_version": 1,
        "canvas": {"width": 1080, "height": 1920},
        "timebase": {"fps_num": 30, "fps_den": 1},
        "assets": [
            {
                "asset_id": asset["asset_id"],
                "media_type": asset["media_type"],
                "original_name": asset.get("original_name") or "cover.jpg",
            }
        ],
        "visual_items": [
            {
                "item_id": "photo-1",
                "asset_id": asset["asset_id"],
                "media_type": asset["media_type"],
                "track_id": "V1",
                "timeline_start_frame": 0,
                "duration_frames": 90,
                "source_in_us": 0,
                "source_out_us": 0,
                "source_audio_policy": "discard",
                "transform": {"scale_x": 1.1, "scale_y": 1.1, "position_x": 0.5, "position_y": 0.5},
                "crop": {"left": 10, "top": 20, "right": 30, "bottom": 40},
            }
        ],
        "audio_items": [],
        "text_items": [
            {
                "item_id": "title-1",
                "text": "Opening",
                "timeline_start_frame": 0,
                "duration_frames": 90,
            }
        ],
        "renderer": {"primary_renderer": "shotcut", "capabilities": []},
    }


def latest_file(pattern: str) -> Path:
    matches = sorted(TEMP_ROOT.rglob(pattern), key=lambda path: path.stat().st_mtime)
    if not matches:
        raise FileNotFoundError(pattern)
    return matches[-1]


def inspect_results() -> dict:
    manifest_path = latest_handoff_manifest()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    imported_plan_path = latest_file(f"{PROJECT_NAME}.json")
    build_summary_path = latest_file("build_summary.json")
    build_summary = json.loads(build_summary_path.read_text(encoding="utf-8"))
    normalized_path = latest_file("normalized_timeline.json")
    normalized_payload = json.loads(normalized_path.read_text(encoding="utf-8"))
    mlt_path = Path(build_summary["project_path"])
    mlt_text = mlt_path.read_text(encoding="utf-8")
    inspect_project = build_summary.get("inspect_result") or {}
    timeline_duration_frames = int((inspect_project.get("duration_frames") or 0))
    return {
        "manifest_path": str(manifest_path),
        "manifest": manifest,
        "imported_plan_path": str(imported_plan_path),
        "imported_plan_sha256": sha256(imported_plan_path),
        "normalized_timeline_path": str(normalized_path),
        "normalized_timeline_hash": normalized_payload.get("normalized_timeline_hash"),
        "build_summary_path": str(build_summary_path),
        "build_summary": build_summary,
        "mlt_path": str(mlt_path),
        "mlt_sha256": sha256(mlt_path),
        "mlt_contains_crop": "shotcut_filter\" value=\"crop" in mlt_text or "mlt_service\">crop<" in mlt_text or "service\">crop<" in mlt_text,
        "mlt_contains_text": "Opening" in mlt_text,
        "mlt_contains_transform": "rect\">" in mlt_text or "affineSizePosition" in mlt_text,
        "mlt_contains_local_source": "cover.jpg" in mlt_text and "C:/" in mlt_text,
        "mlt_contains_cloud_path": ("http://" in mlt_text) or ("https://" in mlt_text),
        "timeline_duration_frames": timeline_duration_frames,
        "photo_duration_ok": timeline_duration_frames == 91,
    }


def main() -> None:
    prepare_inputs()
    normal_dialogs = collect_normal_dialog_evidence()

    oversize_status = run_acceptance_mode(
        OVERSIZE_JSON,
        "04-acceptance-oversize-rejected.png",
        {"plan_import_start_failed", "plan_json_missing", "shotcut_error", "v2_error"},
    )
    manifest_path = latest_handoff_manifest()
    valid_plan = build_valid_plan_from_manifest(manifest_path)
    VALID_JSON.write_text(json.dumps(valid_plan, ensure_ascii=False, indent=2), encoding="utf-8")

    valid_status = run_acceptance_mode(
        VALID_JSON,
        "05-acceptance-valid-complete.png",
        {"shotcut_opened", "shotcut_error", "v2_error"},
    )
    results = inspect_results()

    report = {
        "exe_path": str(EXE_PATH),
        "exe_sha256": sha256(EXE_PATH),
        "project_name": PROJECT_NAME,
        "source_zip": str(SOURCE_ZIP),
        "source_zip_sha256": sha256(SOURCE_ZIP),
        "oversize_json": str(OVERSIZE_JSON),
        "oversize_bytes": OVERSIZE_JSON.stat().st_size,
        "valid_json": str(VALID_JSON),
        "valid_json_sha256": sha256(VALID_JSON),
        "normal_dialogs": normal_dialogs,
        "oversize_status": oversize_status,
        "valid_status": valid_status,
        "results": results,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.stdout.buffer.write(json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8", errors="replace"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
