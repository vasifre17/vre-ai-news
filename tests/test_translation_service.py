import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("SECRET_KEY", "translation-service-test-secret-key")
os.environ.setdefault("ADMIN_USERNAME", "translation_admin")
os.environ.setdefault("SITE_URL", "https://vreyc.com")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.NamedTemporaryFile(suffix='.db', delete=False).name}")
os.environ.setdefault("IMAGE_UPLOAD_DIR", tempfile.mkdtemp(prefix="vre-test-uploads-"))

from sqlalchemy.exc import IntegrityError

from ai.translation_service import get_or_create_translation
from database.models import Article, ArticleTranslation
from database.session import SessionLocal, init_db


def prepare_translation_service_test():
    init_db()
    db = SessionLocal()
    try:
        db.query(ArticleTranslation).delete()
        db.query(Article).delete()
        db.commit()
    finally:
        db.close()


def test_get_or_create_translation_returns_existing_row_without_insert():
    prepare_translation_service_test()
    db = SessionLocal()
    try:
        article = Article(title="Mövcud tərcümə xəbəri", slug="movcud-tercume-xeberi", status="published")
        db.add(article)
        db.flush()
        existing = ArticleTranslation(article_id=article.id, language="en", status="published", title="Existing")
        db.add(existing)
        db.commit()

        row = get_or_create_translation(db, article, "EN")

        assert row.id == existing.id
        assert row.title == "Existing"
        assert db.query(ArticleTranslation).filter(ArticleTranslation.article_id == article.id, ArticleTranslation.language == "en").count() == 1
    finally:
        db.close()


class _FakeQuery:
    def __init__(self, db):
        self.db = db

    def filter(self, *args):
        return self

    def first(self):
        self.db.first_calls += 1
        return None if self.db.first_calls == 1 else self.db.existing


class _IntegrityRaceDb:
    new = []

    def __init__(self, existing):
        self.existing = existing
        self.first_calls = 0
        self.added = []
        self.rolled_back = False

    def query(self, model):
        assert model is ArticleTranslation
        return _FakeQuery(self)

    def add(self, row):
        self.added.append(row)

    def flush(self):
        raise IntegrityError("INSERT", {}, Exception("duplicate key"))

    def rollback(self):
        self.rolled_back = True


def test_get_or_create_translation_recovers_existing_row_after_integrity_error():
    article = Article(id=170, title="Race condition news")
    existing = ArticleTranslation(id=9, article_id=article.id, language="en", status="pending")
    db = _IntegrityRaceDb(existing)

    row = get_or_create_translation(db, article, "en")

    assert row is existing
    assert db.rolled_back is True
    assert len(db.added) == 1
    assert db.first_calls == 2
