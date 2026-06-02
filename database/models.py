from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, UniqueConstraint, Date
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Article(Base):
    __tablename__ = "articles"
    id = Column(Integer, primary_key=True)
    original_hash = Column(String(128), unique=True, index=True)
    source_title = Column(String(500))
    source_url = Column(String(1000))
    title = Column(String(500), index=True)
    slug = Column(String(500), unique=True, index=True, nullable=True)
    summary = Column(Text)
    content = Column(Text)
    seo_title = Column(String(500))
    meta_description = Column(Text)
    tags = Column(String(500))
    category = Column(String(100), index=True)
    image_url = Column(String(1000))
    language = Column(String(20), default="az")
    status = Column(String(20), default="draft")
    narration_enabled = Column(Boolean, default=True)
    is_featured = Column(Boolean, default=False, index=True)
    is_trending = Column(Boolean, default=False, index=True)
    homepage_order = Column(Integer, default=100, index=True)
    view_count = Column(Integer, default=0, index=True)
    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    revisions = relationship("ArticleRevision", back_populates="article", cascade="all, delete-orphan")
    narrations = relationship("ArticleNarration", back_populates="article", cascade="all, delete-orphan")
    translations = relationship("ArticleTranslation", back_populates="article", cascade="all, delete-orphan")
    views = relationship("ArticleView", back_populates="article", cascade="all, delete-orphan")


class ArticleView(Base):
    __tablename__ = "article_views"
    __table_args__ = (UniqueConstraint("article_id", "visitor_key", "visit_date", name="uq_article_view_unique_visit"),)

    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"), index=True, nullable=False)
    visitor_key = Column(String(128), index=True, nullable=False)
    session_id = Column(String(64), index=True, nullable=True)
    ip_address = Column(String(64), index=True, nullable=True)
    user_agent = Column(String(500), nullable=True)
    referrer = Column(String(1000), nullable=True)
    language = Column(String(20), default="az", index=True)
    visit_date = Column(Date, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    article = relationship("Article", back_populates="views")


class ArticleTranslation(Base):
    __tablename__ = "article_translations"
    __table_args__ = (UniqueConstraint("article_id", "language", name="uq_article_translation_lang"),)

    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"), index=True)
    language = Column(String(20), default="az", index=True)
    title = Column(String(500))
    slug = Column(String(500), index=True)
    summary = Column(Text)
    content = Column(Text)
    seo_title = Column(String(500))
    meta_description = Column(Text)
    tags = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    article = relationship("Article", back_populates="translations")


class ArticleNarration(Base):
    __tablename__ = "article_narrations"
    __table_args__ = (UniqueConstraint("article_id", "language", name="uq_article_narration_lang"),)

    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"), index=True)
    language = Column(String(20), default="az", index=True)
    status = Column(String(20), default="pending", index=True)  # pending|generating|ready|failed
    audio_path = Column(String(1000), nullable=True)
    error_message = Column(Text, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    provider = Column(String(50), default="openai")
    allow_download = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    article = relationship("Article", back_populates="narrations")


class ArticleRevision(Base):
    __tablename__ = "article_revisions"
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"))
    title = Column(String(500))
    content = Column(Text)
    image_url = Column(String(1000))
    category = Column(String(100))
    seo_title = Column(String(500))
    tags = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)
    article = relationship("Article", back_populates="revisions")


class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, index=True)
    slug = Column(String(120), unique=True, index=True)
    description = Column(Text)
    color = Column(String(20), default="#48a6ff")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class MediaAsset(Base):
    __tablename__ = "media_assets"
    id = Column(Integer, primary_key=True)
    filename = Column(String(500))
    path = Column(String(1000), unique=True)
    content_type = Column(String(120))
    size_bytes = Column(Integer, default=0)
    alt_text = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)


class Setting(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True)
    value = Column(String(500))


class FetchLog(Base):
    __tablename__ = "fetch_logs"
    id = Column(Integer, primary_key=True)
    level = Column(String(20), default="INFO")
    message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
