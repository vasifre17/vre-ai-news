import json
from typing import Dict
from openai import OpenAI
from config import settings


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
                "tags": "news,ai",
                "category": self.categorize(f"{title} {content}"),
            }

        prompt = (
            "Detect language; if not Azerbaijani translate. Rewrite as unique journalism article. "
            "Return JSON keys: language,title,summary,content,seo_title,tags,category. "
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
