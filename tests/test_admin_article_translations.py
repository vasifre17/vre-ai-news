import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("SECRET_KEY", "article-translation-test-secret-key")
os.environ.setdefault("ADMIN_USERNAME", "article_admin")
os.environ.setdefault("SITE_URL", "https://vreyc.com")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.NamedTemporaryFile(suffix='.db', delete=False).name}")
os.environ.setdefault("IMAGE_UPLOAD_DIR", tempfile.mkdtemp(prefix="vre-test-uploads-"))

from fastapi.testclient import TestClient

from database.models import Article, ArticleTranslation
from database.session import SessionLocal, init_db
from main import app, apply_schema_migrations, ensure_categories, require_auth


def prepare_article_translation_test():
    init_db()
    db = SessionLocal()
    try:
        apply_schema_migrations(db)
        ensure_categories(db)
        db.query(ArticleTranslation).delete()
        db.query(Article).delete()
        db.commit()
    finally:
        db.close()


def test_new_article_does_not_duplicate_manual_translation_when_queueing_missing_languages():
    prepare_article_translation_test()

    app.dependency_overrides[require_auth] = lambda: None
    try:
        with TestClient(app) as client:
            response = client.post(
                "/admin/articles/new",
                data={
                    "status": "published",
                    "title_az": "Yeni Azərbaycan xəbəri",
                    "slug_az": "yeni-azerbaycan-xeberi",
                    "summary_az": "Azərbaycan dilində xülasə.",
                    "content_az": "<p>Azərbaycan dili əsas məqalə mətnidir.</p>",
                    "category": "Technology",
                    "title_en": "New Azerbaijani news",
                    "slug_en": "new-azerbaijani-news",
                    "summary_en": "English summary.",
                    "content_en": "<p>English translation already exists.</p>",
                    "translation_status_en": "published",
                },
                follow_redirects=False,
            )
    finally:
        app.dependency_overrides.pop(require_auth, None)

    assert response.status_code == 302
    assert response.headers["location"] == "/admin/articles"

    db = SessionLocal()
    try:
        article = db.query(Article).filter(Article.slug == "yeni-azerbaycan-xeberi").one()
        translations = db.query(ArticleTranslation).filter(ArticleTranslation.article_id == article.id).all()
        languages = sorted(row.language for row in translations)
        assert languages == ["en", "es", "ru", "tr", "zh"]
        assert sum(1 for row in translations if row.language == "en") == 1
        en_translation = next(row for row in translations if row.language == "en")
        assert en_translation.title == "New Azerbaijani news"
        assert en_translation.status == "published"
        assert article.language == "az"
    finally:
        db.close()
