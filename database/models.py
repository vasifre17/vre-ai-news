from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, UniqueConstraint, Float
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
    focus_keywords = Column(String(500))
    google_news_description = Column(Text)
    image_alt_text = Column(String(500))
    reading_time_minutes = Column(Integer, default=1)
    facebook_share_text = Column(Text)
    telegram_share_text = Column(Text)
    x_share_text = Column(Text)
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
    publish_at = Column(DateTime, nullable=True, index=True)
    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    revisions = relationship("ArticleRevision", back_populates="article", cascade="all, delete-orphan")
    narrations = relationship("ArticleNarration", back_populates="article", cascade="all, delete-orphan")
    translations = relationship("ArticleTranslation", back_populates="article", cascade="all, delete-orphan")
    views = relationship("ArticleView", back_populates="article", cascade="all, delete-orphan")


class ArticleView(Base):
    __tablename__ = "article_views"
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id", ondelete="CASCADE"), index=True)
    viewed_at = Column(DateTime, default=datetime.utcnow, index=True)
    visitor_key = Column(String(128), index=True)
    traffic_source = Column(String(120), default="Direct", index=True)
    path = Column(String(1000))
    language = Column(String(20), default="az", index=True)
    device_type = Column(String(40), default="desktop", index=True)
    country_code = Column(String(8), default="XX", index=True)
    country_name = Column(String(120), default="Unknown", index=True)
    is_admin_traffic = Column(Boolean, default=False, index=True)

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
    focus_keywords = Column(String(500))
    google_news_description = Column(Text)
    image_alt_text = Column(String(500))
    reading_time_minutes = Column(Integer, default=1)
    facebook_share_text = Column(Text)
    telegram_share_text = Column(Text)
    x_share_text = Column(Text)
    tags = Column(String(500))
    status = Column(String(20), default="published", index=True)  # pending|generating|draft|published|failed
    error_message = Column(Text, nullable=True)
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
    meta_description = Column(Text)
    focus_keywords = Column(String(500))
    google_news_description = Column(Text)
    image_alt_text = Column(String(500))
    reading_time_minutes = Column(Integer, default=1)
    facebook_share_text = Column(Text)
    telegram_share_text = Column(Text)
    x_share_text = Column(Text)
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
    url = Column(String(1000), unique=True)
    content_type = Column(String(120))
    mime_type = Column(String(120))
    size_bytes = Column(Integer, default=0)
    width = Column(Integer)
    height = Column(Integer)
    alt_text = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)


class Setting(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True)
    value = Column(String(500))


class MarketQuote(Base):
    __tablename__ = "market_quotes"
    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True, index=True)
    label = Column(String(50))
    value = Column(Float)
    quote_currency = Column(String(10), default="USD")
    source = Column(String(120))
    updated_at = Column(DateTime, default=datetime.utcnow, index=True)


class FetchLog(Base):
    __tablename__ = "fetch_logs"
    id = Column(Integer, primary_key=True)
    level = Column(String(20), default="INFO")
    message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
