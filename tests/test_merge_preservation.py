import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

os.environ.setdefault("SECRET_KEY", "merge-preservation-test-secret-key")
os.environ.setdefault("ADMIN_USERNAME", "merge_admin")
os.environ.setdefault("SITE_URL", "https://vreyc.com")
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.NamedTemporaryFile(suffix='.db', delete=False).name}"
os.environ.setdefault("IMAGE_UPLOAD_DIR", tempfile.mkdtemp(prefix="vre-test-uploads-"))

from fastapi.testclient import TestClient

from cms.auth.security import hash_password
from config import settings
from database.models import Article, ArticleTranslation, ArticleView, MediaAsset
from database.session import SessionLocal, init_db
from main import app, apply_schema_migrations, ensure_categories


def seed_merge_feature_data():
    settings.admin_password_hash = hash_password("merge-password")
    init_db()
    db = SessionLocal()
    try:
        apply_schema_migrations(db)
        ensure_categories(db)
        if db.query(Article).filter(Article.original_hash == "merge-preservation-primary").first():
            return
        published_at = datetime.now(UTC) - timedelta(hours=2)
        article = Article(
            original_hash="merge-preservation-primary",
            source_title="Merge source",
            source_url="https://example.com/merge-source",
            title="Main features and SEO article",
            slug="main-features-seo-article",
            summary="Summary used by cards and feeds.",
            content="Article body used by structured data and admin filters.",
            seo_title="Merge SEO Title",
            meta_description="Merge SEO description for canonical and social cards.",
            tags="merge,seo,analytics",
            category="Technology",
            language="az",
            status="published",
            image_url="/uploads/images/missing-merge-image.jpg",
            is_featured=True,
            is_trending=True,
            homepage_order=1,
            view_count=7,
            published_at=published_at,
        )
        db.add(article)
        db.flush()
        db.add(
            ArticleTranslation(
                article_id=article.id,
                language="en",
                title="Translated merge SEO article",
                slug="translated-merge-seo-article",
                summary="Translated summary for cards and feeds.",
                content="Translated article body.",
                seo_title="Translated Merge SEO Title",
                meta_description="Translated social description.",
                tags="translation,seo",
            )
        )
        db.add(MediaAsset(filename="merge-image.jpg", path="/uploads/images/missing-merge-image.jpg", content_type="image/jpeg", size_bytes=1024))
        for index in range(5):
            db.add(
                ArticleView(
                    article_id=article.id,
                    visitor_key=f"visitor-{index}",
                    traffic_source="referral" if index % 2 else "direct",
                    viewed_at=published_at + timedelta(minutes=index),
                )
            )
        db.commit()
    finally:
        db.close()


def login(client: TestClient):
    response = client.post(
        "/admin/login",
        data={"username": settings.admin_username, "password": "merge-password"},
        follow_redirects=False,
    )
    assert response.status_code == 302


def test_public_seo_feeds_and_admin_features_survive_main_merge():
    seed_merge_feature_data()
    with TestClient(app) as client:
        home = client.get("/en/?q=Translated&category=Technology")
        assert home.status_code == 200
        assert "Translated merge SEO article" in home.text
        assert "https://vreyc.com/en/" in home.text
        assert "og:title" in home.text
        assert "twitter:card" in home.text

        article = client.get("/en/translated-merge-seo-article")
        assert article.status_code == 200
        assert "Translated Merge SEO Title" in article.text
        assert "https://vreyc.com/en/translated-merge-seo-article" in article.text
        assert "application/ld+json" in article.text
        assert "NewsArticle" in article.text
        assert "og:url" in article.text
        assert "twitter:title" in article.text
        assert "hreflang=\"az\"" in article.text
        assert "loading=\"lazy\"" in article.text or "fetchpriority=\"high\"" in article.text

        sitemap = client.get("/sitemap.xml")
        assert sitemap.status_code == 200
        assert "https://vreyc.com/en/translated-merge-seo-article" in sitemap.text

        news_sitemap = client.get("/news-sitemap.xml")
        assert news_sitemap.status_code == 200
        assert "Main features and SEO article" in news_sitemap.text

        rss = client.get("/rss.xml")
        assert rss.status_code == 200
        assert "Main features and SEO article" in rss.text
        assert "main-features-seo-article" in rss.text

        login(client)
        dashboard = client.get("/admin")
        assert dashboard.status_code == 200
        assert "VREYC Admin Dashboard" in dashboard.text
        assert "Analytics" in dashboard.text
        assert "most viewed" in dashboard.text

        filtered = client.get("/admin/articles?q=Translated&category=Technology&language=en&status=published")
        assert filtered.status_code == 200
        assert "Main features and SEO article" in filtered.text
        assert "SEO" in filtered.text

        seo = client.get("/admin/seo")
        assert seo.status_code == 200
        assert "SEO" in seo.text
        assert "main-features-seo-article" in seo.text

        media = client.get("/admin/media")
        assert media.status_code == 200
        assert "merge-image.jpg" in media.text


