from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont, ImageOps


def _font(size: int = 22) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def build_contact_sheet(
    images: list[tuple[Path, str]],
    destination: Path,
    *,
    columns: int = 4,
    thumb_size: tuple[int, int] = (320, 240),
    background: str = "#161922",
) -> None:
    if not images:
        return
    rows = math.ceil(len(images) / columns)
    label_height = 42
    cell_w, cell_h = thumb_size[0], thumb_size[1] + label_height
    canvas = Image.new("RGB", (columns * cell_w, rows * cell_h), background)
    draw = ImageDraw.Draw(canvas)
    font = _font(18)

    for index, (path, label) in enumerate(images):
        row, col = divmod(index, columns)
        x, y = col * cell_w, row * cell_h
        try:
            with Image.open(path) as image:
                image = ImageOps.exif_transpose(image).convert("RGB")
                fitted = ImageOps.contain(image, thumb_size)
                px = x + (thumb_size[0] - fitted.width) // 2
                py = y + (thumb_size[1] - fitted.height) // 2
                canvas.paste(fitted, (px, py))
        except Exception:
            draw.rectangle((x + 8, y + 8, x + cell_w - 8, y + thumb_size[1] - 8), outline="red")
        short = label if len(label) <= 42 else label[:39] + "..."
        draw.text((x + 8, y + thumb_size[1] + 8), short, fill="white", font=font)

    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, "JPEG", quality=86, optimize=True)


def paginate_contact_sheets(
    images: list[tuple[Path, str]],
    output_dir: Path,
    *,
    prefix: str,
    page_size: int = 20,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    result: list[Path] = []
    for page_index in range(0, len(images), page_size):
        page = images[page_index: page_index + page_size]
        destination = output_dir / f"{prefix}_{page_index // page_size + 1:03d}.jpg"
        build_contact_sheet(page, destination)
        result.append(destination)
    return result
