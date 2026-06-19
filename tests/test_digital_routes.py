import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("SECRET_KEY", "digital-routes-test-secret-key")
os.environ.setdefault("ADMIN_USERNAME", "digital_admin")
os.environ.setdefault("SITE_URL", "https://vreyc.com")
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.NamedTemporaryFile(suffix='.db', delete=False).name}"
os.environ.setdefault("IMAGE_UPLOAD_DIR", tempfile.mkdtemp(prefix="vre-test-uploads-"))

from fastapi.testclient import TestClient

from database.session import init_db
from main import app, apply_schema_migrations, ensure_categories


def test_digital_public_routes_render_without_touching_news_routes():
    init_db()
    from database.session import SessionLocal

    db = SessionLocal()
    try:
        apply_schema_migrations(db)
        ensure_categories(db)
    finally:
        db.close()
    client = TestClient(app)

    expected_markers = {
        "/digital": "Premium Websites • SEO • AI Solutions",
        "/digital/projects": "BuildPro Construction",
        "/digital/projects/vreyc": "View Live Project",
        "/digital/projects/buildpro": "BuildPro Construction",
    }

    for path, marker in expected_markers.items():
        response = client.get(path)
        assert response.status_code == 200
        assert marker in response.text

    news_response = client.get("/az/")
    assert news_response.status_code == 200
    assert "Premium AI News Portal" in news_response.text
