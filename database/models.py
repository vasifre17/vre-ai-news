from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, UniqueConstraint
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
    tags = Column(String(500))
    category = Column(String(100), index=True)
    image_url = Column(String(1000))
    language = Column(String(20), default="az")
    status = Column(String(20), default="draft")
    narration_enabled = Column(Boolean, default=True)
    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    revisions = relationship("ArticleRevision", back_populates="article", cascade="all, delete-orphan")
    narrations = relationship("ArticleNarration", back_populates="article", cascade="all, delete-orphan")


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
