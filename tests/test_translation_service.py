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

import ai.translation_service as translation_service
from ai.translation_service import enqueue_missing_translations, get_or_create_translation
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


def test_enqueue_missing_translations_recovers_existing_row_after_duplicate_integrity_error(monkeypatch):
    prepare_translation_service_test()
    db = SessionLocal()
    try:
        article = Article(title="Queue duplicate news", slug="queue-duplicate-news", status="published")
        db.add(article)
        db.flush()
        existing = ArticleTranslation(article_id=article.id, language="en", status="pending")
        db.add(existing)
        db.commit()

        def raise_duplicate(_db, _article, _language):
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))

        monkeypatch.setattr(translation_service, "missing_translation_languages", lambda _article: ["en"])
        monkeypatch.setattr(translation_service, "get_or_create_translation", raise_duplicate)

        queued = enqueue_missing_translations(db, article)

        assert queued == ["en"]
        assert db.query(ArticleTranslation).filter(ArticleTranslation.article_id == article.id, ArticleTranslation.language == "en").count() == 1
    finally:
        db.close()


def _set_setting(db, key, value):
    from database.models import Setting

    row = db.query(Setting).filter(Setting.key == key).first()
    if not row:
        row = Setting(key=key)
        db.add(row)
    row.value = value
    db.commit()


def _clear_ai_settings(db):
    from database.models import Setting

    db.query(Setting).filter(Setting.key.in_(["openai_api_key", "ai_translation_enabled", "ai_seo_enabled"])).delete(synchronize_session=False)
    db.commit()


def test_ai_translation_configured_uses_valid_env_key_when_database_key_missing(monkeypatch):
    prepare_translation_service_test()
    db = SessionLocal()
    try:
        _clear_ai_settings(db)
        monkeypatch.setattr(translation_service.openai_runtime_settings.__globals__["settings"], "openai_api_key", "sk-env-valid")

        runtime = translation_service.openai_runtime_settings()

        assert runtime["configured"] is True
        assert runtime["api_key"] == "sk-env-valid"
        assert runtime["translation_enabled"] is True
        assert runtime["seo_enabled"] is True
        assert translation_service.is_ai_translation_configured() is True
    finally:
        db.close()


def test_ai_translation_configured_uses_valid_env_key_when_database_key_invalid(monkeypatch):
    prepare_translation_service_test()
    db = SessionLocal()
    try:
        _clear_ai_settings(db)
        _set_setting(db, "openai_api_key", "")
        monkeypatch.setattr(translation_service.openai_runtime_settings.__globals__["settings"], "openai_api_key", "sk-env-valid")

        runtime = translation_service.openai_runtime_settings()

        assert runtime["configured"] is True
        assert runtime["api_key"] == "sk-env-valid"
        assert translation_service.is_ai_translation_configured() is True
    finally:
        db.close()


def test_ai_translation_configured_uses_valid_database_key_without_env(monkeypatch):
    prepare_translation_service_test()
    db = SessionLocal()
    try:
        _clear_ai_settings(db)
        _set_setting(db, "openai_api_key", "sk-db-valid")
        monkeypatch.setattr(translation_service.openai_runtime_settings.__globals__["settings"], "openai_api_key", "")

        runtime = translation_service.openai_runtime_settings()

        assert runtime["configured"] is True
        assert runtime["api_key"] == "sk-db-valid"
        assert translation_service.is_ai_translation_configured() is True
    finally:
        db.close()
