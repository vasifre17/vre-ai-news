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
            existing.published_at = datetime(2026, 6, 9, 22, 14)
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
            published_at=datetime(2026, 6, 9, 22, 14),
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


def test_public_article_image_metadata_uses_publish_timestamp_and_views():
    slug = seed_article()
    client = TestClient(app)

    response = client.get(f"/az/{slug}")

    assert response.status_code == 200
    html = response.text
    assert "09 İyun 2026 • 22:14 • 1 baxış" in html
    assert "Dərc edilib: 22:14" in html
    assert "Mənbə: Vasif REYC" not in html
