import json
from typing import Dict
from openai import OpenAI
from config import PLACEHOLDER_VALUES, settings


class AIEngine:
    def __init__(self) -> None:
        key = (settings.openai_api_key or "").strip()
        configured = bool(key and key != "test_key" and key not in PLACEHOLDER_VALUES and key.startswith("sk-"))
        self.client = OpenAI(api_key=key) if configured else None

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

    def translate_article(self, article: Dict[str, str], target_language: str) -> Dict[str, str]:
        if not self.client:
            return {
                "title": article.get("title", ""),
                "summary": article.get("summary", ""),
                "content": article.get("content", ""),
                "seo_title": article.get("seo_title", article.get("title", "")),
                "tags": article.get("tags", "news"),
                "meta_description": article.get("meta_description", ""),
            }
        prompt = (
            "Translate the provided Azerbaijani news article to target language. "
            "Return JSON keys: title,summary,content,seo_title,meta_description,tags. Keep journalistic tone. "
            "Preserve HTML structure in content if present. Translate tags as a comma-separated list."
        )
        resp = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps({"target_language": target_language, "article": article}, ensure_ascii=False)},
            ],
            response_format={"type": "json_object"},
        )
        return json.loads(resp.choices[0].message.content)
