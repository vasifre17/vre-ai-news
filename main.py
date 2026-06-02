from datetime import datetime
from types import SimpleNamespace
import re
import shutil
from pathlib import Path
from uuid import uuid4
from sqlalchemy import or_, text
from sqlalchemy.orm import selectinload
from fastapi import FastAPI, Request, Depends, Form, HTTPException, UploadFile, File
from PIL import Image, UnidentifiedImageError
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from apscheduler.schedulers.background import BackgroundScheduler

from config import settings
from database.session import SessionLocal, init_db
from database.models import Article, ArticleRevision, FetchLog, Setting, ArticleNarration, ArticleTranslation, Category, MediaAsset
from cms.auth.security import is_authenticated, set_session, clear_session, verify_password
from scheduler.jobs import run_fetch_pipeline, queue_narration, generate_pending_narrations
from ai.pipeline import AIEngine

app = FastAPI(title=settings.app_name)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
templates = Jinja2Templates(directory="templates")
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
scheduler = BackgroundScheduler()
ai_engine = AIEngine()
SUPPORTED_LANGUAGES = ["az", "en", "ru", "tr", "zh", "es"]
LANGUAGE_LABELS = {"az": "Azerbaijani", "en": "English", "ru": "Russian", "tr": "Turkish", "zh": "Chinese", "es": "Spanish"}
UPLOAD_DIR = Path(settings.image_upload_dir)
UPLOAD_URL_PREFIX = settings.image_upload_url_prefix
LEGACY_UPLOAD_DIRS = (Path("uploads"), Path("static/uploads/images"), Path("/app/static/uploads/images"))
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
IMAGE_VARIANT_WIDTHS = (480, 960, 1440)


