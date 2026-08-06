from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .models import VoiceGenerationRequest, VoiceGenerationResult, VoiceProfile, VoiceRuntimeInfo


class VoiceboxError(RuntimeError):
    pass


class VoiceboxClient:
    def __init__(self, base_url: str = "http://127.0.0.1:17493", *, timeout_seconds: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def health_check(self) -> VoiceRuntimeInfo:
        payload = self._request_json("GET", "/health")
        openapi = self.get_openapi()
        version = str(openapi.get("info", {}).get("version") or "unknown")
        engines = self._discover_engines(openapi)
        return VoiceRuntimeInfo(
            base_url=self.base_url,
            api_version=version,
            status=str(payload.get("status") or "unknown"),
            model_loaded=bool(payload.get("model_loaded")),
            model_downloaded=payload.get("model_downloaded"),
            model_size=payload.get("model_size"),
            gpu_available=bool(payload.get("gpu_available")),
            gpu_type=payload.get("gpu_type"),
            vram_used_mb=payload.get("vram_used_mb"),
            backend_type=payload.get("backend_type"),
            backend_variant=payload.get("backend_variant"),
            engines=tuple(engines),
        )

    def get_openapi(self) -> dict[str, Any]:
        return self._request_json("GET", "/openapi.json")

    def list_profiles(self) -> list[VoiceProfile]:
        payload = self._request_json("GET", "/profiles")
        profiles: list[VoiceProfile] = []
        for item in payload:
            profiles.append(
                VoiceProfile(
                    profile_id=str(item["id"]),
                    name=str(item["name"]),
                    language=str(item["language"]),
                    voice_type=str(item.get("voice_type") or "unknown"),
                    default_engine=item.get("default_engine"),
                    sample_count=int(item.get("sample_count") or 0),
                    generation_count=int(item.get("generation_count") or 0),
                    raw=dict(item),
                )
            )
        return profiles

    def get_profile_samples(self, profile_id: str) -> list[dict[str, Any]]:
        payload = self._request_json("GET", f"/profiles/{urllib.parse.quote(profile_id)}/samples")
        return [dict(item) for item in payload]

    def generate_take(self, request: VoiceGenerationRequest, *, seed: int) -> VoiceGenerationResult:
        payload = self._request_json(
            "POST",
            "/generate",
            {
                "profile_id": request.profile_id,
                "text": request.text,
                "language": request.language.replace("-US", "").replace("-GB", ""),
                "seed": seed,
                "model_size": request.model_size,
                "instruct": request.instruct,
                "engine": request.engine,
                "normalize": request.normalize_voice,
            },
        )
        return self._to_generation_result(payload)

    def get_generation(self, generation_id: str) -> VoiceGenerationResult:
        payload = self._request_json("GET", f"/history/{urllib.parse.quote(generation_id)}")
        return self._to_generation_result(payload)

    def wait_for_generation(
        self,
        generation_id: str,
        *,
        poll_seconds: float = 2.0,
        max_polls: int = 480,
    ) -> VoiceGenerationResult:
        import time

        last = self.get_generation(generation_id)
        for _ in range(max_polls):
            if last.status not in {"queued", "generating", "running"}:
                return last
            time.sleep(poll_seconds)
            last = self.get_generation(generation_id)
        raise VoiceboxError(f"Generation did not finish in time: {generation_id}")

    def download_audio(self, generation_id: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(f"{self.base_url}/audio/{urllib.parse.quote(generation_id)}", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = response.read()
        except urllib.error.HTTPError as exc:
            raise VoiceboxError(f"Audio download failed for {generation_id}: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise VoiceboxError(f"Audio download failed for {generation_id}: {exc.reason}") from exc
        if not data:
            raise VoiceboxError(f"Audio download returned empty payload for {generation_id}")
        destination.write_bytes(data)
        return destination

    def transcribe_audio(self, audio_path: Path) -> dict[str, Any]:
        boundary = f"----VoiceboxBoundary{uuid.uuid4().hex}"
        body = self._encode_multipart_form({"file": audio_path}, boundary)
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        return self._request_json("POST", "/transcribe", body, headers=headers, is_binary=True)

    def cancel_generation(self, generation_id: str) -> dict[str, Any]:
        return self._request_json("POST", f"/generate/{urllib.parse.quote(generation_id)}/cancel", {})

    def _to_generation_result(self, payload: dict[str, Any]) -> VoiceGenerationResult:
        return VoiceGenerationResult(
            generation_id=str(payload["id"]),
            status=str(payload.get("status") or "unknown"),
            audio_path=payload.get("audio_path"),
            duration_seconds=float(payload["duration"]) if payload.get("duration") is not None else None,
            seed=payload.get("seed"),
            engine=payload.get("engine"),
            model_size=payload.get("model_size"),
            created_at=str(payload.get("created_at") or ""),
            raw=dict(payload),
        )

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | bytes | None = None,
        *,
        headers: dict[str, str] | None = None,
        is_binary: bool = False,
    ) -> Any:
        request_headers = dict(headers or {})
        data: bytes | None = None
        if isinstance(payload, dict):
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        elif isinstance(payload, bytes):
            data = payload
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=request_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise VoiceboxError(f"{method} {path} failed: HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise VoiceboxError(f"{method} {path} failed: {exc.reason}") from exc
        except TimeoutError as exc:
            raise VoiceboxError(f"{method} {path} timed out") from exc
        if is_binary:
            return json.loads(raw.decode("utf-8"))
        return json.loads(raw.decode("utf-8"))

    def _discover_engines(self, openapi: dict[str, Any]) -> list[str]:
        schema = openapi.get("components", {}).get("schemas", {}).get("GenerationRequest", {})
        engine = schema.get("properties", {}).get("engine", {})
        patterns = engine.get("anyOf", [])
        for item in patterns:
            pattern = item.get("pattern")
            if pattern and pattern.startswith("^(") and pattern.endswith(")$"):
                return pattern[2:-2].split("|")
        return []

    def _encode_multipart_form(self, files: dict[str, Path], boundary: str) -> bytes:
        chunks: list[bytes] = []
        for field_name, path in files.items():
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode("utf-8"),
                    (
                        f'Content-Disposition: form-data; name="{field_name}"; filename="{path.name}"\r\n'
                    ).encode("utf-8"),
                    f"Content-Type: {mime}\r\n\r\n".encode("utf-8"),
                    path.read_bytes(),
                    b"\r\n",
                ]
            )
        chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
        return b"".join(chunks)
