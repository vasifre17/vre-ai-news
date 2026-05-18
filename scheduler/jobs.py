from datetime import datetime
from database.session import SessionLocal
from database.models import Article, FetchLog, ArticleNarration
from scraper.fetcher import fetch_rss_items
from ai.pipeline import AIEngine
from ai.image_service import get_image_for_article
from ai.audio_service import AudioNarrationService
from config import settings


def queue_narration(db, article: Article) -> None:
    if not article.narration_enabled:
        return
    language = (article.language or "az").lower()
    row = db.query(ArticleNarration).filter(ArticleNarration.article_id == article.id, ArticleNarration.language == language).first()
    if row:
        row.status = "pending"
        row.error_message = None
        row.updated_at = datetime.utcnow()
        return
    db.add(ArticleNarration(article_id=article.id, language=language, status="pending", provider="openai"))


def generate_pending_narrations() -> None:
    db = SessionLocal()
    service = AudioNarrationService()
    try:
        pending = db.query(ArticleNarration).join(Article).filter(ArticleNarration.status == "pending", Article.status == "published").limit(6).all()
        for narration in pending:
            narration.status = "generating"
            narration.updated_at = datetime.utcnow()
            db.commit()
            article = narration.article
            try:
                audio_path, file_size = service.generate(article.id, narration.language, article.title, article.summary or "", article.content or "")
                narration.audio_path = audio_path
                narration.file_size_bytes = file_size
                narration.status = "ready"
                narration.error_message = None
            except Exception as e:
                narration.status = "failed"
                narration.error_message = str(e)
            narration.updated_at = datetime.utcnow()
            db.commit()
    except Exception as e:
        db.add(FetchLog(level="ERROR", message=f"Narration pipeline failed: {e}"))
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
                tags=processed["tags"],
                category=processed["category"],
                image_url=item["image_url"] or get_image_for_article(processed["category"]),
                language=processed["language"],
                status="published" if settings.publish_mode == "auto" else "draft",
                published_at=datetime.utcnow() if settings.publish_mode == "auto" else None,
            )
            db.add(article)
            db.flush()
            if article.status == "published":
                queue_narration(db, article)
        db.add(FetchLog(level="INFO", message=f"Fetched {len(items)} items"))
        db.commit()
    except Exception as e:
        db.add(FetchLog(level="ERROR", message=str(e)))
        db.commit()
    finally:
        db.close()
