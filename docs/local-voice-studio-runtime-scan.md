# Local Voice Studio Runtime Scan

Date: 2026-07-21

## Runtime

- Base URL: `http://127.0.0.1:17493`
- OpenAPI version: `3.1.0`
- API version: `0.5.0`
- Health status: `healthy`
- Backend type: `pytorch`
- Backend variant: `cpu`
- Model loaded: `true`
- Model downloaded: `true`
- Model size: `0.6B`
- GPU available: `false`

## Confirmed endpoints used

- `GET /health`
- `GET /openapi.json`
- `GET /profiles`
- `GET /profiles/{profile_id}/samples`
- `POST /generate`
- `GET /history/{generation_id}`
- `GET /audio/{generation_id}`
- `POST /transcribe`

## Confirmed generation contract

`GenerationRequest` requires:

- `profile_id`
- `text`

Confirmed optional fields used:

- `language`
- `seed`
- `model_size`
- `instruct`
- `engine`
- `normalize`

## Confirmed response behavior

- `POST /generate` immediately returns a generation record with `status=generating`
- polling `GET /history/{generation_id}` is required for completion
- `GET /audio/{generation_id}` serves the generated WAV

## Current limitation

`POST /transcribe` returns only:

- `text`
- `duration`

It does not provide word-level timestamps in the confirmed OpenAPI contract. Because of that, the Builder currently treats word alignment as a separate local adapter problem instead of pretending Voicebox already returns karaoke-ready timing.

## Confirmed profile

- `profile_key`: `olga-polo-en-v1`
- `profile_id`: `e3684e16-2e15-421b-b305-dc2845280193`
- `name`: `Olga`
- `language`: `en`
- `voice_type`: `cloned`
- `default_engine`: `qwen`
- `sample_count`: `1`

## Existing-solution reuse decisions

- Reuse Builder SQLite workspace + additive migrations
- Reuse Builder FFmpeg/ffprobe execution path
- Reuse Builder CLI/service separation
- Reuse Voicebox OpenAPI directly instead of inventing a fake adapter surface
- Defer word-level alignment until a real local aligner exists in the Builder runtime
