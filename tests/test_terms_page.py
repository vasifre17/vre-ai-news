import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("SECRET_KEY", "terms-page-test-secret-key")
os.environ.setdefault("ADMIN_USERNAME", "terms_admin")
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


def test_terms_page_contains_required_sections_and_footer_link():
    prepare_public_pages()
    client = TestClient(app)

    response = client.get("/terms")

    assert response.status_code == 200
    assert "Terms of Use" in response.text
    assert "Content ownership" in response.text
    assert "User responsibilities" in response.text
    assert "Copyright notice" in response.text
    assert "Disclaimer" in response.text
    assert "vreyc.com@gmail.com" in response.text
    assert '<a class="footer-policy-link" href="/terms">Terms of Use</a>' in response.text


def test_public_footer_links_to_terms_of_use():
    prepare_public_pages()
    client = TestClient(app)

    response = client.get("/en/")

    assert response.status_code == 200
    assert '<a class="footer-policy-link" href="/terms">Terms of Use</a>' in response.text
