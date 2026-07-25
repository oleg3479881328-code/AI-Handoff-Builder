from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class CoordinatorDraft:
    title: str
    voice_script: str
    visual_direction: str
    shot_sequence: list[str] = field(default_factory=list)
    overlay_lines: list[str] = field(default_factory=list)
    source_format: str = "plain_text"


def build_coordinator_draft(raw_text: str) -> CoordinatorDraft:
    text = raw_text.strip()
    if not text:
        raise ValueError("Coordinator brief is empty.")

    payload = _try_parse_json(text)
    if isinstance(payload, dict):
        return _draft_from_json(payload)
    return _draft_from_plain_text(text)


def draft_to_summary(draft: CoordinatorDraft) -> str:
    lines = [
        f"Title: {draft.title or 'Coordinator Draft'}",
        f"Source Format: {draft.source_format}",
        "",
        "Voice Script:",
        draft.voice_script or "-",
        "",
        "Visual Direction:",
        draft.visual_direction or "-",
        "",
        "Shot Sequence:",
    ]
    if draft.shot_sequence:
        lines.extend(f"- {item}" for item in draft.shot_sequence)
    else:
        lines.append("-")
    lines.extend(["", "Overlay Lines:"])
    if draft.overlay_lines:
        lines.extend(f"- {item}" for item in draft.overlay_lines)
    else:
        lines.append("-")
    return "\n".join(lines)


def draft_to_payload(draft: CoordinatorDraft) -> dict:
    payload = asdict(draft)
    payload["trusted_boundary"] = {
        "raw_html_allowed": False,
        "remote_urls_allowed": False,
        "render_target": "local_windows_machine",
    }
    return payload


def _try_parse_json(text: str) -> dict | None:
    if not text.startswith("{"):
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _draft_from_json(payload: dict) -> CoordinatorDraft:
    title = _first_text(payload, "title", "hook", "headline") or "Coordinator Draft"
    voice_script = _first_text(payload, "voice_script", "script", "narration", "voiceover")
    visual_direction = _first_text(payload, "visual_direction", "visual_notes", "look", "style", "notes")
    shot_sequence = _list_text(payload.get("shot_sequence") or payload.get("shots") or payload.get("scenes"))
    overlay_lines = _list_text(payload.get("overlay_lines") or payload.get("overlays") or payload.get("titles"))
    if not voice_script:
        voice_script = visual_direction or title
    return CoordinatorDraft(
        title=title,
        voice_script=voice_script,
        visual_direction=visual_direction,
        shot_sequence=shot_sequence,
        overlay_lines=overlay_lines,
        source_format="json",
    )


def _draft_from_plain_text(text: str) -> CoordinatorDraft:
    title = ""
    voice_parts: list[str] = []
    visual_parts: list[str] = []
    shot_sequence: list[str] = []
    overlay_lines: list[str] = []
    current_section = ""

    def _set_if_blank(field_name: str, value: str) -> None:
        nonlocal title
        if field_name == "title" and not title:
            title = value

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        section, remainder = _split_section(line)
        if section:
            current_section = section
            if remainder:
                _append_section_value(
                    section,
                    remainder,
                    title_ref=lambda value: _set_if_blank("title", value),
                    voice_parts=voice_parts,
                    visual_parts=visual_parts,
                    shot_sequence=shot_sequence,
                    overlay_lines=overlay_lines,
                )
            continue

        bullet = _strip_bullet(line)
        if bullet != line:
            if current_section == "overlay":
                overlay_lines.append(bullet)
            else:
                shot_sequence.append(bullet)
            continue

        if current_section == "voice":
            voice_parts.append(line)
        elif current_section == "visual":
            visual_parts.append(line)
        elif current_section == "overlay":
            overlay_lines.append(line)
        elif current_section == "shots":
            shot_sequence.append(line)
        elif not title:
            title = line
        elif not voice_parts:
            voice_parts.append(line)
        else:
            visual_parts.append(line)

    if not voice_parts and title:
        voice_parts.append(title)
    if not title:
        title = "Coordinator Draft"

    return CoordinatorDraft(
        title=title,
        voice_script=" ".join(part.strip() for part in voice_parts if part.strip()),
        visual_direction=" ".join(part.strip() for part in visual_parts if part.strip()),
        shot_sequence=shot_sequence,
        overlay_lines=overlay_lines,
        source_format="plain_text",
    )


def _split_section(line: str) -> tuple[str, str]:
    if ":" not in line:
        return "", ""
    head, tail = line.split(":", 1)
    key = head.strip().lower()
    mapping = {
        "title": "title",
        "hook": "title",
        "voice": "voice",
        "voice script": "voice",
        "script": "voice",
        "narration": "voice",
        "visual": "visual",
        "visual direction": "visual",
        "look": "visual",
        "style": "visual",
        "shots": "shots",
        "scenes": "shots",
        "overlay": "overlay",
        "overlays": "overlay",
        "titles": "overlay",
    }
    return mapping.get(key, ""), tail.strip()


def _append_section_value(
    section: str,
    value: str,
    *,
    title_ref,
    voice_parts: list[str],
    visual_parts: list[str],
    shot_sequence: list[str],
    overlay_lines: list[str],
) -> None:
    if section == "title":
        title_ref(value)
    elif section == "voice":
        voice_parts.append(value)
    elif section == "visual":
        visual_parts.append(value)
    elif section == "shots":
        shot_sequence.append(value)
    elif section == "overlay":
        overlay_lines.append(value)


def _strip_bullet(line: str) -> str:
    return re.sub(r"^(?:[-*]\s+|\d+[.)]\s+)", "", line).strip()


def _first_text(payload: dict, *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _list_text(value: object) -> list[str]:
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                result.append(item.strip())
            elif isinstance(item, dict):
                text = _first_text(item, "text", "title", "note", "description")
                if text:
                    result.append(text)
        return result
    return []
