from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .models import BuilderConfig
from .pipeline import HandoffBuilder


def _safe_print(message: object) -> None:
    text = str(message)
    try:
        print(text)
    except UnicodeEncodeError:
        stream = sys.stdout
        stream.buffer.write(text.encode(stream.encoding or "utf-8", errors="replace") + b"\n")
        stream.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a ChatGPT analysis handoff ZIP.")
    parser.add_argument("--input", nargs="+", required=True, help="ZIP, folder, photo, or video paths")
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument("--project", required=True, help="Project name")
    parser.add_argument("--no-proxies", action="store_true", help="Do not include full video proxies")
    args = parser.parse_args()

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


if __name__ == "__main__":
    raise SystemExit(main())
