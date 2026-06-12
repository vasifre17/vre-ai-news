import json
import re
from typing import Any, Dict

from openai import OpenAI

from config import PLACEHOLDER_VALUES, settings
from database.models import Setting
from database.session import SessionLocal

OPENAI_MODEL_OPTIONS = {
    "gpt-5.5": "GPT-5.5",
    "gpt-5.5-mini": "GPT-5.5 Mini",
}
DEFAULT_OPENAI_MODEL = "gpt-5.5-mini"


LANGUAGE_NAMES = {
    "az": "Azerbaijani",
    "en": "English",
    "ru": "Russian",
    "tr": "Turkish",
    "es": "Spanish",
    "zh": "Chinese",
}


def _bounded(value: str | None, limit: int) -> str:
    text = (value or "").strip()
    return text[:limit].rstrip()


def _clean_json(content: str | None) -> dict[str, Any]:
    if not content:
        return {}
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.S)
        if match:
            return json.loads(match.group(0))
        raise


def _setting_value(key: str, default: str = "") -> str:
    db = SessionLocal()
    try:
        row = db.query(Setting).filter(Setting.key == key).first()
        return (row.value if row and row.value is not None else default) or ""
    except Exception:
        return default or ""
    finally:
        db.close()


def openai_runtime_settings() -> dict[str, str | bool]:
    api_key = (_setting_value("openai_api_key") or settings.openai_api_key or "").strip()
    model = (_setting_value("openai_model", DEFAULT_OPENAI_MODEL) or DEFAULT_OPENAI_MODEL).strip()
    if model not in OPENAI_MODEL_OPTIONS:
        model = DEFAULT_OPENAI_MODEL
    translation_enabled = (_setting_value("ai_translation_enabled", "enabled") or "enabled") == "enabled"
    seo_enabled = (_setting_value("ai_seo_enabled", "enabled") or "enabled") == "enabled"
    configured = bool(api_key and api_key not in PLACEHOLDER_VALUES and api_key != "test_key" and api_key.startswith("sk-"))
    return {
        "api_key": api_key,
        "model": model,
        "translation_enabled": translation_enabled,
        "seo_enabled": seo_enabled,
        "configured": configured,
    }


def estimate_reading_time(content: str, words_per_minute: int = 220) -> int:
    text = re.sub(r"<[^>]+>", " ", content or "")
    words = re.findall(r"\w+", text, flags=re.UNICODE)
    return max(1, round(len(words) / words_per_minute))


