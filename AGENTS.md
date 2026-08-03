# AI-Handoff-Builder Agent Notes

Work through these files in this exact order before any task:

1. `PROJECT.md`
2. `PROJECT_STATE.md`
3. `logs/latest.md`
4. `REFERENCE_TRAINING_KB.md` — mandatory reference and interaction knowledge base

Current implementation contract:

- primary active handoff: `Yt-Dlp-Download-Manager` issue `#67`
- current local baseline source: this repository

Execution rules for this repository:

- extend the existing standalone application; do not create a second app;
- keep originals on the owner's machine; never modify them during analysis or rendering;
- use safe FFmpeg argument arrays only; no `shell=True`;
- treat GitHub as the code and execution source of truth;
- keep the project transfer-ready after each meaningful step by updating `PROJECT_STATE.md` and `logs/latest.md`.

## Mandatory reference-learning rule

Before changing Shotcut/MLT files, Gemini workflows, integrations, effects, transitions, timelines, project formats, or behavior in any external program, read `REFERENCE_TRAINING_KB.md` completely.

The executor must:

- follow confirmed rules from the knowledge base;
- never invent an unsupported file structure or program behavior;
- request or use a reference produced by the target program when the mechanism is unknown;
- compare the reference, validate the generated result in the target program, and then update `REFERENCE_TRAINING_KB.md`;
- never repeat an error already recorded in the knowledge base.

Key defaults:

- a Shotcut editing file means `.mlt`;
- MP4 is created only after an explicit render/export request;
- the assistant supplies confirmed absolute source paths inside MLT by default;
- “причесать”, “собрать в кучу”, or “привести таймлайн в порядок” means remove all timeline gaps while preserving clip order, trims, and chronology;
- Shotcut transitions must use the structure confirmed by a Shotcut-generated reference.
