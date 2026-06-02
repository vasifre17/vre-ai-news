import re
from datetime import datetime
from typing import Any

from config import PLACEHOLDER_VALUES, settings
from database.models import Article, ArticleNarration, ArticleTranslation, FetchLog
from database.session import SessionLocal
from ai.pipeline import AIEngine

PRIMARY_LANGUAGE = "az"
TRANSLATION_LANGUAGES = ["en", "ru", "tr", "zh", "es"]
AI_TRANSLATION_WARNING = "AI translation provider is not configured."


def is_ai_translation_configured() -> bool:
    key = (settings.openai_api_key or "").strip()
    return bool(key and key != "test_key" and key not in PLACEHOLDER_VALUES and key.startswith("sk-"))


def ai_translation_status() -> dict[str, Any]:
    configured = is_ai_translation_configured()
    return {
        "configured": configured,
        "provider": "OpenAI",
        "message": "OpenAI translation provider is configured." if configured else AI_TRANSLATION_WARNING,
    }


def slugify(text: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return base or "article"


def source_payload(article: Article) -> dict[str, str]:
    return {
        "title": article.title or "",
        "summary": article.summary or "",
        "content": article.content or "",
        "seo_title": article.seo_title or article.title or "",
        "meta_description": article.meta_description or "",
        "tags": article.tags or "",
    }


def translation_has_content(row: ArticleTranslation | None) -> bool:
    return bool(row and any((getattr(row, field, None) or "").strip() for field in ["title", "summary", "content", "seo_title", "meta_description", "tags"]))


def missing_translation_languages(article: Article) -> list[str]:
    translations = {(row.language or "").lower(): row for row in getattr(article, "translations", []) or []}
    return [lang for lang in TRANSLATION_LANGUAGES if not translation_has_content(translations.get(lang))]


def unique_translation_slug(db, language: str, requested_slug: str, current_translation_id: int | None = None) -> str:
    root = slugify(requested_slug)
    candidate = root
    suffix = 2
    while True:
        query = db.query(ArticleTranslation).filter(ArticleTranslation.language == language, ArticleTranslation.slug == candidate)
        if current_translation_id:
            query = query.filter(ArticleTranslation.id != current_translation_id)
        if not query.first():
            return candidate
        candidate = f"{root}-{suffix}"
        suffix += 1


def get_or_create_translation(db, article: Article, language: str) -> ArticleTranslation:
    row = db.query(ArticleTranslation).filter(ArticleTranslation.article_id == article.id, ArticleTranslation.language == language).first()
    if not row:
        row = ArticleTranslation(article_id=article.id, language=language)
        db.add(row)
        db.flush()
    return row


def queue_translation_narration(db, article: Article, language: str) -> None:
    if not article.narration_enabled or article.status != "published":
        return
    row = db.query(ArticleNarration).filter(ArticleNarration.article_id == article.id, ArticleNarration.language == language).first()
    if row:
        row.status = "pending"
        row.error_message = None
        row.updated_at = datetime.utcnow()
        return
    db.add(ArticleNarration(article_id=article.id, language=language, status="pending", provider="openai"))


def generate_missing_translations(article_id: int) -> dict[str, Any]:
    db = SessionLocal()
    engine = AIEngine()
    generated: list[str] = []
    try:
        if not is_ai_translation_configured():
            db.add(FetchLog(level="WARNING", message=AI_TRANSLATION_WARNING))
            db.commit()
            return {"configured": False, "generated": generated, "message": AI_TRANSLATION_WARNING}
        article = db.query(Article).filter(Article.id == article_id).first()
        if not article:
            return {"configured": True, "generated": generated, "message": "Article not found."}
        source = source_payload(article)
        for language in missing_translation_languages(article):
            payload = engine.translate_article(source, language)
            row = get_or_create_translation(db, article, language)
            row.title = payload.get("title") or article.title
            row.summary = payload.get("summary") or article.summary
            row.content = payload.get("content") or article.content
            row.seo_title = payload.get("seo_title") or row.title or article.seo_title
            row.meta_description = payload.get("meta_description") or article.meta_description
            row.tags = payload.get("tags") or article.tags
            row.slug = unique_translation_slug(db, language, row.title or f"{article.slug}-{language}", row.id)
            row.updated_at = datetime.utcnow()
            queue_translation_narration(db, article, language)
            generated.append(language)
        db.commit()
        return {"configured": True, "generated": generated, "message": f"Generated translations: {', '.join(generated) or 'none'}."}
    except Exception as exc:
        db.rollback()
        db.add(FetchLog(level="ERROR", message=f"AI translation failed for article {article_id}: {exc}"))
        db.commit()
        return {"configured": True, "generated": generated, "message": str(exc)}
    finally:
        db.close()


def generate_all_missing_translations(limit: int | None = None) -> dict[str, Any]:
    db = SessionLocal()
    try:
        if not is_ai_translation_configured():
            db.add(FetchLog(level="WARNING", message=AI_TRANSLATION_WARNING))
            db.commit()
            return {"configured": False, "queued": 0, "message": AI_TRANSLATION_WARNING}
        query = db.query(Article).order_by(Article.updated_at.desc(), Article.created_at.desc())
        if limit:
            query = query.limit(limit)
        article_ids = [article.id for article in query.all() if missing_translation_languages(article)]
    finally:
        db.close()
    generated = 0
    for article_id in article_ids:
        result = generate_missing_translations(article_id)
        generated += len(result.get("generated", []))
    return {"configured": True, "queued": len(article_ids), "generated": generated, "message": f"Processed {len(article_ids)} article(s)."}
