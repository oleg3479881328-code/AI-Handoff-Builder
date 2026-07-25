# HyperFrames local prototype

This folder is a non-production discovery prototype inside `AI-Handoff-Builder`.

It validates the official HyperFrames local CLI against owner media before any renderer integration is added to the desktop application.

## Privacy

Do not commit real photographs, video, audio, rendered MP4 files, browser profiles, or generated workspace contents.

Copy test media locally into:

```text
prototypes/hyperframes/assets/
```

Expected local filenames:

```text
01-wide.jpg
02-wide.jpg
03-medium.jpg
04-portrait.jpg
05-close.jpg
06-close.jpg
```

The six current demonstration photographs can be mapped from these owner filenames when available locally:

```text
20260722_172637.jpg
20260722_172633.jpg
20260722_172635.jpg
20260722_172119.jpg
20260722_172122.jpg
20260722_172124.jpg
```

Do not rename or modify the originals. Copy them into the prototype asset directory.

## Official local workflow

From this folder on Windows:

```text
npm install -g hyperframes
hyperframes doctor
hyperframes preview .
hyperframes lint .
hyperframes inspect .
hyperframes render . --out out/hyperframes_photo_demo.mp4
```

Current HyperFrames releases validate a project directory, not a standalone `comp.html`.
`comp.html` is kept here as the original discovery draft, while `index.html + meta.json + hyperframes.json + package.json` provide the actual CLI-compatible project shape for `0.7.x`.

Preview normally opens on a local port chosen by HyperFrames, often:

```text
http://localhost:5173
```

Use a different port only when required:

```text
hyperframes preview . --port 5174
```

## Required evidence

Record:

- `node --version`;
- `npm --version`;
- `hyperframes --version`;
- full `hyperframes doctor` result;
- preview screenshot;
- render command and exit code;
- output width, height, FPS, duration, audio presence, size, and SHA-256;
- second-render SHA-256 comparison;
- any Windows, Chromium, FFmpeg, path, Unicode, or firewall problem.

## Expected output

- format: MP4;
- dimensions: 1080x1920;
- FPS: 30;
- duration: 12 seconds;
- visual flow: wide -> medium -> portrait -> close-up;
- no network assets;
- no source-file modification.

## Boundary

This prototype does not yet change the production FFmpeg renderer. It must be validated before adding a Python adapter or Tkinter controls.
