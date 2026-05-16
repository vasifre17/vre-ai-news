from datetime import datetime
from database.session import SessionLocal
from database.models import Article, FetchLog
from scraper.fetcher import fetch_rss_items
from ai.pipeline import AIEngine
from ai.image_service import get_image_for_article
from config import settings


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
        db.add(FetchLog(level="INFO", message=f"Fetched {len(items)} items"))
        db.commit()
    except Exception as e:
        db.add(FetchLog(level="ERROR", message=str(e)))
        db.commit()
    finally:
        db.close()
