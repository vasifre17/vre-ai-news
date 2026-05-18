import json
from typing import Dict
from openai import OpenAI
from config import settings
from i18n import SUPPORTED_LANGUAGES


class AIEngine:
    def __init__(self) -> None:
        self.client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    def process_article(self, title: str, content: str) -> Dict[str, str]:
        if not self.client:
            return {
                "language": "az",
                "title": title,
                "summary": content[:180],
                "content": content,
                "seo_title": title,
                "meta_description": content[:160],
                "tags": "news,ai",
                "category": self.categorize(f"{title} {content}"),
            }

        prompt = (
            "Detect language; if not Azerbaijani translate. Rewrite as unique journalism article. "
            "Return JSON keys: language,title,summary,content,seo_title,meta_description,tags,category. "
            "Categories: Politics, World, Social, Economy."
        )
        resp = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Title: {title}\n\nContent: {content}"},
            ],
            response_format={"type": "json_object"},
        )
        out = json.loads(resp.choices[0].message.content)
        out["category"] = out.get("category") or self.categorize(f"{title} {content}")
        out["meta_description"] = out.get("meta_description") or out.get("summary", "")[:160]
        return out

    def translate_article(self, article: Dict[str, str], target_language: str) -> Dict[str, str]:
        if target_language not in SUPPORTED_LANGUAGES or target_language == "az":
            return article
        if not self.client:
            return article
        prompt = (
            "Translate this Azerbaijani news article with professional journalistic quality. "
            "Do not summarize or omit. Preserve names, meaning, tone, quotes, dates, political context, formatting. "
            "Return JSON keys: title,summary,content,seo_title,meta_description,tags."
        )
        resp = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps({"target_language": target_language, **article}, ensure_ascii=False)},
            ],
            response_format={"type": "json_object"},
        )
        return json.loads(resp.choices[0].message.content)

    def categorize(self, text: str) -> str:
        t = text.lower()
        if any(k in t for k in ["government", "aliyev", "diplom", "official visit", "president"]):
            return "Politics"
        if any(k in t for k in ["market", "business", "finance", "inflation", "bank"]):
            return "Economy"
        if any(k in t for k in ["health", "education", "society", "hospital", "school"]):
            return "Social"
        return "World"
