#!/usr/bin/env python3
"""Run local launch smoke checks for multilingual pages, narration, SEO, and admin auth."""

import os
import tempfile
import sys
from pathlib import Path
from datetime import UTC, datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("SECRET_KEY", "local-smoke-check-secret-key-change-before-prod")
os.environ.setdefault("ADMIN_USERNAME", "smoke_admin")
os.environ.setdefault("SITE_URL", "https://vreyc.com")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.NamedTemporaryFile(suffix='.db', delete=False).name}")

from fastapi.testclient import TestClient

from cms.auth.security import hash_password
from config import settings
from database.models import Article, ArticleNarration, ArticleTranslation
from database.session import SessionLocal, init_db
from main import app


def assert_contains(haystack: str, needle: str, label: str) -> None:
    if needle not in haystack:
        raise AssertionError(f"Missing {label}: {needle}")


def seed_data() -> None:
    settings.admin_password_hash = hash_password("smoke-password")
    init_db()
    db = SessionLocal()
    try:
        article = Article(
            original_hash="smoke-check-article",
            source_title="Smoke source",
            source_url="https://example.com/source",
            title="Azərbaycan xəbəri",
            slug="azerbaycan-xeberi",
            summary="Qısa xülasə",
            content="Tam məqalə mətni.",
            seo_title="Azərbaycan xəbəri SEO",
            tags="news,smoke",
            category="World",
            language="az",
            status="published",
            image_url="/static/uploads/images/missing-smoke.jpg",
            published_at=datetime.now(UTC),
        )
        db.add(article)
        db.flush()
        db.add(
            ArticleTranslation(
                article_id=article.id,
                language="en",
                title="Azerbaijan news",
                slug="azerbaijan-news-en",
                summary="Short summary",
                content="Full article text.",
                seo_title="Azerbaijan news SEO",
                tags="news,smoke",
            )
        )
        db.add(ArticleNarration(article_id=article.id, language="az", status="ready", audio_path="/static/audio/smoke-az.mp3"))
        db.add(ArticleNarration(article_id=article.id, language="en", status="ready", audio_path="/static/audio/smoke-en.mp3"))
        db.commit()
    finally:
        db.close()


def main() -> int:
    seed_data()
    client = TestClient(app)

    en_home = client.get("/en/")
    en_home.raise_for_status()
    assert_contains(en_home.text, "Azerbaijan news", "English translated headline")
    assert_contains(en_home.text, "https://vreyc.com/en/", "English canonical URL")
    assert_contains(en_home.text, "image-placeholder", "VREYC placeholder for missing uploaded image")

    article = client.get("/en/azerbaijan-news-en")
    article.raise_for_status()
    assert_contains(article.text, "Azerbaijan news SEO", "translated SEO title")
    assert_contains(article.text, "https://vreyc.com/en/azerbaijan-news-en", "article canonical URL")
    assert_contains(article.text, "https://vreyc.com/assets/og-cover.jpg", "fallback social image for missing upload")
    assert_contains(article.text, "/static/audio/smoke-en.mp3", "English narration audio")
    assert_contains(article.text, 'hreflang="az"', "alternate language metadata")

    legacy_article = client.get("/en/article/azerbaijan-news-en")
    legacy_article.raise_for_status()
    assert_contains(legacy_article.text, "https://vreyc.com/en/azerbaijan-news-en", "legacy article route canonical URL")

    sitemap = client.get("/sitemap.xml")
    sitemap.raise_for_status()
    assert_contains(sitemap.text, "https://vreyc.com/", "sitemap root URL")
    assert_contains(sitemap.text, "https://vreyc.com/en/azerbaijan-news-en", "sitemap translated article URL")

    robots = client.get("/robots.txt")
    robots.raise_for_status()
    assert_contains(robots.text, "Sitemap: https://vreyc.com/sitemap.xml", "robots sitemap URL")
    assert_contains(robots.text, "Disallow: /admin", "robots admin exclusion")

    login = client.post(
        "/admin/login",
        data={"username": settings.admin_username, "password": "smoke-password"},
        follow_redirects=False,
    )
    if login.status_code != 302:
        raise AssertionError(f"Admin login failed with HTTP {login.status_code}")
    dashboard = client.get("/admin")
    dashboard.raise_for_status()
    assert_contains(dashboard.text, "VREYC Admin Dashboard", "admin dashboard")

    print("Production smoke checks passed: multilingual, image fallback, AI audio narration, SEO, sitemap, robots, and admin auth.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
