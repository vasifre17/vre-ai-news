import os
from datetime import UTC, datetime
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("SECRET_KEY", "analytics-test-secret-key")
os.environ.setdefault("ADMIN_USERNAME", "analytics_admin")
os.environ.setdefault("SITE_URL", "https://vreyc.com")
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.NamedTemporaryFile(suffix='.db', delete=False).name}"
os.environ.setdefault("IMAGE_UPLOAD_DIR", tempfile.mkdtemp(prefix="vre-test-uploads-"))

from fastapi.testclient import TestClient

from database.models import Article
from database.session import init_db
from main import app, apply_schema_migrations, ensure_categories


def prepare_public_pages():
    init_db()
    from database.session import SessionLocal

    db = SessionLocal()
    try:
        apply_schema_migrations(db)
        ensure_categories(db)
    finally:
        db.close()


def test_public_pages_load_google_analytics_tag():
    prepare_public_pages()
    client = TestClient(app)

    response = client.get("/en/")

    assert response.status_code == 200
    assert "https://www.googletagmanager.com/gtag/js?id=G-HHCSL6WB2H" in response.text
    assert "gtag('config', \"G-HHCSL6WB2H\")" in response.text


def test_admin_pages_do_not_load_google_analytics_tag():
    client = TestClient(app)

    response = client.get("/admin/login")

    assert response.status_code == 200
    assert "googletagmanager.com/gtag/js" not in response.text
    assert "G-HHCSL6WB2H" not in response.text


def seed_public_article():
    prepare_public_pages()
    from database.session import SessionLocal

    db = SessionLocal()
    try:
        existing = db.query(Article).filter(Article.original_hash == "adsense-verification-article").first()
        if existing:
            return existing.slug
        article = Article(
            original_hash="adsense-verification-article",
            source_title="AdSense source",
            source_url="https://example.com/adsense-source",
            title="AdSense Verification Article",
            slug="adsense-verification-article",
            summary="Article summary for AdSense verification tests.",
            content="Article body for AdSense verification tests.",
            seo_title="AdSense Verification Article",
            meta_description="Article description for AdSense verification tests.",
            tags="adsense,verification",
            category="Technology",
            language="en",
            status="published",
            is_featured=True,
            homepage_order=1,
            published_at=datetime.now(UTC),
        )
        db.add(article)
        db.commit()
        return article.slug
    finally:
        db.close()


def assert_adsense_verification_script(html: str, publisher_id: str = "ca-pub-1323022477437742"):
    expected = (
        '<script async src="https://pagead2.googlesyndication.com/pagead/js/'
        f'adsbygoogle.js?client={publisher_id}" crossorigin="anonymous"></script>'
    )
    assert expected in html


def test_public_pages_load_adsense_verification_script():
    slug = seed_public_article()
    client = TestClient(app)

    for path in ("/en/", "/privacy", "/terms", f"/en/{slug}", "/missing-page"):
        response = client.get(path)

        assert response.status_code in {200, 404}
        assert_adsense_verification_script(response.text)


def test_admin_pages_do_not_load_adsense_verification_script():
    client = TestClient(app)

    response = client.get("/admin/login")

    assert response.status_code == 200
    assert "pagead2.googlesyndication.com/pagead/js/adsbygoogle.js" not in response.text
    assert "ca-pub-1323022477437742" not in response.text
