import os
import re
from pathlib import Path
from typing import Tuple

from openai import OpenAI

from config import settings

SUPPORTED_LANGUAGES = {"az", "en", "ru", "tr", "zh", "es"}


class AudioNarrationService:
    def __init__(self) -> None:
        self.client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
        self.audio_dir = Path("static/audio")
        self.audio_dir.mkdir(parents=True, exist_ok=True)

    def supports_language(self, language: str) -> bool:
        return (language or "").lower() in SUPPORTED_LANGUAGES

    def _clean_text(self, text: str) -> str:
        normalized = re.sub(r"\s+", " ", (text or "").strip())
        return normalized

    def generate(self, article_id: int, language: str, title: str, summary: str, content: str) -> Tuple[str, int]:
        lang = (language or "az").lower()
        script = self._clean_text(f"{title}. {summary}. {content}")
        filename = f"article-{article_id}-{lang}.mp3"
        filepath = self.audio_dir / filename

        if self.client and self.supports_language(lang):
            prompt = (
                "Narrate this news article naturally with a professional journalistic tone. "
                "Respect punctuation, dates, numbers, names, and direct quotations."
            )
            with self.client.audio.speech.with_streaming_response.create(
                model="gpt-4o-mini-tts",
                voice="alloy",
                input=f"{prompt}\n\nLanguage: {lang}\n\n{script}",
                format="mp3",
            ) as response:
                response.stream_to_file(filepath)
        else:
            # Fallback silent-compatible placeholder payload for non-blocking publish behavior.
            with open(filepath, "wb") as f:
                f.write(b"ID3")
        size = os.path.getsize(filepath)
        return f"/static/audio/{filename}", size