class AIEngine:
    def __init__(self) -> None:
        runtime = openai_runtime_settings()
        self.model = str(runtime["model"])
        self.translation_enabled = bool(runtime["translation_enabled"])
        self.seo_enabled = bool(runtime["seo_enabled"])
        self.configured = bool(runtime["configured"])
        self.client = OpenAI(api_key=str(runtime["api_key"])) if self.configured else None

    def _json_chat(self, system_prompt: str, payload: Dict[str, Any], max_payload_chars: int = 12000) -> Dict[str, Any]:
        if not self.client:
            return {}
        serialized = json.dumps(payload, ensure_ascii=False)
        if len(serialized) > max_payload_chars:
            serialized = serialized[:max_payload_chars]
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": serialized},
            ],
            response_format={"type": "json_object"},
        )
        return _clean_json(resp.choices[0].message.content)

    def process_article(self, title: str, content: str) -> Dict[str, str]:
        if not self.client:
            return {
                "language": "az",
                "title": title,
                "summary": content[:180],
                "content": content,
                "seo_title": title,
                "tags": "news,ai",
                "category": self.categorize(f"{title} {content}"),
            }

        prompt = (
            "Detect language; if not Azerbaijani translate. Rewrite as unique journalism article. "
            "Return JSON keys: language,title,summary,content,seo_title,tags,category. "
            "Categories: Politics, World, Social, Economy."
        )
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Title: {title}\n\nContent: {content}"},
            ],
            response_format={"type": "json_object"},
        )
        out = _clean_json(resp.choices[0].message.content)
        out["category"] = out.get("category") or self.categorize(f"{title} {content}")
        return out

    def generate_meta_description(self, title: str, summary: str = "", content: str = "", language: str = "az") -> str:
        source = " ".join(part.strip() for part in [summary, content] if part and part.strip())
        fallback = (source or title or "VREYC news update").strip().replace("\n", " ")
        if not self.client or not self.seo_enabled:
            return fallback[:157].rstrip() + ("..." if len(fallback) > 157 else "")

        prompt = (
            "Write one concise SEO meta description for a news article. "
            "Use the article language when possible, avoid quotation marks, and return JSON with key meta_description. "
            "Keep it between 150 and 160 characters."
        )
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps({"language": language, "title": title, "summary": summary, "content": content[:2500]}, ensure_ascii=False)},
            ],
            response_format={"type": "json_object"},
        )
        out = _clean_json(resp.choices[0].message.content)
        return (out.get("meta_description") or fallback[:155]).strip()

    def generate_seo_pack(self, article: Dict[str, str], language: str = "az") -> Dict[str, Any]:
        title = article.get("title", "")
        summary = article.get("summary", "")
        content = article.get("content", "")
        fallback_description = self.generate_meta_description(title, summary, content, language)
        fallback = {
            "seo_title": article.get("seo_title") or title,
            "meta_description": fallback_description,
            "focus_keywords": article.get("tags") or "news, VREYC",
            "google_news_description": summary or fallback_description,
            "image_alt_text": title,
            "reading_time_minutes": estimate_reading_time(content),
            "facebook_share_text": f"{title} — VREYC".strip(),
            "telegram_share_text": f"{title}\n\n{summary}".strip(),
            "x_share_text": f"{title} — VREYC"[:260].strip(),
        }
        if not self.client or not self.seo_enabled:
            return fallback
        prompt = (
            "You are an AI SEO editor for a Google News-ready multilingual CMS. Return strict JSON with keys: "
            "seo_title, meta_description, focus_keywords, google_news_description, image_alt_text, "
            "reading_time_minutes, facebook_share_text, telegram_share_text, x_share_text. "
            "Meta description must be 150-160 characters. Focus keywords must be comma-separated. "
            "Keep social texts ready to publish and keep X text under 280 characters."
        )
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps({"language": language, "article": article}, ensure_ascii=False)},
            ],
            response_format={"type": "json_object"},
        )
        out = {**fallback, **_clean_json(resp.choices[0].message.content)}
        out["reading_time_minutes"] = int(out.get("reading_time_minutes") or fallback["reading_time_minutes"])
        return out

    def categorize(self, text: str) -> str:
        t = text.lower()
        if any(k in t for k in ["government", "aliyev", "diplom", "official visit", "president"]):
            return "Politics"
        if any(k in t for k in ["market", "business", "finance", "inflation", "bank"]):
            return "Economy"
        if any(k in t for k in ["health", "education", "society", "hospital", "school"]):
            return "Social"
        return "World"

    def translate_article(self, article: Dict[str, str], target_language: str) -> Dict[str, str]:
        if not self.client or not self.translation_enabled:
            return {
                "title": article.get("title", ""),
                "summary": article.get("summary", ""),
                "content": article.get("content", ""),
                "seo_title": article.get("seo_title", article.get("title", "")),
                "meta_description": article.get("meta_description", ""),
                "focus_keywords": article.get("focus_keywords", article.get("tags", "news")),
                "google_news_description": article.get("google_news_description", article.get("summary", "")),
                "image_alt_text": article.get("image_alt_text", article.get("title", "")),
                "reading_time_minutes": str(article.get("reading_time_minutes", estimate_reading_time(article.get("content", "")))),
                "facebook_share_text": article.get("facebook_share_text", article.get("title", "")),
                "telegram_share_text": article.get("telegram_share_text", article.get("summary", "")),
                "x_share_text": article.get("x_share_text", article.get("title", "")),
                "tags": article.get("tags", "news"),
            }
        prompt = (
            "Translate the provided Azerbaijani news article to target language. "
            "Return JSON keys: title,summary,content,seo_title,meta_description,focus_keywords,google_news_description,"
            "image_alt_text,reading_time_minutes,facebook_share_text,telegram_share_text,x_share_text,tags. "
            "Keep journalistic tone. Preserve HTML structure in content if present. Translate tags as a comma-separated list."
        )
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps({"target_language": target_language, "article": article}, ensure_ascii=False)},
            ],
            response_format={"type": "json_object"},
        )
        return _clean_json(resp.choices[0].message.content)

    def rewrite_title(self, article: Dict[str, str], language: str = "az") -> Dict[str, str]:
        title = article.get("title", "")
        fallback = {"title": title, "seo_title": article.get("seo_title") or title}
        if not self.client or not self.seo_enabled:
            return fallback
        prompt = (
            "You are a senior news headline editor. Return strict JSON with keys title and seo_title. "
            "Rewrite the headline in the requested language, keep facts unchanged, avoid clickbait, "
            "and keep title under 90 characters and seo_title under 70 characters."
        )
        out = self._json_chat(prompt, {"language": language, "language_name": LANGUAGE_NAMES.get(language, language), "article": article})
        return {**fallback, **out}

    def rewrite_article(self, article: Dict[str, str], language: str = "az") -> Dict[str, str]:
        fallback = {
            "title": article.get("title", ""),
            "summary": article.get("summary", ""),
            "content": article.get("content", ""),
            "seo_title": article.get("seo_title", article.get("title", "")),
            "tags": article.get("tags", ""),
            "category": article.get("category", ""),
        }
        if not self.client:
            return fallback
        prompt = (
            "You are a newsroom rewrite editor. Return strict JSON with keys title, summary, content, "
            "seo_title, tags, category. Rewrite the article in the requested language with an original "
            "journalistic style while preserving all verifiable facts, names, numbers, quotes, HTML structure, "
            "and attribution. Do not invent facts."
        )
        out = self._json_chat(prompt, {"language": language, "language_name": LANGUAGE_NAMES.get(language, language), "article": article})
        return {**fallback, **out}

    def generate_summary(self, article: Dict[str, str], language: str = "az") -> Dict[str, str]:
        fallback = {"summary": _bounded(article.get("summary") or re.sub(r"<[^>]+>", " ", article.get("content", "")), 280)}
        if not self.client:
            return fallback
        prompt = (
            "Return strict JSON with key summary. Write a concise 2-3 sentence news summary in the requested language. "
            "Keep facts unchanged and avoid promotional language."
        )
        out = self._json_chat(prompt, {"language": language, "language_name": LANGUAGE_NAMES.get(language, language), "article": article})
        return {**fallback, **out}

    def generate_tags(self, article: Dict[str, str], language: str = "az") -> Dict[str, str]:
        fallback = {"tags": article.get("tags") or "news"}
        if not self.client or not self.seo_enabled:
            return fallback
        prompt = (
            "Return strict JSON with key tags. Generate 6-10 SEO/news tags in the requested language as a comma-separated string. "
            "Use only topics supported by the article."
        )
        out = self._json_chat(prompt, {"language": language, "language_name": LANGUAGE_NAMES.get(language, language), "article": article})
        return {**fallback, **out}

    def generate_social_share_pack(self, article: Dict[str, str], language: str = "az") -> Dict[str, str]:
        title = article.get("title", "")
        summary = article.get("summary", "")
        fallback = {
            "facebook_share_text": f"{title} — VREYC".strip(),
            "telegram_share_text": f"{title}\n\n{summary}".strip(),
            "x_share_text": f"{title} — VREYC"[:260].strip(),
        }
        if not self.client or not self.seo_enabled:
            return fallback
        prompt = (
            "You are a social media editor for a news CMS. Return strict JSON with keys facebook_share_text, "
            "telegram_share_text, x_share_text. Write ready-to-publish social copy in the requested language; "
            "x_share_text must be under 280 characters. Do not add unsupported claims."
        )
        out = self._json_chat(prompt, {"language": language, "language_name": LANGUAGE_NAMES.get(language, language), "article": article})
        merged = {**fallback, **out}
        merged["x_share_text"] = _bounded(merged.get("x_share_text"), 279)
        return merged
