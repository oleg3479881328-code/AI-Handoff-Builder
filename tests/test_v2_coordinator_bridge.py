from __future__ import annotations

from handoff_builder.v2.coordinator_bridge import build_coordinator_draft, draft_to_payload


def test_build_coordinator_draft_from_json():
    draft = build_coordinator_draft(
        """
        {
          "title": "Cafe Promise",
          "voice_script": "Warm vows, alive room, confident finish.",
          "visual_direction": "Warm cafe light and gentle motion.",
          "shots": ["Wide room", "Medium laugh", "Close promise"],
          "overlay_lines": ["HYPERFRAMES LAB", "Warm and Alive"]
        }
        """
    )
    assert draft.source_format == "json"
    assert draft.title == "Cafe Promise"
    assert draft.voice_script == "Warm vows, alive room, confident finish."
    assert draft.shot_sequence == ["Wide room", "Medium laugh", "Close promise"]
    assert draft.overlay_lines == ["HYPERFRAMES LAB", "Warm and Alive"]


def test_build_coordinator_draft_from_plain_text():
    draft = build_coordinator_draft(
        """
        Title: Candlelight Reception
        Voice: Your wedding should feel warm, alive, and quietly cinematic.
        Visual: Soft cafe light, confident pacing, polished portrait transitions.
        Shots:
        - Wide room opening
        - Medium smile at the table
        - Close portrait finish
        Overlay:
        - WARM AND ALIVE
        - HYPERFRAMES LAB
        """
    )
    assert draft.source_format == "plain_text"
    assert draft.title == "Candlelight Reception"
    assert "warm, alive" in draft.voice_script
    assert draft.shot_sequence == [
        "Wide room opening",
        "Medium smile at the table",
        "Close portrait finish",
    ]
    assert draft.overlay_lines == ["WARM AND ALIVE", "HYPERFRAMES LAB"]


def test_draft_payload_records_trusted_boundary():
    draft = build_coordinator_draft("Voice: Local render only.")
    payload = draft_to_payload(draft)
    assert payload["trusted_boundary"]["raw_html_allowed"] is False
    assert payload["trusted_boundary"]["remote_urls_allowed"] is False
    assert payload["trusted_boundary"]["render_target"] == "local_windows_machine"
