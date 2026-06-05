import os
import sys
import tempfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("SECRET_KEY", "media-upload-test-secret-key")
os.environ.setdefault("ADMIN_USERNAME", "media_admin")
os.environ.setdefault("SITE_URL", "https://vreyc.com")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.NamedTemporaryFile(suffix='.db', delete=False).name}")

from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from cms.auth.security import hash_password
from config import settings
from database.models import MediaAsset
from database.session import SessionLocal, init_db
import main
from main import app, apply_schema_migrations, save_image_upload


def build_large_png(width: int = 1600, height: int = 1600) -> bytes:
    image = Image.frombytes("RGB", (width, height), os.urandom(width * height * 3))
    output = BytesIO()
    image.save(output, format="PNG", compress_level=0)
    return output.getvalue()


def prepare_media_upload_test(tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(main, "UPLOAD_DIR", upload_dir)
    settings.admin_password_hash = hash_password("media-password")
    init_db()
    db = SessionLocal()
    try:
        apply_schema_migrations(db)
        db.query(MediaAsset).delete()
        db.commit()
    finally:
        db.close()
    return upload_dir


def login(client: TestClient):
    response = client.post(
        "/admin/login",
        data={"username": settings.admin_username, "password": "media-password"},
        follow_redirects=False,
    )
    assert response.status_code == 302


def test_media_library_accepts_large_png_upload(tmp_path, monkeypatch):
    upload_dir = prepare_media_upload_test(tmp_path, monkeypatch)
    png_bytes = build_large_png()

    assert len(png_bytes) > 1024 * 1024
    assert len(png_bytes) <= main.MAX_UPLOAD_IMAGE_BYTES

    with TestClient(app) as client:
        login(client)
        response = client.post(
            "/admin/media",
            files=[("files", ("large-library-upload.png", png_bytes, "image/png"))],
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers["location"] == "/admin/media"
        media_page = client.get("/admin/media")
        assert media_page.status_code == 200
        assert "large-library-upload.png" in media_page.text

    saved_files = list(upload_dir.glob("large-library-upload-*.png"))
    assert len(saved_files) == 1
    assert saved_files[0].stat().st_size == len(png_bytes)


def test_save_image_upload_rejects_files_over_twenty_mb(tmp_path, monkeypatch):
    prepare_media_upload_test(tmp_path, monkeypatch)
    too_large_upload = SimpleNamespace(
        filename="too-large.png",
        content_type="image/png",
        file=BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * main.MAX_UPLOAD_IMAGE_BYTES),
    )

    try:
        save_image_upload(too_large_upload)
    except HTTPException as exc:
        assert exc.status_code == 413
        assert "20 MB" in exc.detail
    else:
        raise AssertionError("Expected uploads larger than 20 MB to be rejected")

    assert not list((tmp_path / "uploads").glob("too-large-*.png"))