def reset_analytics_fixture_data():
    settings.admin_password_hash = hash_password("merge-password")
    init_db()
    db = SessionLocal()
    try:
        apply_schema_migrations(db)
        db.query(ArticleView).delete()
        db.query(ArticleTranslation).delete()
        db.query(MediaAsset).delete()
        db.query(Article).delete()
        db.commit()
        published_at = datetime.now(UTC) - timedelta(hours=1)
        high_fake = Article(
            original_hash="fake-view-count-high",
            title="Fake high counter article",
            slug="fake-high-counter-article",
            summary="Old seeded view count must be ignored.",
            content="Article body for analytics assertions.",
            category="Technology",
            language="az",
            status="published",
            view_count=650,
            published_at=published_at,
        )
        low_fake = Article(
            original_hash="fake-view-count-low",
            title="Fake low counter article",
            slug="fake-low-counter-article",
            summary="Real article_views rows must be counted.",
            content="Second article body for analytics assertions.",
            category="Business",
            language="az",
            status="published",
            view_count=3,
            published_at=published_at,
        )
        db.add_all([high_fake, low_fake])
        db.flush()
        db.add_all(
            [
                ArticleView(article_id=high_fake.id, visitor_key="repeat-reader", traffic_source="direct", viewed_at=published_at),
                ArticleView(article_id=high_fake.id, visitor_key="repeat-reader", traffic_source="direct", viewed_at=published_at + timedelta(minutes=1)),
                ArticleView(article_id=low_fake.id, visitor_key="single-reader", traffic_source="search", viewed_at=published_at + timedelta(minutes=2)),
            ]
        )
        db.commit()
        return high_fake.id, low_fake.id
    finally:
        db.close()


def test_admin_analytics_use_only_real_article_views_table():
    high_fake_id, low_fake_id = reset_analytics_fixture_data()
    from main import analytics_summary, article_analytics_context, top_category_rows

    db = SessionLocal()
    try:
        summary = analytics_summary(db)
        assert summary["total_views"] == 3
        assert summary["unique_visitors"] == 2
        assert summary["returning_visitors"] == 1
        assert {row["name"]: row["views"] for row in top_category_rows(db)} == {"Technology": 2, "Business": 1}

        high_fake = db.query(Article).get(high_fake_id)
        low_fake = db.query(Article).get(low_fake_id)
        assert article_analytics_context(db, high_fake)["publish_performance"]["total_views"] == 2
        assert article_analytics_context(db, low_fake)["publish_performance"]["total_views"] == 1
    finally:
        db.close()

    client = TestClient(app)
    login(client)
    dashboard = client.get("/admin")
    assert dashboard.status_code == 200
    assert "Real tracked views" in dashboard.text
    assert "653" not in dashboard.text
    assert "Fake high counter article" in dashboard.text
    assert "<strong>2</strong>" in dashboard.text

    article_list = client.get("/admin/articles?sort=most_viewed")
    assert article_list.status_code == 200
    assert "Fake high counter article" in article_list.text
    assert "Fake low counter article" in article_list.text
    assert "650" not in article_list.text


def test_scheduled_articles_use_request_time_visibility_without_status_mutation():
    seed_merge_feature_data()
    db = SessionLocal()
    try:
        future = datetime.utcnow() + timedelta(days=1)
        past = datetime.utcnow() - timedelta(minutes=5)
        if not db.query(Article).filter(Article.original_hash == "scheduled-future").first():
            db.add(
                Article(
                    original_hash="scheduled-future",
                    title="Future scheduled article",
                    slug="future-scheduled-article",
                    summary="Hidden until its scheduled publish time.",
                    content="Future scheduled body.",
                    category="Technology",
                    language="az",
                    status="scheduled",
                    publish_at=future,
                )
            )
        if not db.query(Article).filter(Article.original_hash == "scheduled-due").first():
            db.add(
                Article(
                    original_hash="scheduled-due",
                    title="Due scheduled article",
                    slug="due-scheduled-article",
                    summary="Visible once publish_at is due without mutating status.",
                    content="Due scheduled body.",
                    category="Technology",
                    language="az",
                    status="scheduled",
                    publish_at=past,
                )
            )
        db.commit()
    finally:
        db.close()

    with TestClient(app) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "Due scheduled article" in home.text
        assert "Future scheduled article" not in home.text

        rss = client.get("/rss.xml")
        assert rss.status_code == 200
        assert "Due scheduled article" in rss.text
        assert "Future scheduled article" not in rss.text

        article = client.get("/az/due-scheduled-article")
        assert article.status_code == 200
        future_article = client.get("/az/future-scheduled-article")
        assert future_article.status_code == 404

        sitemap = client.get("/sitemap.xml")
        assert sitemap.status_code == 200
        assert "due-scheduled-article" in sitemap.text
        assert "future-scheduled-article" not in sitemap.text

        news_sitemap = client.get("/news-sitemap.xml")
        assert news_sitemap.status_code == 200
        assert "Due scheduled article" in news_sitemap.text
        assert "Future scheduled article" not in news_sitemap.text

        db = SessionLocal()
        try:
            due = db.query(Article).filter(Article.original_hash == "scheduled-due").one()
            future = db.query(Article).filter(Article.original_hash == "scheduled-future").one()
            assert due.status == "scheduled"
            assert due.published_at is None
            assert future.status == "scheduled"
            assert future.published_at is None
        finally:
            db.close()
