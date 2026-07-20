# AI-Handoff-Builder Agent Notes

Work through `PROJECT.md` first, then `PROJECT_STATE.md`, then `logs/latest.md`.

Current implementation contract:

- primary active handoff: `Yt-Dlp-Download-Manager` issue `#67`
- current local baseline source: this repository

Execution rules for this repository:

- extend the existing standalone application; do not create a second app;
- keep originals on the owner's machine; never modify them during analysis or rendering;
- use safe FFmpeg argument arrays only; no `shell=True`;
- treat GitHub as the code and execution source of truth;
- keep the project transfer-ready after each meaningful step by updating `PROJECT_STATE.md` and `logs/latest.md`.