def ensure_upload_dir() -> None:
    """Create the persistent host upload directory before serving or saving images."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


ensure_upload_dir()
app.mount(UPLOAD_URL_PREFIX, StaticFiles(directory=UPLOAD_DIR), name="uploaded_images")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/assets", StaticFiles(directory="assets"), name="assets")


PUBLIC_LABELS = {
    "az": {
        "latest": "Son",
        "latest_news": "Son xəbərlər",
        "most_watched": "Ən çox baxılanlar",
        "related": "Oxşar xəbərlər",
        "more_stories": "Daha çox xəbər",
        "search": "Axtar",
        "search_placeholder": "Axtar",
        "news": "Xəbər",
        "top_story": "Əsas xəbər",
        "featured": "Seçilmiş",
        "editor_picks": "Redaktorun AI seçimləri",
        "trending": "Trend",
        "audio_narration": "Audio səsləndirmə",
        "share": "Paylaş",
        "play": "Oxut",
        "pause": "Fasilə",
        "download": "Yüklə",
        "narration_pending": "Səsləndirmə hazırlanır. Məqalənin dərc edilməsi bloklanmır.",
        "no_articles": "Hələ dərc edilmiş məqalə yoxdur. Tezliklə yenidən yoxlayın.",
        "related_empty": "Redaksiya böyüdükcə oxşar xəbərlər burada görünəcək.",
        "footer_tagline": "Yüksək səviyyəli AI xəbər analitikası",
        "about": "Haqqımızda",
        "contact": "Əlaqə",
        "site_name": "Adı",
        "domain_owner": "Domen adının sahibi",
        "mobile_whatsapp": "Mobil və WhatsApp",
        "youtube": "YouTube",
        "tiktok": "TikTok",
        "founder_ceo": "VREYC-in təsisçisi və baş direktoru Vasif Cəbrayıllıdır.",
        "email": "E-poçt",
        "more_categories": "Daha çox kateqoriya",
    },
    "en": {
        "latest": "Latest",
        "latest_news": "Latest news",
        "most_watched": "Most watched",
        "related": "Related",
        "more_stories": "More stories",
        "search": "Search",
        "search_placeholder": "Search",
        "news": "News",
        "top_story": "Top Story",
        "featured": "Featured",
        "editor_picks": "Editor's AI picks",
        "trending": "Trending",
        "audio_narration": "Audio narration",
        "share": "Share",
        "play": "Play",
        "pause": "Pause",
        "download": "Download",
        "narration_pending": "Narration is being prepared. Article publishing is not blocked.",
        "no_articles": "No published articles yet. Please check back soon.",
        "related_empty": "Related articles will appear here as the newsroom grows.",
        "footer_tagline": "Premium AI news intelligence",
        "about": "About",
        "contact": "Contact",
        "site_name": "Name",
        "domain_owner": "Domain owner",
        "mobile_whatsapp": "Mobile and WhatsApp",
        "youtube": "YouTube",
        "tiktok": "TikTok",
        "founder_ceo": "VREYC founder and chief executive is Vasif Jabrayilli.",
        "email": "Email",
        "more_categories": "More categories",
    },
    "ru": {
        "latest": "Последнее",
        "latest_news": "Последние новости",
        "most_watched": "Самые просматриваемые",
        "related": "Похожие новости",
        "more_stories": "Больше материалов",
        "search": "Поиск",
        "search_placeholder": "Поиск",
        "news": "Новость",
        "top_story": "Главная новость",
        "featured": "Избранное",
        "editor_picks": "Выбор AI-редакции",
        "trending": "В тренде",
        "audio_narration": "Аудиоозвучка",
        "share": "Поделиться",
        "play": "Воспроизвести",
        "pause": "Пауза",
        "download": "Скачать",
        "narration_pending": "Озвучка готовится. Публикация статьи не блокируется.",
        "no_articles": "Опубликованных статей пока нет. Загляните позже.",
        "related_empty": "Похожие статьи появятся здесь по мере роста редакции.",
        "footer_tagline": "Премиальная AI-аналитика новостей",
        "about": "About",
        "contact": "Contact",
        "site_name": "Name",
        "domain_owner": "Domain owner",
        "mobile_whatsapp": "Mobile and WhatsApp",
        "youtube": "YouTube",
        "tiktok": "TikTok",
        "founder_ceo": "VREYC founder and chief executive is Vasif Jabrayilli.",
        "email": "Эл. почта",
        "more_categories": "Больше категорий",
    },
    "tr": {
        "latest": "Son",
        "latest_news": "Son haberler",
        "most_watched": "En çok izlenenler",
        "related": "İlgili haberler",
        "more_stories": "Daha fazla haber",
        "search": "Ara",
        "search_placeholder": "Ara",
        "news": "Haber",
        "top_story": "Manşet",
        "featured": "Öne çıkan",
        "editor_picks": "Editörün AI seçimleri",
        "trending": "Trend",
        "audio_narration": "Sesli anlatım",
        "share": "Paylaş",
        "play": "Oynat",
        "pause": "Duraklat",
        "download": "İndir",
        "narration_pending": "Sesli anlatım hazırlanıyor. Makale yayını engellenmez.",
        "no_articles": "Henüz yayımlanmış makale yok. Lütfen yakında tekrar kontrol edin.",
        "related_empty": "Editoryal içerik büyüdükçe ilgili haberler burada görünecek.",
        "footer_tagline": "Premium AI haber istihbaratı",
        "about": "About",
        "contact": "Contact",
        "site_name": "Name",
        "domain_owner": "Domain owner",
        "mobile_whatsapp": "Mobile and WhatsApp",
        "youtube": "YouTube",
        "tiktok": "TikTok",
        "founder_ceo": "VREYC founder and chief executive is Vasif Jabrayilli.",
        "email": "E-posta",
        "more_categories": "Daha fazla kategori",
    },
    "zh": {
        "latest": "最新",
        "latest_news": "最新新闻",
        "most_watched": "最多观看",
        "related": "相关新闻",
        "more_stories": "更多报道",
        "search": "搜索",
        "search_placeholder": "搜索",
        "news": "新闻",
        "top_story": "头条",
        "featured": "精选",
        "editor_picks": "AI 编辑精选",
        "trending": "热门",
        "audio_narration": "音频播报",
        "share": "分享",
        "play": "播放",
        "pause": "暂停",
        "download": "下载",
        "narration_pending": "音频播报正在准备中。文章发布不会受阻。",
        "no_articles": "暂无已发布文章。请稍后再查看。",
        "related_empty": "随着 newsroom 内容增长，相关新闻将显示在这里。",
        "footer_tagline": "高端 AI 新闻情报",
        "about": "About",
        "contact": "Contact",
        "site_name": "Name",
        "domain_owner": "Domain owner",
        "mobile_whatsapp": "Mobile and WhatsApp",
        "youtube": "YouTube",
        "tiktok": "TikTok",
        "founder_ceo": "VREYC founder and chief executive is Vasif Jabrayilli.",
        "email": "电子邮件",
        "more_categories": "更多分类",
    },
    "es": {
        "latest": "Último",
        "latest_news": "Últimas noticias",
        "most_watched": "Más vistas",
        "related": "Relacionadas",
        "more_stories": "Más historias",
        "search": "Buscar",
        "search_placeholder": "Buscar",
        "news": "Noticia",
        "top_story": "Noticia principal",
        "featured": "Destacadas",
        "editor_picks": "Selección AI del editor",
        "trending": "Tendencias",
        "audio_narration": "Narración de audio",
        "share": "Compartir",
        "play": "Reproducir",
        "pause": "Pausa",
        "download": "Descargar",
        "narration_pending": "La narración se está preparando. La publicación del artículo no se bloquea.",
        "no_articles": "Aún no hay artículos publicados. Vuelve pronto.",
        "related_empty": "Los artículos relacionados aparecerán aquí a medida que crezca la redacción.",
        "footer_tagline": "Inteligencia premium de noticias con AI",
        "about": "About",
        "contact": "Contact",
        "site_name": "Name",
        "domain_owner": "Domain owner",
        "mobile_whatsapp": "Mobile and WhatsApp",
        "youtube": "YouTube",
        "tiktok": "TikTok",
        "founder_ceo": "VREYC founder and chief executive is Vasif Jabrayilli.",
        "email": "Correo",
        "more_categories": "Más categorías",
    },
}

CATEGORY_LABELS = {
    "az": {"Politics": "Siyasət", "World": "Dünya", "Economy": "İqtisadiyyat", "Technology": "Texnologiya", "Business": "Biznes", "Sports": "İdman", "Health": "Sağlamlıq", "Country": "Ölkə", "Incident": "Hadisə", "Science and Education": "Elm və Təhsil", "Show Business": "Şou Biznes", "Agriculture": "Kənd təsərrüfatı"},
    "en": {"Politics": "Politics", "World": "World", "Economy": "Economy", "Technology": "Technology", "Business": "Business", "Sports": "Sports", "Health": "Health", "Country": "Country", "Incident": "Incident", "Science and Education": "Science & Education", "Show Business": "Show Business", "Agriculture": "Agriculture"},
    "ru": {"Politics": "Политика", "World": "Мир", "Economy": "Экономика", "Technology": "Технологии", "Business": "Бизнес", "Sports": "Спорт", "Health": "Здоровье", "Country": "Страна", "Incident": "Происшествия", "Science and Education": "Наука и образование", "Show Business": "Шоу-бизнес", "Agriculture": "Сельское хозяйство"},
    "tr": {"Politics": "Siyaset", "World": "Dünya", "Economy": "Ekonomi", "Technology": "Teknoloji", "Business": "İş dünyası", "Sports": "Spor", "Health": "Sağlık", "Country": "Ülke", "Incident": "Olay", "Science and Education": "Bilim ve Eğitim", "Show Business": "Şov Biznes", "Agriculture": "Tarım"},
    "zh": {"Politics": "政治", "World": "世界", "Economy": "经济", "Technology": "科技", "Business": "商业", "Sports": "体育", "Health": "健康", "Country": "国内", "Incident": "事件", "Science and Education": "科学与教育", "Show Business": "娱乐圈", "Agriculture": "农业"},
    "es": {"Politics": "Política", "World": "Mundo", "Economy": "Economía", "Technology": "Tecnología", "Business": "Negocios", "Sports": "Deportes", "Health": "Salud", "Country": "País", "Incident": "Sucesos", "Science and Education": "Ciencia y educación", "Show Business": "Espectáculos", "Agriculture": "Agricultura"},
}


def public_labels(language: str) -> dict[str, str]:
    return PUBLIC_LABELS.get(language, PUBLIC_LABELS["az"])


def public_category_labels(language: str) -> dict[str, str]:
    return CATEGORY_LABELS.get(language, CATEGORY_LABELS["az"])

PRIMARY_CATEGORY_NAMES = ["Politics", "World", "Economy", "Technology", "Business", "Sports", "Health"]
SECONDARY_CATEGORY_NAMES = ["Country", "Incident", "Science and Education", "Show Business"]

DEFAULT_CATEGORIES = [
    {"name": "Politics", "description": "Policy, elections, diplomacy and public leadership.", "color": "#e11d48"},
    {"name": "World", "description": "Global affairs, conflicts, climate and society.", "color": "#2563eb"},
    {"name": "Economy", "description": "Markets, macroeconomics, labor and public finance.", "color": "#16a34a"},
    {"name": "Technology", "description": "AI, platforms, cybersecurity, science and innovation.", "color": "#7c3aed"},
    {"name": "Business", "description": "Companies, startups, leadership and industry strategy.", "color": "#f97316"},
    {"name": "Sports", "description": "Scores, tournaments, athletes and sports business.", "color": "#06b6d4"},
    {"name": "Health", "description": "Medicine, wellbeing, research and public health.", "color": "#db2777"},
    {"name": "Country", "description": "Local and national news from Azerbaijan and the region.", "color": "#0ea5e9"},
    {"name": "Incident", "description": "Breaking incidents, public safety and developing events.", "color": "#ef4444"},
    {"name": "Science and Education", "description": "Science, schools, universities and education policy.", "color": "#14b8a6"},
    {"name": "Show Business", "description": "Entertainment, celebrities, culture and show business.", "color": "#d946ef"},
]


def slugify(text: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return base or "article"


def format_published_at(value):
    return value.strftime("%b %d, %Y") if value else ""


def is_uploaded_file(value) -> bool:
    return bool(getattr(value, "filename", None)) and hasattr(value, "file")


def public_image_url(path: str | None) -> str:
    if not path:
        return ""
    value = path.strip()
    upload_dir = str(UPLOAD_DIR)
    legacy_upload_dirs = tuple(str(path) for path in LEGACY_UPLOAD_DIRS)
    if value == upload_dir or value.startswith(f"{upload_dir}/"):
        return f"{UPLOAD_URL_PREFIX}/{Path(value).name}"
    if any(value == legacy_dir or value.startswith(f"{legacy_dir}/") for legacy_dir in legacy_upload_dirs):
        return f"{UPLOAD_URL_PREFIX}/{Path(value).name}"
    if value.startswith(("http://", "https://")):
        return value
    if value.startswith(f"{UPLOAD_URL_PREFIX}/"):
        return value
    if value.startswith("/"):
        return value
    if value.startswith(("static/", "assets/")):
        return f"/{value}"
    return value


def local_uploaded_image_path(path: str | None) -> Path | None:
    public_path = public_image_url(path)
    if not public_path.startswith(f"{UPLOAD_URL_PREFIX}/"):
        return None
    return UPLOAD_DIR / Path(public_path).name


def uploaded_image_exists(path: str | None) -> bool:
    public_path = public_image_url(path)
    if not public_path:
        return False
    if public_path.startswith(("http://", "https://")):
        return True
    if public_path.startswith(f"{UPLOAD_URL_PREFIX}/"):
        local_path = local_uploaded_image_path(public_path)
        return bool(local_path and local_path.is_file())
    if public_path.startswith("/static/"):
        local_path = Path(public_path.lstrip("/"))
        return local_path.is_file()
    if public_path.startswith("/assets/"):
        local_path = Path(public_path.lstrip("/"))
        return local_path.is_file()
    return True


def image_srcset(path: str | None) -> str:
    if not uploaded_image_exists(path):
        return ""
    source = local_uploaded_image_path(path)
    if not source:
        return ""
    parts = []
    for width in IMAGE_VARIANT_WIDTHS:
        variant = source.with_name(f"{source.stem}-{width}.webp")
        if variant.exists():
            parts.append(f"{UPLOAD_URL_PREFIX}/{variant.name} {width}w")
    return ", ".join(parts)


def preserve_legacy_uploads() -> None:
    """Copy any images found in old local upload locations into the persistent upload mount."""
    resolved_upload_dir = UPLOAD_DIR.resolve()
    for legacy_dir in LEGACY_UPLOAD_DIRS:
        if not legacy_dir.exists() or not legacy_dir.is_dir():
            continue
        try:
            if legacy_dir.resolve() == resolved_upload_dir:
                continue
        except OSError:
            continue
        for source in legacy_dir.iterdir():
            if not source.is_file():
                continue
            if source.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            target = UPLOAD_DIR / source.name
            if not target.exists():
                shutil.copy2(source, target)


def save_image_upload(file, alt_text: str = "") -> MediaAsset | None:
    if not is_uploaded_file(file):
        return None
    content_type = file.content_type or ""
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Only JPG, PNG, WEBP and GIF images can be uploaded.")
    ensure_upload_dir()
    original_name = Path(file.filename or "image").name
    suffix = Path(original_name).suffix.lower() or ".jpg"
    safe_root = uuid4().hex
    target = UPLOAD_DIR / f"{safe_root}{suffix}"
    with target.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    try:
        with Image.open(target) as img:
            img.verify()
        with Image.open(target) as img:
            image = img.convert("RGB") if img.mode not in {"RGB", "RGBA"} else img.copy()
            for width in IMAGE_VARIANT_WIDTHS:
                if img.width <= width:
                    continue
                ratio = width / img.width
                height = max(1, round(img.height * ratio))
                variant = image.copy()
                variant.thumbnail((width, height), Image.Resampling.LANCZOS)
                variant.save(UPLOAD_DIR / f"{safe_root}-{width}.webp", "WEBP", quality=82, method=6)
    except (UnidentifiedImageError, OSError):
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid image.")
    stat = target.stat()
    return MediaAsset(
        filename=original_name,
        path=f"{UPLOAD_URL_PREFIX}/{target.name}",
        content_type=content_type,
        size_bytes=stat.st_size,
        alt_text=alt_text,
    )


templates.env.filters["format_published_at"] = format_published_at
templates.env.filters["image_srcset"] = image_srcset
templates.env.filters["public_image_url"] = public_image_url
templates.env.filters["uploaded_image_exists"] = uploaded_image_exists


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_auth(request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=401)


def canonical_url(request: Request, path: str = "") -> str:
    return f"{settings.site_url.rstrip('/')}/{path.lstrip('/')}"


def article_url(language: str, slug: str) -> str:
    return f"/{language}/article/{slug}"


def get_translation(article: Article, language: str):
    """Return the stored translation row for a public language, if one exists.

    Azerbaijani content is stored directly on the Article row. EN/RU/TR/ZH/ES
    content is stored in ArticleTranslation rows created by the admin form or
    translation generator.
    """
    normalized_language = (language or "az").lower()
    if normalized_language == "az":
        return article
    for translation in getattr(article, "translations", []) or []:
        if (translation.language or "").lower() == normalized_language:
            return translation
    return None


def localized_value(article: Article, translation: ArticleTranslation | None, field: str):
    """Use translated article content when present, otherwise fall back to AZ."""
    value = getattr(translation, field, None) if translation else None
    if isinstance(value, str):
        value = value.strip()
    if value not in (None, ""):
        return value
    return getattr(article, field, None)


def localized_slug(article: Article, language: str) -> str:
    translation = get_translation(article, language) if language != "az" else None
    return localized_value(article, translation, "slug") or article.slug or str(article.id)


def localized_article_view(article: Article, language: str):
    translation = get_translation(article, language) if language != "az" else None
    return SimpleNamespace(
        id=article.id,
        title=localized_value(article, translation, "title"),
        slug=localized_slug(article, language),
        summary=localized_value(article, translation, "summary"),
        content=localized_value(article, translation, "content"),
        seo_title=localized_value(article, translation, "seo_title"),
        meta_description=localized_value(article, translation, "meta_description"),
        tags=localized_value(article, translation, "tags"),
        category=article.category,
        category_label=public_category_labels(language).get(article.category, article.category) if article.category else public_labels(language)["news"],
        language=language,
        source_language="az",
        has_translation=bool(translation),
        translation=translation,
    )


def unique_article_slug(db, requested_slug: str, current_id: int | None = None) -> str:
    root = slugify(requested_slug)
    candidate = root
    suffix = 2
    while True:
        query = db.query(Article).filter(Article.slug == candidate)
        if current_id:
            query = query.filter(Article.id != current_id)
        if not query.first():
            return candidate
        candidate = f"{root}-{suffix}"
        suffix += 1


def get_or_create_translation(db, article: Article, language: str) -> ArticleTranslation:
    row = db.query(ArticleTranslation).filter(ArticleTranslation.article_id == article.id, ArticleTranslation.language == language).first()
    if not row:
        row = ArticleTranslation(article_id=article.id, language=language)
        db.add(row)
    return row


def ensure_slugs(db):
    used = set()
    for a in db.query(Article).all():
        candidate = getattr(a, "slug", None) or slugify(a.title)
        original = candidate
        n = 2
        while candidate in used:
            candidate = f"{original}-{n}"
            n += 1
        used.add(candidate)
        if getattr(a, "slug", None) != candidate:
            a.slug = candidate
    db.commit()



def ensure_categories(db):
    existing = {c.name.lower(): c for c in db.query(Category).all()}
    for item in DEFAULT_CATEGORIES:
        if item["name"].lower() not in existing:
            db.add(Category(name=item["name"], slug=slugify(item["name"]), description=item["description"], color=item["color"]))
    db.commit()


def category_navigation(db):
    rows = db.query(Category).order_by(Category.name.asc()).all()
    by_name = {c.name: c for c in rows}
    ordered = []
    for item in DEFAULT_CATEGORIES:
        ordered.append(by_name.get(item["name"]) or Category(name=item["name"], slug=slugify(item["name"]), description=item["description"], color=item["color"]))
    extras = [c for c in rows if c.name not in {item["name"] for item in DEFAULT_CATEGORIES}]
    return ordered + extras


def public_category_navigation(db) -> dict[str, list[Category]]:
    categories = category_navigation(db)
    by_name = {c.name: c for c in categories}
    primary = [by_name[name] for name in PRIMARY_CATEGORY_NAMES if name in by_name]
    primary_names = {c.name for c in primary}
    secondary = [by_name[name] for name in SECONDARY_CATEGORY_NAMES if name in by_name and name not in primary_names]
    secondary_names = {c.name for c in secondary}
    secondary.extend(c for c in categories if c.name not in primary_names and c.name not in secondary_names)
    return {
        "primary": primary,
        "secondary": secondary,
    }


def article_card(article: Article, language: str, category_labels: dict[str, str] | None = None) -> dict:
    view = localized_article_view(article, language)
    labels = category_labels or public_category_labels(language)
    category_label = labels.get(article.category, article.category) if article.category else public_labels(language)["news"]
    return {
        "article": article,
        "view": view,
        "t": view.translation,
        "title": view.title,
        "summary": view.summary,
        "url": article_url(language, view.slug),
        "category_label": category_label,
        "image_exists": uploaded_image_exists(article.image_url),
    }

def get_settings_map(db) -> dict[str, str]:
    return {row.key: row.value for row in db.query(Setting).all()}


def save_setting(db, key: str, value: str) -> None:
    row = db.query(Setting).filter(Setting.key == key).first()
    if not row:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value


def article_form_context(db, article: Article | None = None) -> dict:
    categories = db.query(Category).order_by(Category.name.asc()).all()
    if not categories:
        names = [c[0] for c in db.query(Article.category).filter(Article.category.isnot(None)).distinct().all() if c[0]]
        categories = [Category(name=name, slug=slugify(name), description="") for name in names]
    translations = {lang: get_translation(article, lang) for lang in SUPPORTED_LANGUAGES} if article else {lang: None for lang in SUPPORTED_LANGUAGES}
    return {"categories": categories, "languages": SUPPORTED_LANGUAGES, "language_labels": LANGUAGE_LABELS, "translations": translations}



def validate_image_references(db) -> list[str]:
    """Return missing local image paths without mutating records or deleting uploads."""
    missing: list[str] = []
    rows = list(db.query(Article).filter(Article.image_url.isnot(None), Article.image_url != "").all())
    rows.extend(db.query(MediaAsset).filter(MediaAsset.path.isnot(None), MediaAsset.path != "").all())
    for row in rows:
        path = getattr(row, "image_url", None) or getattr(row, "path", None)
        public_path = public_image_url(path)
        if public_path.startswith(f"{UPLOAD_URL_PREFIX}/") and not uploaded_image_exists(public_path):
            missing.append(public_path)
    return sorted(set(missing))

def apply_schema_migrations(db) -> None:
    for statement in [
        "ALTER TABLE articles ADD COLUMN slug VARCHAR(500)",
        "ALTER TABLE articles ADD COLUMN narration_enabled BOOLEAN DEFAULT true",
        "ALTER TABLE articles ADD COLUMN meta_description TEXT",
        "ALTER TABLE articles ADD COLUMN is_featured BOOLEAN DEFAULT false",
        "ALTER TABLE articles ADD COLUMN is_trending BOOLEAN DEFAULT false",
        "ALTER TABLE articles ADD COLUMN homepage_order INTEGER DEFAULT 100",
        "ALTER TABLE article_translations ADD COLUMN slug VARCHAR(500)",
        "ALTER TABLE article_translations ADD COLUMN meta_description TEXT",
    ]:
        try:
            db.execute(text(statement))
            db.commit()
        except Exception:
            db.rollback()


@app.on_event("startup")
def startup() -> None:
    settings.validate_production_or_raise()
    init_db()
    ensure_upload_dir()
    preserve_legacy_uploads()
    db = SessionLocal()
    apply_schema_migrations(db)
    ensure_categories(db)
    ensure_slugs(db)
    missing_images = validate_image_references(db)
    if missing_images:
        print(f"WARNING: {len(missing_images)} uploaded image reference(s) are missing from {UPLOAD_DIR}; VREYC placeholders will be shown: {missing_images}")
    db.close()
    scheduler.add_job(run_fetch_pipeline, "interval", minutes=max(13, min(17, settings.fetch_interval_min)), id="fetch_job", replace_existing=True)
    scheduler.add_job(generate_pending_narrations, "interval", seconds=45, id="narration_job", replace_existing=True)
    scheduler.start()


@app.get("/", response_class=HTMLResponse)
@app.get("/{language}/", response_class=HTMLResponse)
def home(request: Request, language: str = "az", q: str = "", category: str = "", db=Depends(get_db)):
    language = language if language in SUPPORTED_LANGUAGES else "az"
    ensure_categories(db)
    query = db.query(Article).options(selectinload(Article.translations)).filter(Article.status == "published")
    if q:
        translation_matches = db.query(ArticleTranslation.article_id).filter(
            ArticleTranslation.language == language,
            (ArticleTranslation.title.ilike(f"%{q}%")) | (ArticleTranslation.summary.ilike(f"%{q}%")),
        )
        query = query.filter((Article.title.ilike(f"%{q}%")) | (Article.summary.ilike(f"%{q}%")) | (Article.id.in_(translation_matches.scalar_subquery())))
    if category:
        query = query.filter(Article.category == category)
    articles = query.order_by(Article.homepage_order.asc(), Article.published_at.desc(), Article.created_at.desc()).limit(30).all()
    featured = db.query(Article).options(selectinload(Article.translations)).filter(Article.status == "published", Article.is_featured == True).order_by(Article.homepage_order.asc(), Article.published_at.desc()).limit(6).all()
    if not featured:
        featured = articles[:6]
    trending = db.query(Article).options(selectinload(Article.translations)).filter(Article.status == "published", Article.is_trending == True).order_by(Article.homepage_order.asc(), Article.published_at.desc()).limit(8).all()
    if not trending:
        trending = articles[:8]
    category_labels = public_category_labels(language)
    article_cards = [article_card(a, language, category_labels) for a in articles]
    featured_cards = [article_card(a, language, category_labels) for a in featured]
    trending_cards = [article_card(a, language, category_labels) for a in trending]
    hero = featured_cards[0] if featured_cards else (article_cards[0] if article_cards else None)
    latest_cards = [row for row in article_cards if not hero or row["article"].id != hero["article"].id]
    categories = public_category_navigation(db)
    alt_links = {lang: f"/{lang}/" for lang in SUPPORTED_LANGUAGES}
    return templates.TemplateResponse("public/home.html", {"request": request, "articles": article_cards, "latest_articles": latest_cards, "featured_articles": featured_cards, "trending_articles": trending_cards, "hero": hero, "categories": categories["primary"], "secondary_categories": categories["secondary"], "q": q, "category": category, "site_url": settings.site_url, "canonical": canonical_url(request, f'{language}/'), "language": language, "languages": SUPPORTED_LANGUAGES, "alt_links": alt_links, "ui": public_labels(language), "category_labels": category_labels})


@app.get("/article/{slug}", response_class=HTMLResponse)
@app.get("/{language}/article/{slug}", response_class=HTMLResponse)
def article_by_slug(slug: str, request: Request, language: str = "az", db=Depends(get_db)):
    language = language if language in SUPPORTED_LANGUAGES else "az"
    slug_filters = [Article.slug == slug]
    if slug.isdigit():
        slug_filters.append(Article.id == int(slug))
    article = db.query(Article).options(selectinload(Article.translations)).filter(or_(*slug_filters), Article.status == "published").first()
    if not article and language != "az":
        tr = db.query(ArticleTranslation).filter(ArticleTranslation.slug == slug, ArticleTranslation.language == language).first()
        article = db.query(Article).options(selectinload(Article.translations)).filter(Article.id == tr.article_id).first() if tr else None
    if not article:
        raise HTTPException(404)
    view = localized_article_view(article, language)
    narration = db.query(ArticleNarration).filter(ArticleNarration.article_id == article.id, ArticleNarration.language == language).first()
    alt_links = {lang: article_url(lang, localized_slug(article, lang)) for lang in SUPPORTED_LANGUAGES}
    related = db.query(Article).options(selectinload(Article.translations)).filter(Article.status == "published", Article.id != article.id, Article.category == article.category).order_by(Article.published_at.desc(), Article.created_at.desc()).limit(3).all()
    if len(related) < 3:
        related = related + db.query(Article).options(selectinload(Article.translations)).filter(Article.status == "published", Article.id != article.id, Article.category != article.category).order_by(Article.published_at.desc(), Article.created_at.desc()).limit(3 - len(related)).all()
    canonical = canonical_url(request, f"{language}/article/{view.slug}")
    navigation = public_category_navigation(db)
    category_labels = public_category_labels(language)
    return templates.TemplateResponse("public/article.html", {"request": request, "article": view, "root_article": article, "image_exists": uploaded_image_exists(article.image_url), "narration": narration, "related_articles": [article_card(a, language, category_labels) for a in related], "categories": navigation["primary"], "secondary_categories": navigation["secondary"], "share_url": canonical, "site_url": settings.site_url, "canonical": canonical, "language": language, "languages": SUPPORTED_LANGUAGES, "alt_links": alt_links, "ui": public_labels(language), "category_labels": category_labels})


@app.get('/search', response_class=HTMLResponse)
def search(request: Request, q: str = "", db=Depends(get_db)):
    return home(request, q=q, db=db)


@app.get('/category/{category}', response_class=HTMLResponse)
def category_page(category: str, request: Request, db=Depends(get_db)):
    return home(request, category=category, db=db)


@app.get('/sitemap.xml')
def sitemap(db=Depends(get_db)):
    base_url = settings.site_url.rstrip("/")
    urls = [f"<url><loc>{base_url}/</loc></url>"]
    urls.extend(f"<url><loc>{base_url}/{lang}/</loc></url>" for lang in SUPPORTED_LANGUAGES)
    for a in db.query(Article).filter(Article.status == 'published').all():
        urls.append(f"<url><loc>{base_url}/az/article/{a.slug or a.id}</loc></url>")
        for lang in SUPPORTED_LANGUAGES:
            if lang == "az":
                continue
            urls.append(f"<url><loc>{base_url}/{lang}/article/{localized_slug(a, lang)}</loc></url>")
    return Response(content=f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{"".join(urls)}</urlset>', media_type='application/xml')


@app.get('/robots.txt')
def robots():
    return Response(content=f"User-agent: *\nAllow: /\nDisallow: /admin\nSitemap: {settings.site_url.rstrip('/')}/sitemap.xml\n", media_type='text/plain')


@app.exception_handler(401)
def unauthorized(request: Request, exc):
    if request.url.path.startswith('/admin'):
        return RedirectResponse('/admin/login', status_code=302)
    return Response(status_code=401)


@app.get('/admin/login', response_class=HTMLResponse)
def login_page(request: Request):
    if is_authenticated(request):
        return RedirectResponse('/admin', status_code=302)
    return templates.TemplateResponse('admin/login.html', {'request': request})


@app.post('/admin/login')
@limiter.limit('5/minute')
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == settings.admin_username and settings.admin_password_hash and verify_password(password, settings.admin_password_hash):
        set_session(request, username)
        return RedirectResponse('/admin', status_code=302)
    return templates.TemplateResponse('admin/login.html', {'request': request, 'error': 'Invalid credentials'}, status_code=401)


@app.post('/admin/logout')
def logout(request: Request):
    clear_session(request)
    return RedirectResponse('/admin/login', status_code=302)


@app.get('/admin', response_class=HTMLResponse)
def admin_dashboard(request: Request, db=Depends(get_db), _=Depends(require_auth)):
    drafts = db.query(Article).filter(Article.status == 'draft').count()
    published = db.query(Article).filter(Article.status == 'published').count()
    total_articles = db.query(Article).count()
    categories = db.query(Category).count() or db.query(Article.category).filter(Article.category.isnot(None)).distinct().count()
    media_count = db.query(MediaAsset).count()
    logs = db.query(FetchLog).order_by(FetchLog.created_at.desc()).limit(8).all()
    recent_articles = db.query(Article).order_by(Article.updated_at.desc(), Article.created_at.desc()).limit(6).all()
    return templates.TemplateResponse('admin/dashboard.html', {'request': request, 'drafts': drafts, 'published': published, 'total_articles': total_articles, 'categories': categories, 'media_count': media_count, 'logs': logs, 'recent_articles': recent_articles, "languages": SUPPORTED_LANGUAGES})


@app.get('/admin/articles', response_class=HTMLResponse)
def admin_articles(request: Request, status: str = "all", db=Depends(get_db), _=Depends(require_auth)):
    query = db.query(Article)
    if status in {"draft", "published"}:
        query = query.filter(Article.status == status)
    articles = query.order_by(Article.updated_at.desc(), Article.created_at.desc()).all()
    narration_map = {n.article_id: n for n in db.query(ArticleNarration).filter(ArticleNarration.article_id.in_([a.id for a in articles] or [0])).all()}
    return templates.TemplateResponse("admin/articles.html", {"request": request, "articles": articles, "status": status, "narration_map": narration_map, "languages": SUPPORTED_LANGUAGES})


@app.get('/admin/articles/new', response_class=HTMLResponse)
def new_article_page(request: Request, db=Depends(get_db), _=Depends(require_auth)):
    context = article_form_context(db)
    context.update({'request': request, 'article': None, 'mode': 'new', 'narration': None})
    return templates.TemplateResponse('admin/edit.html', context)


@app.post('/admin/articles/new')
async def create_article(request: Request, db=Depends(get_db), _=Depends(require_auth)):
    form = await request.form()
    uploaded_image = save_image_upload(form.get('hero_image'), form.get('hero_alt_text', ''))
    if uploaded_image:
        db.add(uploaded_image)
        db.flush()
    title = form.get('title_az') or form.get('title') or 'Untitled article'
    article = Article(
        title=title,
        slug=unique_article_slug(db, form.get('slug_az') or title),
        summary=form.get('summary_az', ''),
        content=form.get('content_az', ''),
        seo_title=form.get('seo_title_az', ''),
        meta_description=form.get('meta_description_az', ''),
        tags=form.get('tags_az', ''),
        image_url=uploaded_image.path if uploaded_image else form.get('image_url', ''),
        category=form.get('category', ''),
        status=form.get('status', 'draft'),
        language='az',
        narration_enabled=form.get('narration_enabled') == 'on',
        is_featured=form.get('is_featured') == 'on',
        is_trending=form.get('is_trending') == 'on',
        homepage_order=int(form.get('homepage_order') or 100),
        published_at=datetime.utcnow() if form.get('status') == 'published' else None,
    )
    db.add(article)
    db.flush()
    for lang in SUPPORTED_LANGUAGES:
        if lang == 'az':
            continue
        if any(form.get(f'{field}_{lang}', '') for field in ['title', 'summary', 'content', 'seo_title', 'meta_description', 'tags', 'slug']):
            row = ArticleTranslation(article_id=article.id, language=lang)
            row.title = form.get(f'title_{lang}', '')
            row.slug = slugify(form.get(f'slug_{lang}') or row.title or f'{article.slug}-{lang}')
            row.summary = form.get(f'summary_{lang}', '')
            row.content = form.get(f'content_{lang}', '')
            row.seo_title = form.get(f'seo_title_{lang}', '')
            row.meta_description = form.get(f'meta_description_{lang}', '')
            row.tags = form.get(f'tags_{lang}', '')
            db.add(row)
    db.commit()
    return RedirectResponse('/admin/articles', status_code=302)


@app.post('/admin/articles/{article_id}/publish')
def publish_article(article_id: int, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    a = db.query(Article).get(article_id)
    if a:
        a.status = 'published'
        a.published_at = a.published_at or datetime.utcnow()
        a.slug = a.slug or unique_article_slug(db, a.title, a.id)
        a.updated_at = datetime.utcnow()
        db.commit()
        queue_narration(db, a)
        db.commit()
    return RedirectResponse('/admin/articles?status=published', status_code=302)


@app.post('/admin/articles/{article_id}/unpublish')
def unpublish_article(article_id: int, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    a = db.query(Article).get(article_id)
    if a:
        a.status = 'draft'
        a.updated_at = datetime.utcnow()
        db.commit()
    return RedirectResponse('/admin/articles?status=draft', status_code=302)


@app.get('/admin/articles/{article_id}/edit', response_class=HTMLResponse)
def edit_page(article_id: int, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    article = db.query(Article).get(article_id)
    if not article:
        raise HTTPException(404)
    narration = db.query(ArticleNarration).filter(ArticleNarration.article_id == article_id, ArticleNarration.language == article.language).first()
    context = article_form_context(db, article)
    context.update({'request': request, 'article': article, 'mode': 'edit', 'narration': narration})
    return templates.TemplateResponse('admin/edit.html', context)


@app.post('/admin/articles/{article_id}/edit')
async def edit_article(article_id: int, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    form = await request.form()
    a = db.query(Article).get(article_id)
    if not a:
        return RedirectResponse('/admin/articles', status_code=302)
    uploaded_image = save_image_upload(form.get('hero_image'), form.get('hero_alt_text', ''))
    if uploaded_image:
        db.add(uploaded_image)
        db.flush()
    db.add(ArticleRevision(article_id=a.id, title=a.title, content=a.content, image_url=a.image_url, category=a.category, seo_title=a.seo_title, tags=a.tags))
    a.title = form.get('title_az') or form.get('title') or a.title
    requested_az_slug = form.get('slug_az')
    if requested_az_slug and requested_az_slug != a.slug:
        a.slug = unique_article_slug(db, requested_az_slug, a.id)
    elif not a.slug:
        a.slug = unique_article_slug(db, a.title, a.id)
    a.summary = form.get('summary_az', '')
    a.content = form.get('content_az', '')
    a.seo_title = form.get('seo_title_az', '')
    a.meta_description = form.get('meta_description_az', '')
    a.tags = form.get('tags_az', '')
    a.image_url = uploaded_image.path if uploaded_image else form.get('image_url', '')
    a.category = form.get('category', '')
    old_status = a.status
    a.status = form.get('status', 'draft')
    a.narration_enabled = form.get('narration_enabled') == 'on'
    a.is_featured = form.get('is_featured') == 'on'
    a.is_trending = form.get('is_trending') == 'on'
    a.homepage_order = int(form.get('homepage_order') or 100)
    a.updated_at = datetime.utcnow()
    if a.status == 'published' and (old_status != 'published' or not a.published_at):
        a.published_at = datetime.utcnow()
    for lang in SUPPORTED_LANGUAGES:
        if lang == 'az':
            continue
        has_content = any(form.get(f'{field}_{lang}', '') for field in ['title', 'summary', 'content', 'seo_title', 'meta_description', 'tags', 'slug'])
        row = db.query(ArticleTranslation).filter(ArticleTranslation.article_id == a.id, ArticleTranslation.language == lang).first()
        if not has_content:
            continue
        row = row or ArticleTranslation(article_id=a.id, language=lang)
        if row.id is None:
            db.add(row)
        row.title = form.get(f'title_{lang}', '')
        row.slug = slugify(form.get(f'slug_{lang}') or row.slug or row.title or f'{a.slug}-{lang}')
        row.summary = form.get(f'summary_{lang}', '')
        row.content = form.get(f'content_{lang}', '')
        row.seo_title = form.get(f'seo_title_{lang}', '')
        row.meta_description = form.get(f'meta_description_{lang}', '')
        row.tags = form.get(f'tags_{lang}', '')
        row.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(f'/admin/articles/{a.id}/edit?saved=1', status_code=302)


@app.post('/admin/articles/{article_id}/feature')
def toggle_featured(article_id: int, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    article = db.query(Article).get(article_id)
    if article:
        article.is_featured = not bool(article.is_featured)
        article.updated_at = datetime.utcnow()
        db.commit()
    return RedirectResponse('/admin/articles', status_code=302)


@app.post('/admin/articles/{article_id}/trending')
def toggle_trending(article_id: int, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    article = db.query(Article).get(article_id)
    if article:
        article.is_trending = not bool(article.is_trending)
        article.updated_at = datetime.utcnow()
        db.commit()
    return RedirectResponse('/admin/articles', status_code=302)


@app.post('/admin/articles/{article_id}/order')
def update_homepage_order(article_id: int, request: Request, homepage_order: int = Form(100), db=Depends(get_db), _=Depends(require_auth)):
    article = db.query(Article).get(article_id)
    if article:
        article.homepage_order = homepage_order
        article.updated_at = datetime.utcnow()
        db.commit()
    return RedirectResponse('/admin/articles', status_code=302)


@app.post('/admin/articles/{article_id}/delete')
def delete_article(article_id: int, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    article = db.query(Article).get(article_id)
    status = article.status if article else 'all'
    if article:
        db.delete(article)
        db.commit()
    return RedirectResponse(f'/admin/articles?status={status}', status_code=302)


@app.get('/admin/categories', response_class=HTMLResponse)
def categories_page(request: Request, db=Depends(get_db), _=Depends(require_auth)):
    categories = db.query(Category).order_by(Category.name.asc()).all()
    counts = {c.name: db.query(Article).filter(Article.category == c.name).count() for c in categories}
    return templates.TemplateResponse('admin/categories.html', {'request': request, 'categories': categories, 'counts': counts})


@app.post('/admin/categories')
def create_category(request: Request, name: str = Form(...), description: str = Form(''), color: str = Form('#48a6ff'), db=Depends(get_db), _=Depends(require_auth)):
    name = name.strip()
    if name and not db.query(Category).filter(Category.name == name).first():
        db.add(Category(name=name, slug=slugify(name), description=description, color=color))
        db.commit()
    return RedirectResponse('/admin/categories', status_code=302)


@app.post('/admin/categories/{category_id}/edit')
def update_category(category_id: int, request: Request, name: str = Form(...), description: str = Form(''), color: str = Form('#48a6ff'), db=Depends(get_db), _=Depends(require_auth)):
    category = db.query(Category).get(category_id)
    if category:
        old_name = category.name
        category.name = name.strip()
        category.slug = slugify(name)
        category.description = description
        category.color = color
        for article in db.query(Article).filter(Article.category == old_name).all():
            article.category = category.name
        db.commit()
    return RedirectResponse('/admin/categories', status_code=302)


@app.post('/admin/categories/{category_id}/delete')
def delete_category(category_id: int, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    category = db.query(Category).get(category_id)
    if category:
        db.delete(category)
        db.commit()
    return RedirectResponse('/admin/categories', status_code=302)


@app.get('/admin/media', response_class=HTMLResponse)
def media_page(request: Request, db=Depends(get_db), _=Depends(require_auth)):
    assets = db.query(MediaAsset).order_by(MediaAsset.created_at.desc()).all()
    return templates.TemplateResponse('admin/media.html', {'request': request, 'assets': assets})


@app.post('/admin/media')
async def upload_media(request: Request, file: UploadFile = File(...), alt_text: str = Form(''), db=Depends(get_db), _=Depends(require_auth)):
    asset = save_image_upload(file, alt_text)
    if asset:
        db.add(asset)
        db.commit()
    return RedirectResponse('/admin/media', status_code=302)


@app.post('/admin/media/{asset_id}/delete')
def delete_media(asset_id: int, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    asset = db.query(MediaAsset).get(asset_id)
    if asset:
        local_path = local_uploaded_image_path(asset.path) or Path(asset.path.lstrip('/'))
        if local_path.exists() and local_path.is_file():
            local_path.unlink()
        for width in IMAGE_VARIANT_WIDTHS:
            variant = local_path.with_name(f"{local_path.stem}-{width}.webp")
            if variant.exists() and variant.is_file():
                variant.unlink()
        db.delete(asset)
        db.commit()
    return RedirectResponse('/admin/media', status_code=302)


@app.get('/admin/settings', response_class=HTMLResponse)
def settings_page(request: Request, db=Depends(get_db), _=Depends(require_auth)):
    admin_settings = get_settings_map(db)
    return templates.TemplateResponse('admin/settings.html', {'request': request, 'settings_map': admin_settings, 'config': settings, 'languages': SUPPORTED_LANGUAGES})


@app.post('/admin/settings')
def save_settings(request: Request, site_name: str = Form('VREYC'), editor_name: str = Form('Editor'), publish_mode: str = Form('manual'), default_language: str = Form('az'), db=Depends(get_db), _=Depends(require_auth)):
    for key, value in {'site_name': site_name, 'editor_name': editor_name, 'publish_mode': publish_mode, 'default_language': default_language}.items():
        save_setting(db, key, value)
    db.commit()
    return RedirectResponse('/admin/settings?saved=1', status_code=302)


@app.get('/admin/translations', response_class=HTMLResponse)
def admin_translations(request: Request, db=Depends(get_db), _=Depends(require_auth)):
    articles = db.query(Article).filter(Article.status == 'published').order_by(Article.published_at.desc()).all()
    return templates.TemplateResponse('admin/translations.html', {'request': request, 'articles': articles, 'languages': SUPPORTED_LANGUAGES})


@app.post('/admin/translations/{article_id}/generate')
def admin_generate_translations(article_id: int, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    article = db.query(Article).get(article_id)
    if not article:
        return RedirectResponse('/admin/translations', status_code=302)
    source = {"title": article.title, "summary": article.summary, "content": article.content, "seo_title": article.seo_title, "tags": article.tags, "meta_description": article.meta_description}
    for lang in SUPPORTED_LANGUAGES:
        if lang == "az":
            continue
        payload = ai_engine.translate_article(source, lang)
        row = get_or_create_translation(db, article, lang)
        row.title = payload.get("title", article.title)
        row.summary = payload.get("summary", article.summary)
        row.content = payload.get("content", article.content)
        row.seo_title = payload.get("seo_title", row.title)
        row.meta_description = payload.get("meta_description", article.meta_description)
        row.tags = payload.get("tags", article.tags)
        if not row.slug:
            row.slug = slugify(row.title) + f"-{lang}"
        if article.status == "published" and article.narration_enabled:
            queue_narration(db, article, lang)
    db.commit()
    return RedirectResponse('/admin/translations', status_code=302)


@app.post('/admin/articles/{article_id}/narration/regenerate')
def regenerate_narration(article_id: int, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    article = db.query(Article).get(article_id)
    if article:
        queue_narration(db, article)
        db.commit()
    return RedirectResponse(f'/admin/articles/{article_id}/edit', status_code=302)


@app.post('/admin/articles/{article_id}/narration/delete')
def delete_narration(article_id: int, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    rows = db.query(ArticleNarration).filter(ArticleNarration.article_id == article_id).all()
    for row in rows:
        row.audio_path = None
        row.status = 'pending'
        row.error_message = None
    db.commit()
    return RedirectResponse(f'/admin/articles/{article_id}/edit', status_code=302)


@app.post('/admin/articles/{article_id}/narration/toggle')
def toggle_narration(article_id: int, request: Request, enabled: str = Form('true'), db=Depends(get_db), _=Depends(require_auth)):
    article = db.query(Article).get(article_id)
    if article:
        article.narration_enabled = enabled == 'true'
        db.commit()
    return RedirectResponse(f'/admin/articles/{article_id}/edit', status_code=302)


@app.post('/admin/settings/mode')
def set_mode(request: Request, mode: str = Form(...), db=Depends(get_db), _=Depends(require_auth)):
    save_setting(db, 'publish_mode', mode)
    db.commit()
    return RedirectResponse('/admin/settings', status_code=302)


@app.exception_handler(404)
def not_found(request: Request, exc):
    return templates.TemplateResponse('public/404.html', {'request': request}, status_code=404)


@app.exception_handler(500)
def server_error(request: Request, exc):
    return templates.TemplateResponse('public/500.html', {'request': request}, status_code=500)
