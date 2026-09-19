from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.ai.agent import Agent
from app.ai.provider import AIProvider, Message
from app.api.routes import set_agent, set_voice_service
from app.main import app
from app.voice import VoiceService


class FakeAudioClient:
    def __init__(self):
        self.audio = SimpleNamespace(
            transcriptions=SimpleNamespace(create=self.transcribe),
            speech=SimpleNamespace(create=self.speak),
        )
        self.last_file = None
        self.last_text = None

    async def transcribe(self, **kwargs):
        self.last_file = kwargs["file"]
        return SimpleNamespace(text="What are my tasks?")

    async def speak(self, **kwargs):
        self.last_text = kwargs["input"]

        class AudioResponse:
            async def read(self):
                return b"fake-mp3"

        return AudioResponse()


class VoiceProvider(AIProvider):
    async def generate(self, messages: list[Message], system_prompt: str) -> str:
        return "Your tasks are ready."


@pytest.mark.asyncio
async def test_voice_service_transcribes_and_synthesizes():
    client = FakeAudioClient()
    service = VoiceService(api_key=None, client=client)
    assert await service.transcribe(b"audio", "note.ogg") == "What are my tasks?"
    assert client.last_file[0] == "note.ogg"
    assert await service.synthesize("Hello") == b"fake-mp3"
    assert client.last_text == "Hello"


@pytest.mark.asyncio
async def test_voice_api_routes_audio_through_agent_pipeline():
    voice_client = FakeAudioClient()
    set_voice_service(VoiceService(api_key=None, client=voice_client))
    set_agent(Agent(provider=VoiceProvider()))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        transcript = await client.post("/api/voice/transcribe?filename=test.ogg", content=b"audio", headers={"content-type": "audio/ogg"})
        assert transcript.status_code == 200
        assert transcript.json()["transcript"] == "What are my tasks?"

        reply = await client.post("/api/voice/reply?conversation_id=voice-1&user_id=user-1", content=b"audio", headers={"content-type": "audio/ogg"})
        assert reply.status_code == 200
        assert reply.json() == {"transcript": "What are my tasks?", "reply": "Your tasks are ready."}

        speech = await client.post("/api/voice/synthesize", content=b"Speak this")
        assert speech.status_code == 200
        assert speech.headers["content-type"] == "audio/mpeg"
        assert speech.content == b"fake-mp3"
    set_agent(None)
    set_voice_service(None)
