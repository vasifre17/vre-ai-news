import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("SECRET_KEY", "article-cleanup-test-secret-key")
os.environ.setdefault("ADMIN_USERNAME", "article_cleanup_admin")
os.environ.setdefault("SITE_URL", "https://vreyc.com")
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.NamedTemporaryFile(suffix='.db', delete=False).name}"
os.environ.setdefault("IMAGE_UPLOAD_DIR", tempfile.mkdtemp(prefix="vre-test-uploads-"))

from fastapi.testclient import TestClient

from database.models import Article, ArticleView
from database.session import init_db
from main import app, apply_schema_migrations, ensure_categories


def prepare_database():
    init_db()
    from database.session import SessionLocal

    db = SessionLocal()
    try:
        apply_schema_migrations(db)
        ensure_categories(db)
    finally:
        db.close()


def seed_article():
    prepare_database()
    from database.session import SessionLocal

    db = SessionLocal()
    try:
        existing = db.query(Article).filter(Article.original_hash == "article-page-cleanup").first()
        if existing:
            db.query(ArticleView).filter(ArticleView.article_id == existing.id).delete()
            existing.published_at = datetime(2026, 6, 9, 19, 7)
            db.commit()
            return existing.slug
        article = Article(
            original_hash="article-page-cleanup",
            source_title="Cleanup source",
            source_url="https://example.com/cleanup-source",
            title="Article Page Cleanup Test",
            slug="article-page-cleanup-test",
            summary="This summary should not appear in the article header.",
            content="Article body for article header cleanup tests.",
            seo_title="Article Page Cleanup Test",
            meta_description="Article description for cleanup tests.",
            tags="cleanup,article",
            category="Technology",
            language="az",
            status="published",
            published_at=datetime(2026, 6, 9, 19, 7),
        )
        db.add(article)
        db.commit()
        return article.slug
    finally:
        db.close()


def test_public_article_header_only_shows_category_and_title_before_image_metadata():
    slug = seed_article()
    client = TestClient(app)

    response = client.get(f"/az/{slug}")

    assert response.status_code == 200
    html = response.text
    hero = html.split('<div class="container section page-shell article-shell">', 1)[0]
    assert '<span class="badge article-category-badge">Texnologiya</span>' in hero
    assert '<h1>Article Page Cleanup Test</h1>' in hero
    assert "This summary should not appear in the article header." not in hero
    assert "Tarix:" not in hero
    assert "Baxış:" not in hero
    assert "Müəllif:" not in hero


def test_public_article_image_metadata_uses_baku_timestamp_once_with_views():
    slug = seed_article()
    client = TestClient(app)

    response = client.get(f"/az/{slug}")

    assert response.status_code == 200
    html = response.text
    assert "09 İyun 2026 • 23:07 • 1 baxış" in html
    assert "Dərc edilib:" not in html
    assert "Mənbə: Vasif REYC" not in html


def test_homepage_latest_news_includes_hero_slider_articles():
    prepare_database()
    from database.session import SessionLocal

    db = SessionLocal()
    try:
        db.query(ArticleView).delete()
        db.query(Article).filter(Article.original_hash.like("homepage-hero-feed-%")).delete(synchronize_session=False)
        for index in range(6):
            article_number = index + 1
            db.add(
                Article(
                    original_hash=f"homepage-hero-feed-{article_number}",
                    source_title=f"Homepage source {article_number}",
                    source_url=f"https://example.com/homepage-{article_number}",
                    title=f"Homepage hero feed article {article_number}",
                    slug=f"homepage-hero-feed-article-{article_number}",
                    summary="Latest feed must include hero slider stories.",
                    content="Homepage feed regression body.",
                    seo_title=f"Homepage hero feed article {article_number}",
                    meta_description="Homepage feed regression description.",
                    category="Technology",
                    language="az",
                    status="published",
                    published_at=datetime(2026, 6, 9, 12, index),
                )
            )
        db.commit()
    finally:
        db.close()

    client = TestClient(app)
    response = client.get("/az/")

    assert response.status_code == 200
    html = response.text
    latest_section = html.split('<h2 id="latest-news-title">', 1)[1].split('<aside class="trending-sidebar', 1)[0]
    assert "Homepage hero feed article 6" in latest_section
    assert "Homepage hero feed article 5" in latest_section
    assert "Homepage hero feed article 4" in latest_section
    assert "Homepage hero feed article 3" in latest_section
    assert "Homepage hero feed article 2" in latest_section
