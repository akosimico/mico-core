from __future__ import annotations

import inspect
from typing import Any


class VoiceService:
    """Thin, replaceable adapter for speech-to-text and text-to-speech."""

    def __init__(
        self,
        api_key: str | None,
        stt_model: str = "gpt-4o-mini-transcribe",
        tts_model: str = "gpt-4o-mini-tts",
        voice: str = "alloy",
        client: Any | None = None,
    ):
        self.stt_model = stt_model
        self.tts_model = tts_model
        self.voice = voice
        self._client = client
        self._api_key = api_key

    @property
    def enabled(self) -> bool:
        return self._client is not None or bool(self._api_key)

    def _client_or_raise(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise RuntimeError("Voice is not configured. Set OPENAI_API_KEY to enable speech features.")
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=self._api_key)
        return self._client

    async def transcribe(self, audio: bytes, filename: str = "voice-message.ogg", content_type: str = "audio/ogg") -> str:
        if not audio:
            raise ValueError("Audio input is empty.")
        client = self._client_or_raise()
        result = await client.audio.transcriptions.create(
            model=self.stt_model,
            file=(filename, audio, content_type),
        )
        text = getattr(result, "text", "")
        if not text or not text.strip():
            raise ValueError("No speech could be transcribed from that audio.")
        return text.strip()

    async def synthesize(self, text: str) -> bytes:
        if not text.strip():
            raise ValueError("Text-to-speech input is empty.")
        client = self._client_or_raise()
        response = await client.audio.speech.create(
            model=self.tts_model,
            voice=self.voice,
            input=text[:4096],
            response_format="mp3",
        )
        payload = response.read()
        return await payload if inspect.isawaitable(payload) else payload
