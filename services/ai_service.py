import base64
import json
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from core.models import AITransactionBatch
from core.prompts import SYSTEM_PROMPT, build_user_prompt
from logger import logger


class AIServiceError(Exception):
    pass


class AIService:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        chat_model: str,
        whisper_model: str,
        transcription_language: str | None = None,
        site_url: str | None = None,
        app_name: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.chat_model = chat_model
        self.whisper_model = whisper_model
        self.transcription_language = transcription_language
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0),
            headers=self._headers(api_key, site_url, app_name),
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def transcribe_audio(self, audio: bytes, filename: str) -> str:
        payload: dict[str, Any] = {
            "model": self.whisper_model,
            "input_audio": {
                "data": base64.b64encode(audio).decode("ascii"),
                "format": self._audio_format(filename),
            },
        }
        if self.transcription_language:
            payload["language"] = self.transcription_language

        try:
            response = await self.client.post(
                f"{self.base_url}/audio/transcriptions",
                json=payload,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            response_text = exc.response.text[:1000] if exc.response is not None else ""
            raise AIServiceError(
                f"OpenRouter transcription request failed: {exc.response.status_code} {response_text}"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise AIServiceError("OpenRouter transcription request failed") from exc

        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise AIServiceError("OpenRouter returned empty transcription")
        return text.strip()

    async def parse_transaction(self, text: str, categories: set[str]) -> AITransactionBatch:
        payload: dict[str, Any] = {
            "model": self.chat_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(text, categories)},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        try:
            response = await self.client.post(f"{self.base_url}/chat/completions", json=payload)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            logger.info("LLM transaction raw response text={!r} content={}", text, content)
            data = json.loads(content)
            return AITransactionBatch.from_payload(data)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError) as exc:
            raise AIServiceError("OpenRouter chat request failed") from exc

    @staticmethod
    def _headers(api_key: str, site_url: str | None, app_name: str | None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }
        if site_url:
            headers["HTTP-Referer"] = site_url
        if app_name:
            headers["X-Title"] = app_name
        return headers

    @staticmethod
    def _audio_format(filename: str) -> str:
        suffix = Path(filename).suffix.lower().lstrip(".")
        if suffix == "oga":
            return "ogg"
        return suffix or "ogg"
