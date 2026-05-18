from datetime import datetime
from database.session import SessionLocal
from database.models import Article, FetchLog, ArticleTranslation
from scraper.fetcher import fetch_rss_items
from ai.pipeline import AIEngine
from ai.image_service import get_image_for_article
from config import settings
from i18n import SUPPORTED_LANGUAGES
import re


def slugify(text: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return base or "article"


def create_translation_jobs(db, article: Article):
    for lang in SUPPORTED_LANGUAGES:
        if lang == "az":
            continue
        exists = db.query(ArticleTranslation).filter_by(article_id=article.id, language=lang).first()
        if not exists:
            db.add(ArticleTranslation(article_id=article.id, language=lang, status="pending"))


def run_translation_pipeline() -> None:
    db = SessionLocal()
    ai = AIEngine()
    try:
        pending = db.query(ArticleTranslation).filter(ArticleTranslation.status == "pending").limit(20).all()
        for tr in pending:
            article = db.query(Article).get(tr.article_id)
            if not article:
                continue
            try:
                result = ai.translate_article({"title": article.title, "summary": article.summary, "content": article.content, "seo_title": article.seo_title, "meta_description": article.meta_description, "tags": article.tags}, tr.language)
                tr.title = result.get("title", article.title)
                tr.summary = result.get("summary", article.summary)
                tr.content = result.get("content", article.content)
                tr.seo_title = result.get("seo_title", tr.title)
                tr.meta_description = result.get("meta_description", tr.summary[:160] if tr.summary else "")
                tr.tags = result.get("tags", article.tags)
                tr.slug = slugify(tr.title)
                tr.status = "translated"
                tr.last_error = ""
                tr.updated_at = datetime.utcnow()
            except Exception as e:
                tr.status = "pending"
                tr.last_error = str(e)
        db.add(FetchLog(level="INFO", message=f"Translation job processed: {len(pending)}"))
        db.commit()
    except Exception as e:
        db.add(FetchLog(level="ERROR", message=f"translation pipeline: {str(e)}"))
        db.commit()
    finally:
        db.close()


def run_fetch_pipeline() -> None:
    db = SessionLocal()
    ai = AIEngine()
    try:
        items = fetch_rss_items()
        for item in items:
            if db.query(Article).filter(Article.original_hash == item["hash"]).first():
                continue
            if len(item["content"]) < 80:
                continue
            processed = ai.process_article(item["title"], item["content"])
            article = Article(
                original_hash=item["hash"],
                source_title=item["title"],
                source_url=item["url"],
                title=processed["title"],
                summary=processed["summary"],
                content=processed["content"],
                seo_title=processed["seo_title"],
                meta_description=processed.get("meta_description", processed["summary"][:160]),
                tags=processed["tags"],
                category=processed["category"],
                image_url=item["image_url"] or get_image_for_article(processed["category"]),
                language="az",
                status="published" if settings.publish_mode == "auto" else "draft",
                published_at=datetime.utcnow() if settings.publish_mode == "auto" else None,
            )
            db.add(article)
            db.flush()
            create_translation_jobs(db, article)
        db.add(FetchLog(level="INFO", message=f"Fetched {len(items)} items"))
        db.commit()
    except Exception as e:
        db.add(FetchLog(level="ERROR", message=str(e)))
        db.commit()
    finally:
        db.close()
