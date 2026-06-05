import os
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
