from datetime import UTC, datetime, timedelta
import hashlib
import logging
from email.utils import format_datetime
import html
from types import SimpleNamespace
import re
import shutil
from urllib.parse import parse_qs, urlparse
from pathlib import Path
from uuid import uuid4
from sqlalchemy import func, or_, select, text
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
from bs4 import BeautifulSoup

from config import PLACEHOLDER_VALUES, settings
from database.session import SessionLocal, init_db
from database.models import Article, ArticleRevision, ArticleView, FetchLog, Setting, ArticleNarration, ArticleTranslation, Category, MediaAsset
from cms.auth.security import is_authenticated, set_session, clear_session, verify_password
from scheduler.jobs import run_fetch_pipeline, queue_narration, generate_pending_narrations
from ai.translation_service import (
    AI_TRANSLATION_WARNING,
    ai_translation_status,
    generate_all_missing_translations,
    generate_missing_translations,
    is_ai_translation_configured,
    missing_translation_languages,
)

app = FastAPI(title=settings.app_name)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
templates = Jinja2Templates(directory="templates")
templates.env.globals["google_analytics_id"] = settings.google_analytics_id
templates.env.globals["adsense_publisher_id"] = settings.adsense_publisher_id
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
scheduler = BackgroundScheduler()
SUPPORTED_LANGUAGES = ["az", "en", "ru", "tr", "zh", "es"]
LANGUAGE_LABELS = {"az": "Azerbaijani", "en": "English", "ru": "Russian", "tr": "Turkish", "zh": "Chinese", "es": "Spanish"}
UPLOAD_DIR = Path(settings.image_upload_dir)
UPLOAD_URL_PREFIX = settings.image_upload_url_prefix
LEGACY_UPLOAD_DIRS = (Path("uploads"), Path("static/uploads/images"), Path("/app/static/uploads/images"))
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
UPLOAD_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_UPLOAD_IMAGE_BYTES = 20 * 1024 * 1024
UPLOAD_COPY_CHUNK_SIZE = 1024 * 1024
IMAGE_VARIANT_WIDTHS = (480, 960, 1440)
APP_VERSION = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
logger = logging.getLogger(__name__)


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
        "most_watched": "Xəbər lenti",
        "date_label": "Tarix",
        "views_label": "Baxış",
        "related": "Oxşar xəbərlər",
        "more_stories": "Daha çox xəbər",
        "search": "Axtar",
        "search_placeholder": "Axtar",
        "news": "Xəbər",
        "top_story": "Əsas xəbər",
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
        "most_watched": "News feed",
        "date_label": "Date",
        "views_label": "Views",
        "related": "Related",
        "more_stories": "More stories",
        "search": "Search",
        "search_placeholder": "Search",
        "news": "News",
        "top_story": "Top Story",
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
        "most_watched": "Лента новостей",
        "date_label": "Дата",
        "views_label": "Просмотры",
        "related": "Похожие новости",
        "more_stories": "Больше материалов",
        "search": "Поиск",
        "search_placeholder": "Поиск",
        "news": "Новость",
        "top_story": "Главная новость",
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
        "most_watched": "Haber akışı",
        "date_label": "Tarih",
        "views_label": "Görüntülenme",
        "related": "İlgili haberler",
        "more_stories": "Daha fazla haber",
        "search": "Ara",
        "search_placeholder": "Ara",
        "news": "Haber",
        "top_story": "Manşet",
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
        "most_watched": "新闻流",
        "date_label": "日期",
        "views_label": "浏览",
        "related": "相关新闻",
        "more_stories": "更多报道",
        "search": "搜索",
        "search_placeholder": "搜索",
        "news": "新闻",
        "top_story": "头条",
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
        "most_watched": "Feed de noticias",
        "date_label": "Fecha",
        "views_label": "Vistas",
        "related": "Relacionadas",
        "more_stories": "Más historias",
        "search": "Buscar",
        "search_placeholder": "Buscar",
        "news": "Noticia",
        "top_story": "Noticia principal",
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



ALLOWED_ARTICLE_TAGS = {
    "p", "h2", "h3", "strong", "b", "em", "i", "u", "s", "ul", "ol", "li", "blockquote",
    "a", "img", "iframe", "div", "table", "thead", "tbody", "tr", "th", "td", "br",
}
ALLOWED_ARTICLE_ATTRIBUTES = {
    "a": {"href", "title", "target", "rel"},
    "img": {"src", "alt", "title", "width", "height", "loading"},
    "iframe": {"src", "width", "height", "allow", "allowfullscreen", "frameborder"},
    "div": {"class"},
    "th": {"colspan", "rowspan", "style"},
    "td": {"colspan", "rowspan", "style"},
    "p": {"style"},
    "h2": {"style"},
    "h3": {"style"},
    "blockquote": {"style"},
}
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com"}
IFRAME_WRAPPER_CLASS = "iframe-video-embed"


def is_html_fragment(value: str) -> bool:
    return bool(re.search(r"</?[a-z][\s\S]*>", value or "", flags=re.I))


def safe_plain_text_html(value: str) -> str:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", value or "") if part.strip()]
    if not paragraphs and value and value.strip():
        paragraphs = [value.strip()]
    return "".join(f"<p>{html.escape(part).replace(chr(10), '<br>')}</p>" for part in paragraphs)


def youtube_embed_src(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value.strip())
    host = (parsed.netloc or "").lower()
    if host not in YOUTUBE_HOSTS:
        return None
    video_id = ""
    if host.endswith("youtu.be"):
        video_id = parsed.path.strip("/").split("/")[0] if parsed.path else ""
    elif parsed.path == "/watch":
        query = parse_qs(parsed.query)
        video_id = (query.get("v") or [""])[0]
    elif parsed.path.startswith(("/embed/", "/shorts/")):
        parts = parsed.path.strip("/").split("/")
        video_id = parts[1] if len(parts) > 1 else ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id or ""):
        return None
    return f"https://www.youtube.com/embed/{video_id}"


def safe_iframe_src(value: str | None) -> str | None:
    if not value:
        return None
    youtube = youtube_embed_src(value)
    if youtube:
        return youtube
    value = value.strip()
    if value.startswith("//"):
        return None
    parsed = urlparse(value)
    host = (parsed.netloc or "").lower()
    path = parsed.path or ""
    if parsed.scheme != "https" or not host:
        return None
    if host == "player.vimeo.com" and path.startswith("/video/"):
        return value
    if host in {"facebook.com", "www.facebook.com"} and path == "/plugins/video.php":
        return value
    if host == "ok.ru" and path.startswith("/videoembed/"):
        return value
    return None


def safe_url(value: str | None, *, image: bool = False) -> str | None:
    if not value:
        return None
    value = value.strip()
    if value.startswith("//"):
        return None
    if value.startswith("/"):
        return value
    if not image and value.startswith("#"):
        return value
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value
    if not image and parsed.scheme in {"mailto", "tel"}:
        return value
    return None


def sanitize_style(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"text-align\s*:\s*(left|right|center|justify)", value, flags=re.I)
    return f"text-align: {match.group(1).lower()};" if match else None


def sanitize_article_html(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if not is_html_fragment(raw):
        youtube = youtube_embed_src(raw)
        if youtube:
            raw = f'<iframe src="{youtube}" allowfullscreen></iframe>'
        else:
            raw = safe_plain_text_html(raw)
    soup = BeautifulSoup(raw, "html.parser")
    for tag in list(soup.find_all(True)):
        name = (tag.name or "").lower()
        if name in {"script", "style", "object", "embed", "form", "input", "button", "svg", "math"}:
            tag.decompose()
            continue
        if name not in ALLOWED_ARTICLE_TAGS:
            tag.unwrap()
            continue
        allowed_attrs = ALLOWED_ARTICLE_ATTRIBUTES.get(name, set())
        for attr in list(tag.attrs):
            if attr not in allowed_attrs:
                del tag.attrs[attr]
        if name == "a":
            href = safe_url(tag.get("href"))
            if href:
                tag["href"] = href
                tag["rel"] = "noopener noreferrer"
                if href.startswith(("http://", "https://")):
                    tag["target"] = "_blank"
            else:
                tag.unwrap()
                continue
        elif name == "img":
            src = safe_url(tag.get("src"), image=True)
            if src:
                tag["src"] = src
                tag["loading"] = tag.get("loading") or "lazy"
                tag["alt"] = tag.get("alt") or ""
            else:
                tag.decompose()
                continue
        elif name == "iframe":
            src = safe_iframe_src(tag.get("src"))
            if src:
                tag["src"] = src
                tag["allow"] = tag.get("allow") or "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                tag["allowfullscreen"] = ""
                tag["frameborder"] = tag.get("frameborder") or "0"
                parent = tag.parent
                if getattr(parent, "name", None) != "div" or IFRAME_WRAPPER_CLASS not in (parent.get("class") or []):
                    wrapper = soup.new_tag("div")
                    wrapper["class"] = IFRAME_WRAPPER_CLASS
                    tag.wrap(wrapper)
            else:
                tag.decompose()
                continue
        elif name == "div":
            if tag.get("class") != [IFRAME_WRAPPER_CLASS] or not tag.find("iframe", recursive=False):
                tag.unwrap()
                continue
        if tag.attrs and "style" in tag.attrs:
            style = sanitize_style(tag.get("style"))
            if style:
                tag["style"] = style
            else:
                tag.attrs.pop("style", None)
    for wrapper in list(soup.find_all("div", class_=IFRAME_WRAPPER_CLASS)):
        if not wrapper.find("iframe", recursive=False):
            wrapper.decompose()
    return str(soup)


def render_article_content(value: str | None) -> str:
    return sanitize_article_html(value)


def format_published_at(value):
    return value.strftime("%b %d, %Y") if value else ""


def format_admin_datetime(value):
    return value.strftime("%d.%m.%Y %H:%M") if value else "—"


def datetime_local_value(value):
    return value.strftime("%Y-%m-%dT%H:%M") if value else ""


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


def safe_media_filename(original_name: str) -> str:
    stem = slugify(Path(original_name or "image").stem) or "image"
    suffix = Path(original_name or "image.jpg").suffix.lower() or ".jpg"
    if suffix == ".jpe":
        suffix = ".jpg"
    return f"{stem}-{uuid4().hex[:12]}{suffix}"


def save_image_upload(file, alt_text: str = "") -> MediaAsset | None:
    if not is_uploaded_file(file):
        return None
    content_type = file.content_type or ""
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Only JPG, JPEG, PNG and WEBP images can be uploaded.")
    ensure_upload_dir()
    original_name = Path(file.filename or "image").name
    suffix = Path(original_name).suffix.lower() or ".jpg"
    if suffix not in UPLOAD_IMAGE_SUFFIXES:
        raise HTTPException(status_code=400, detail="Only JPG, JPEG, PNG and WEBP images can be uploaded.")
    target = UPLOAD_DIR / safe_media_filename(original_name)
    while target.exists():
        target = UPLOAD_DIR / safe_media_filename(original_name)
    safe_root = target.stem
    bytes_written = 0
    with target.open("wb") as buffer:
        while chunk := file.file.read(UPLOAD_COPY_CHUNK_SIZE):
            bytes_written += len(chunk)
            if bytes_written > MAX_UPLOAD_IMAGE_BYTES:
                target.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Image uploads are limited to 20 MB.")
            buffer.write(chunk)
    try:
        with Image.open(target) as img:
            img.verify()
        with Image.open(target) as img:
            image_width, image_height = img.size
            image = img.convert("RGB") if img.mode not in {"RGB", "RGBA"} else img.copy()
            for width in IMAGE_VARIANT_WIDTHS:
                if img.width <= width:
                    continue
                ratio = width / img.width
                height = max(1, round(img.height * ratio))
                variant = image.copy()
                variant.thumbnail((width, height), Image.Resampling.LANCZOS)
                variant.save(UPLOAD_DIR / f"{safe_root}-{width}.webp", "WEBP", quality=82, method=6)
    except (UnidentifiedImageError, OSError, SyntaxError):
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid image.")
    stat = target.stat()
    return MediaAsset(
        filename=original_name,
        path=f"{UPLOAD_URL_PREFIX}/{target.name}",
        url=f"{UPLOAD_URL_PREFIX}/{target.name}",
        content_type=content_type,
        mime_type=content_type,
        size_bytes=stat.st_size,
        width=image_width,
        height=image_height,
        alt_text=alt_text,
    )


def media_asset_public_path(asset: MediaAsset | None) -> str:
    if not asset:
        return ""
    return public_image_url(getattr(asset, "url", None) or getattr(asset, "path", None))


def media_asset_absolute_url(asset: MediaAsset | None) -> str:
    return public_absolute_url(media_asset_public_path(asset))


def media_usage_count(db, asset: MediaAsset) -> int:
    public_path = media_asset_public_path(asset)
    if not public_path:
        return 0
    values = {public_path, media_asset_absolute_url(asset)}
    raw_values = [getattr(asset, "path", None), getattr(asset, "url", None)]
    values.update(value for value in raw_values if value)
    values.update(public_image_url(value) for value in raw_values if value)
    return db.query(Article).filter(Article.image_url.in_(values)).count()


def media_assets_for_display(db, query, page: int, per_page: int):
    total = query.count()
    assets = query.offset((page - 1) * per_page).limit(per_page).all()
    rows = []
    for asset in assets:
        public_path = media_asset_public_path(asset)
        rows.append(SimpleNamespace(
            asset=asset,
            public_path=public_path,
            absolute_url=public_absolute_url(public_path),
            usage_count=media_usage_count(db, asset),
        ))
    return total, rows


templates.env.filters["format_published_at"] = format_published_at
templates.env.filters["format_admin_datetime"] = format_admin_datetime
templates.env.filters["datetime_local_value"] = datetime_local_value
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
    """Return the canonical language-aware public article URL."""
    return f"/{language}/{slug}"


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
        content_html=render_article_content(localized_value(article, translation, "content")),
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


def unique_translation_slug(db, language: str, requested_slug: str, current_translation_id: int | None = None) -> str:
    root = slugify(requested_slug)
    candidate = root
    suffix = 2
    while True:
        query = db.query(ArticleTranslation).filter(ArticleTranslation.language == language, ArticleTranslation.slug == candidate)
        if current_translation_id:
            query = query.filter(ArticleTranslation.id != current_translation_id)
        if not query.first():
            return candidate
        candidate = f"{root}-{suffix}"
        suffix += 1


def find_published_article_by_slug(db, slug: str, language: str = "az") -> Article | None:
    language = language if language in SUPPORTED_LANGUAGES else "az"
    article = None
    if language != "az":
        translation = db.query(ArticleTranslation).filter(ArticleTranslation.language == language, ArticleTranslation.slug == slug).first()
        if translation:
            article = db.query(Article).options(selectinload(Article.translations)).filter(Article.id == translation.article_id, public_article_visibility_filter()).first()
    if not article:
        slug_filters = [Article.slug == slug]
        if slug.isdigit():
            slug_filters.append(Article.id == int(slug))
        article = db.query(Article).options(selectinload(Article.translations)).filter(or_(*slug_filters), public_article_visibility_filter()).first()
    return article


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
        "view_count": getattr(article, "real_view_count", 0) or 0,
    }

def real_article_view_count_subquery():
    return (
        select(
            ArticleView.article_id.label("article_id"),
            func.count(ArticleView.id).label("real_view_count"),
        )
        .group_by(ArticleView.article_id)
        .subquery()
    )


def article_view_count_map(db, article_ids: list[int]) -> dict[int, int]:
    if not article_ids:
        return {}
    rows = (
        db.query(ArticleView.article_id, func.count(ArticleView.id))
        .filter(ArticleView.article_id.in_(article_ids))
        .group_by(ArticleView.article_id)
        .all()
    )
    return {int(article_id): int(count or 0) for article_id, count in rows}


def attach_real_view_counts(db, articles: list[Article]) -> list[Article]:
    counts = article_view_count_map(db, [article.id for article in articles])
    for article in articles:
        article.real_view_count = counts.get(article.id, 0)
    return articles

def get_settings_map(db) -> dict[str, str]:
    return {row.key: row.value for row in db.query(Setting).all()}


def seo_setting(settings_map: dict[str, str], key: str, default: str = "") -> str:
    return (settings_map.get(key) or default or "").strip()


def site_name_from_settings(settings_map: dict[str, str] | None = None) -> str:
    settings_map = settings_map or {}
    return seo_setting(settings_map, "site_name", settings.app_name)


def public_absolute_url(path_or_url: str | None) -> str:
    value = (path_or_url or "").strip()
    if value.startswith(("http://", "https://")):
        return value
    return f"{settings.site_url.rstrip('/')}/{value.lstrip('/')}"


def xml_escape(value) -> str:
    return html.escape(str(value or ""), quote=True)


def iso_datetime(value: datetime | None) -> str:
    return value.isoformat() + "Z" if value else ""


def parse_admin_datetime(value: str | None):
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    for fmt in ("%d.%m.%Y %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


SCHEDULED_STATUS_VALUES = ("scheduled", "Scheduled", "SCHEDULED")


def normalize_article_status(value: str | None) -> str:
    status = (value or "draft").strip().lower()
    return status if status in {"draft", "published", "scheduled"} else "draft"


def current_server_utc() -> datetime:
    """Return the current server time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def datetime_for_database(value: datetime) -> datetime:
    """Normalize datetimes for DateTime columns that may store naive UTC values."""
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def comparable_utc_datetime(value: datetime | None) -> datetime | None:
    """Normalize stored datetimes before comparing them with server UTC time."""
    if value is None:
        return None
    return datetime_for_database(value)


def publish_due_scheduled_articles(db) -> int:
    """Publish scheduled articles whose publish_at has passed using server UTC time."""
    current_time = current_server_utc()
    now = datetime_for_database(current_time)
    logger.info("Checking scheduled articles at %s", current_time.isoformat())
    candidate_articles = (
        db.query(Article)
        .filter(
            Article.status.in_(SCHEDULED_STATUS_VALUES),
            Article.publish_at.isnot(None),
        )
        .order_by(Article.publish_at.asc(), Article.id.asc())
        .all()
    )
    due_articles = [article for article in candidate_articles if comparable_utc_datetime(article.publish_at) <= now]
    logger.info("Due scheduled articles found: %s", len(due_articles))
    for article in due_articles:
        article.status = "published"
        article.published_at = article.publish_at
        article.updated_at = now
        message = f"Auto-published scheduled article id={article.id} publish_at={article.publish_at}"
        logger.info(message)
        db.add(FetchLog(level="INFO", message=message))
    if due_articles:
        touch_sitemap_refresh(db)
        db.commit()
    return len(due_articles)


def run_scheduled_publish_check() -> int:
    """Run the scheduled publishing check with its own database session."""
    db = SessionLocal()
    try:
        return publish_due_scheduled_articles(db)
    finally:
        db.close()


def public_article_visibility_filter(now: datetime | None = None):
    current = datetime_for_database(now or current_server_utc())
    return or_(
        Article.status == "published",
        (Article.status.in_(SCHEDULED_STATUS_VALUES)) & Article.publish_at.isnot(None) & (Article.publish_at <= current),
    )


def public_article_datetime_expression():
    return func.coalesce(Article.published_at, Article.publish_at, Article.created_at)


def public_article_datetime(article: Article) -> datetime | None:
    return article.published_at or article.publish_at or article.created_at


def require_scheduled_publish_at(status: str, publish_at: datetime | None) -> bool:
    return status != "scheduled" or publish_at is not None


def touch_sitemap_refresh(db) -> None:
    save_setting(db, "sitemap_last_refreshed_at", current_server_utc().isoformat())


def article_translation_complete(article: Article, language: str) -> bool:
    if language == "az":
        return True
    translation = get_translation(article, language)
    return bool(translation and (translation.title or "").strip() and (translation.content or "").strip() and (translation.slug or "").strip())


def article_missing_translation_languages(article: Article) -> list[str]:
    return [lang for lang in SUPPORTED_LANGUAGES if not article_translation_complete(article, lang)]


def article_seo_audit(article: Article, language: str = "az") -> dict:
    view = localized_article_view(article, language)
    image_exists = uploaded_image_exists(article.image_url)
    issues = []
    checks = {
        "meta_title": bool((view.seo_title or "").strip()),
        "meta_description": bool((view.meta_description or "").strip()),
        "image": image_exists,
        "schema": bool((view.title or "").strip() and article.published_at and image_exists),
        "canonical": bool((view.slug or "").strip()),
        "hreflang": all(article_translation_complete(article, lang) for lang in SUPPORTED_LANGUAGES),
        "translation": language == "az" or article_translation_complete(article, language),
        "slug": bool((view.slug or "").strip() and slugify(view.slug) == view.slug),
        "published_timestamp": bool(article.published_at),
        "updated_timestamp": bool(article.updated_at),
        "content": len((view.content or "").strip()) >= 200,
    }
    issue_labels = {
        "meta_title": "Missing meta title",
        "meta_description": "Missing meta description",
        "image": "Missing image",
        "schema": "Missing schema data",
        "canonical": "Missing canonical slug",
        "hreflang": "Missing hreflang translation",
        "translation": "Missing translation",
        "slug": "Invalid slug",
        "published_timestamp": "Missing publish timestamp",
        "updated_timestamp": "Missing update timestamp",
        "content": "Article content is short for Google News",
    }
    for key, passed in checks.items():
        if not passed:
            issues.append(issue_labels[key])
    score = round((sum(1 for passed in checks.values() if passed) / len(checks)) * 100)
    return {"score": score, "issues": issues, "checks": checks, "missing_translations": article_missing_translation_languages(article)}


def build_organization_schema(settings_map: dict[str, str]) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "Organization",
        "@id": f"{settings.site_url.rstrip('/')}/#organization",
        "name": site_name_from_settings(settings_map),
        "url": f"{settings.site_url.rstrip('/')}/",
        "logo": public_absolute_url(seo_setting(settings_map, "organization_logo_url", "/assets/og-cover.jpg")),
        "sameAs": [url for url in [seo_setting(settings_map, "youtube_url", "https://www.youtube.com/@vasifreyc"), seo_setting(settings_map, "tiktok_url", "https://www.tiktok.com/@vasifreyc")] if url],
    }


def build_website_schema(settings_map: dict[str, str], language: str) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "@id": f"{settings.site_url.rstrip('/')}/#website",
        "name": site_name_from_settings(settings_map),
        "url": f"{settings.site_url.rstrip('/')}/",
        "publisher": {"@id": f"{settings.site_url.rstrip('/')}/#organization"},
        "inLanguage": language,
        "potentialAction": {"@type": "SearchAction", "target": f"{settings.site_url.rstrip('/')}/{language}/?q={{query}}", "query-input": "required name=query"},
    }


def build_breadcrumb_schema(items: list[tuple[str, str]]) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": index, "name": name, "item": url}
            for index, (name, url) in enumerate(items, start=1)
        ],
    }


def build_news_article_schema(article: Article, view, canonical: str, image_url: str, settings_map: dict[str, str], language: str) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "@id": f"{canonical}#newsarticle",
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical},
        "headline": view.title,
        "description": view.meta_description or view.summary or view.title,
        "image": [image_url],
        "datePublished": iso_datetime(article.published_at),
        "dateModified": iso_datetime(article.updated_at or article.published_at),
        "author": {"@type": "Organization", "name": site_name_from_settings(settings_map)},
        "publisher": {"@id": f"{settings.site_url.rstrip('/')}/#organization"},
        "articleSection": view.category_label,
        "inLanguage": language,
        "isAccessibleForFree": True,
    }


def seo_verification_meta(settings_map: dict[str, str]) -> dict[str, str]:
    return {
        "google": seo_setting(settings_map, "google_search_console_verification"),
        "bing": seo_setting(settings_map, "bing_webmaster_verification"),
    }


def render_xml_response(content: str, media_type: str = "application/xml") -> Response:
    return Response(
        content=content.encode("utf-8"),
        headers={"Content-Type": f"{media_type}; charset=utf-8"},
    )


def save_setting(db, key: str, value: str) -> None:
    row = db.query(Setting).filter(Setting.key == key).first()
    if not row:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value



def safe_positive_int(value, default: int = 1, maximum: int | None = None) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    number = max(1, number)
    if maximum is not None:
        number = min(number, maximum)
    return number


def parse_admin_date(value: str | None):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None


def admin_articles_redirect(request: Request) -> str:
    query = request.url.query
    return f"/admin/articles?{query}" if query else "/admin/articles"


def admin_article_categories(db) -> list[str]:
    category_rows = [name for (name,) in db.query(Category.name).order_by(Category.name.asc()).all() if name]
    article_rows = [name for (name,) in db.query(Article.category).filter(Article.category.isnot(None), Article.category != "").distinct().order_by(Article.category.asc()).all() if name]
    return sorted(set(category_rows + article_rows))


def filtered_admin_article_query(db, search: str = "", status: str = "all", category: str = "", language: str = "", date_from: str = "", date_to: str = ""):
    query = db.query(Article).options(selectinload(Article.translations))
    if status == "scheduled":
        query = query.filter(Article.status.in_(SCHEDULED_STATUS_VALUES))
    elif status in {"draft", "published"}:
        query = query.filter(Article.status == status)
    if category:
        query = query.filter(Article.category == category)
    if language in SUPPORTED_LANGUAGES:
        if language == "az":
            query = query.filter(Article.language == "az")
        else:
            translated_ids = db.query(ArticleTranslation.article_id).filter(ArticleTranslation.language == language)
            query = query.filter(Article.id.in_(translated_ids.scalar_subquery()))
    start = parse_admin_date(date_from)
    end = parse_admin_date(date_to)
    if start:
        query = query.filter(Article.created_at >= start)
    if end:
        query = query.filter(Article.created_at < end.replace(hour=23, minute=59, second=59, microsecond=999999))
    if search:
        term = f"%{search.strip()}%"
        translation_matches = db.query(ArticleTranslation.article_id).filter(
            or_(
                ArticleTranslation.title.ilike(term),
                ArticleTranslation.slug.ilike(term),
                ArticleTranslation.content.ilike(term),
            )
        )
        query = query.filter(
            or_(
                Article.title.ilike(term),
                Article.slug.ilike(term),
                Article.content.ilike(term),
                Article.id.in_(translation_matches.scalar_subquery()),
            )
        )
    return query


def apply_admin_article_sort(query, sort: str):
    if sort == "oldest":
        return query.order_by(Article.created_at.asc(), Article.id.asc())
    if sort == "most_viewed":
        view_counts = real_article_view_count_subquery()
        return (
            query.outerjoin(view_counts, Article.id == view_counts.c.article_id)
            .order_by(
                func.coalesce(view_counts.c.real_view_count, 0).desc(),
                Article.published_at.desc(),
                Article.created_at.desc(),
                Article.id.desc(),
            )
        )
    if sort == "recently_updated":
        return query.order_by(Article.updated_at.desc(), Article.created_at.desc())
    return query.order_by(Article.published_at.desc(), Article.created_at.desc(), Article.id.desc())

def utc_start_of_day(value: datetime | None = None) -> datetime:
    current = value or datetime.utcnow()
    return current.replace(hour=0, minute=0, second=0, microsecond=0)


def compact_number(value) -> str:
    number = int(value or 0)
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if number >= 1_000:
        return f"{number / 1_000:.1f}K"
    return str(number)


def classify_traffic_source(referrer: str | None, request: Request) -> str:
    if not referrer:
        return "Direct"
    host = (urlparse(referrer).netloc or "").lower()
    current_host = request.url.hostname or urlparse(settings.site_url).netloc.lower()
    if current_host and current_host.lower() in host:
        return "Internal"
    search_hosts = ("google.", "bing.", "duckduckgo.", "yahoo.", "yandex.")
    social_hosts = ("facebook.", "fb.", "twitter.", "x.com", "linkedin.", "tiktok.", "instagram.", "threads.")
    if any(item in host for item in search_hosts):
        return "Search"
    if any(item in host for item in social_hosts):
        return "Social"
    return "Referral"


def visitor_fingerprint(request: Request) -> str:
    raw = "|".join([
        get_remote_address(request) or "unknown",
        request.headers.get("user-agent", "unknown"),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def record_article_view(db, article: Article, request: Request, language: str) -> None:
    article.updated_at = article.updated_at or datetime.utcnow()
    db.add(ArticleView(
        article_id=article.id,
        visitor_key=visitor_fingerprint(request),
        traffic_source=classify_traffic_source(request.headers.get("referer"), request),
        path=str(request.url.path),
        language=language,
    ))
    db.commit()


def analytics_summary(db) -> dict:
    today = utc_start_of_day()
    last_7_days = today - timedelta(days=6)
    last_30_days = today - timedelta(days=29)
    total_views = db.query(func.count(ArticleView.id)).scalar() or 0
    views_today = db.query(func.count(ArticleView.id)).filter(ArticleView.viewed_at >= today).scalar() or 0
    views_7 = db.query(func.count(ArticleView.id)).filter(ArticleView.viewed_at >= last_7_days).scalar() or 0
    views_30 = db.query(func.count(ArticleView.id)).filter(ArticleView.viewed_at >= last_30_days).scalar() or 0
    unique_visitors = db.query(func.count(func.distinct(ArticleView.visitor_key))).filter(ArticleView.visitor_key.isnot(None), ArticleView.visitor_key != "").scalar() or 0
    returning_rows = db.query(ArticleView.visitor_key).filter(ArticleView.visitor_key.isnot(None), ArticleView.visitor_key != "").group_by(ArticleView.visitor_key).having(func.count(ArticleView.id) > 1).all()
    return {
        "total_views": total_views,
        "views_today": views_today,
        "views_7_days": views_7,
        "views_30_days": views_30,
        "unique_visitors": unique_visitors,
        "returning_visitors": len(returning_rows),
    }


def format_bytes(value: int) -> str:
    if value >= 1024 * 1024:
        return f"{round(value / (1024 * 1024))} MB"
    if value >= 1024:
        return f"{round(value / 1024)} KB"
    return f"{value} B"


def dashboard_status_context(db, total_articles: int, published: int, drafts: int, scheduled: int) -> dict:
    articles = db.query(Article).options(selectinload(Article.translations)).all()
    audits = [article_seo_audit(article, 'az') for article in articles]
    seo_health_score = round(sum(audit['score'] for audit in audits) / len(audits)) if audits else 100
    missing_meta_descriptions = sum(1 for audit in audits if not audit['checks'].get('meta_description'))
    missing_hreflang = sum(1 for audit in audits if not audit['checks'].get('hreflang'))
    latest_article_date = db.query(func.max(Article.published_at)).filter(Article.status == 'published').scalar() or db.query(func.max(Article.created_at)).scalar()
    latest_media_date = db.query(func.max(MediaAsset.created_at)).scalar()
    settings_map = get_settings_map(db)
    last_sitemap_refresh = settings_map.get('sitemap_last_refreshed_at') or 'Dynamic sitemap updates on every request'
    google_news_ready = published > 0 and seo_health_score >= 80 and missing_meta_descriptions == 0
    adsense_ready = bool((settings.adsense_publisher_id or '').strip())
    security_ready = settings.secret_key not in PLACEHOLDER_VALUES and len(settings.secret_key) >= 32
    return {
        'seo_health_score': seo_health_score,
        'google_news_status': 'Ready' if google_news_ready else 'Needs review',
        'adsense_status': 'Configured' if adsense_ready else 'Missing',
        'google_seo': {
            'xml_sitemap_status': 'Active',
            'news_sitemap_status': 'Active' if published else 'Waiting for published articles',
            'rss_feed_status': 'Active',
            'last_sitemap_refresh': last_sitemap_refresh,
            'missing_meta_descriptions': missing_meta_descriptions,
            'missing_hreflang': missing_hreflang,
        },
        'system_health': {
            'server_status': 'Online',
            'security_status': 'Enabled' if security_ready else 'Review secret key',
            'upload_limit': format_bytes(MAX_UPLOAD_IMAGE_BYTES),
            'protected_routes': '/admin, /admin/articles, /admin/media, /admin/seo, /admin/settings',
        },
        'editorial': {
            'published_articles': published,
            'draft_articles': drafts,
            'scheduled_articles': scheduled,
            'latest_article_date': latest_article_date,
        },
        'latest_activity': [
            {'label': 'Article published', 'detail': f'{published} live article(s)', 'timestamp': latest_article_date},
            {'label': 'Image uploaded', 'detail': 'Latest media library upload', 'timestamp': latest_media_date},
            {'label': 'SEO scan completed', 'detail': f'SEO health score {seo_health_score}%', 'timestamp': current_server_utc()},
            {'label': 'Sitemap refreshed', 'detail': last_sitemap_refresh, 'timestamp': None},
        ],
    }


def top_category_rows(db, limit: int = 10) -> list[dict]:
    rows = (
        db.query(Article.category, func.count(ArticleView.id))
        .join(ArticleView, ArticleView.article_id == Article.id)
        .group_by(Article.category)
        .order_by(func.count(ArticleView.id).desc())
        .limit(limit)
        .all()
    )
    total = sum(int(count or 0) for _, count in rows) or 1
    return [{"name": category or "Uncategorized", "views": int(count or 0), "share": round((int(count or 0) / total) * 100)} for category, count in rows]


def period_chart(rows: list[ArticleView], start: datetime, days: int, label_format: str) -> list[dict]:
    buckets = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        buckets.append({"key": day.date().isoformat(), "label": day.strftime(label_format), "views": 0})
    index = {item["key"]: item for item in buckets}
    for row in rows:
        key = row.viewed_at.date().isoformat()
        if key in index:
            index[key]["views"] += 1
    maximum = max([item["views"] for item in buckets] + [1])
    for item in buckets:
        item["height"] = max(8, round((item["views"] / maximum) * 100)) if item["views"] else 4
    return buckets


def weekly_chart(rows: list[ArticleView], start: datetime, weeks: int = 8) -> list[dict]:
    buckets = []
    for offset in range(weeks):
        week_start = start + timedelta(days=offset * 7)
        week_end = week_start + timedelta(days=7)
        views = sum(1 for row in rows if week_start <= row.viewed_at < week_end)
        buckets.append({"label": week_start.strftime("%b %d"), "views": views})
    maximum = max([item["views"] for item in buckets] + [1])
    for item in buckets:
        item["height"] = max(8, round((item["views"] / maximum) * 100)) if item["views"] else 4
    return buckets


def monthly_chart(rows: list[ArticleView], months: int = 6) -> list[dict]:
    today = utc_start_of_day()
    month_keys = []
    year, month = today.year, today.month
    for _ in range(months):
        month_keys.append((year, month))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    month_keys.reverse()
    buckets = []
    for year, month in month_keys:
        views = sum(1 for row in rows if row.viewed_at.year == year and row.viewed_at.month == month)
        buckets.append({"label": datetime(year, month, 1).strftime("%b"), "views": views})
    maximum = max([item["views"] for item in buckets] + [1])
    for item in buckets:
        item["height"] = max(8, round((item["views"] / maximum) * 100)) if item["views"] else 4
    return buckets


def traffic_charts(db, article_id: int | None = None) -> dict:
    today = utc_start_of_day()
    start_daily = today - timedelta(days=13)
    start_weekly = today - timedelta(days=7 * 7)
    start_monthly = today - timedelta(days=190)
    query = db.query(ArticleView).filter(ArticleView.viewed_at >= start_monthly)
    if article_id is not None:
        query = query.filter(ArticleView.article_id == article_id)
    rows = query.order_by(ArticleView.viewed_at.asc()).all()
    return {
        "daily": period_chart([row for row in rows if row.viewed_at >= start_daily], start_daily, 14, "%b %d"),
        "weekly": weekly_chart([row for row in rows if row.viewed_at >= start_weekly], start_weekly),
        "monthly": monthly_chart(rows),
    }


def article_analytics_context(db, article: Article) -> dict:
    history = db.query(ArticleView).filter(ArticleView.article_id == article.id).order_by(ArticleView.viewed_at.desc()).limit(100).all()
    sources = db.query(ArticleView.traffic_source, func.count(ArticleView.id)).filter(ArticleView.article_id == article.id).group_by(ArticleView.traffic_source).order_by(func.count(ArticleView.id).desc()).all()
    publish_start = article.published_at or article.created_at or datetime.utcnow()
    first_24h_end = publish_start + timedelta(days=1)
    first_24h_views = db.query(func.count(ArticleView.id)).filter(ArticleView.article_id == article.id, ArticleView.viewed_at >= publish_start, ArticleView.viewed_at < first_24h_end).scalar() or 0
    last_7_views = db.query(func.count(ArticleView.id)).filter(ArticleView.article_id == article.id, ArticleView.viewed_at >= utc_start_of_day() - timedelta(days=6)).scalar() or 0
    unique_visitors = db.query(func.count(func.distinct(ArticleView.visitor_key))).filter(ArticleView.article_id == article.id, ArticleView.visitor_key.isnot(None), ArticleView.visitor_key != "").scalar() or 0
    return {
        "history": history,
        "sources": [{"name": source or "Direct", "views": int(count or 0)} for source, count in sources],
        "charts": traffic_charts(db, article.id),
        "publish_performance": {
            "total_views": db.query(func.count(ArticleView.id)).filter(ArticleView.article_id == article.id).scalar() or 0,
            "first_24h_views": first_24h_views,
            "last_7_views": last_7_views,
            "unique_visitors": unique_visitors,
            "published_at": article.published_at,
        },
    }


def article_form_context(db, article: Article | None = None) -> dict:
    categories = db.query(Category).order_by(Category.name.asc()).all()
    if not categories:
        names = [c[0] for c in db.query(Article.category).filter(Article.category.isnot(None)).distinct().all() if c[0]]
        categories = [Category(name=name, slug=slugify(name), description="") for name in names]
    translations = {lang: get_translation(article, lang) for lang in SUPPORTED_LANGUAGES} if article else {lang: None for lang in SUPPORTED_LANGUAGES}
    picker_assets = db.query(MediaAsset).order_by(MediaAsset.created_at.desc()).limit(80).all()
    picker_rows = [SimpleNamespace(asset=asset, public_path=media_asset_public_path(asset), absolute_url=media_asset_absolute_url(asset)) for asset in picker_assets]
    return {"categories": categories, "languages": SUPPORTED_LANGUAGES, "language_labels": LANGUAGE_LABELS, "translations": translations, "ai_translation_status": ai_translation_status(), "media_picker_assets": picker_rows}



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
    # Safe for existing deployments: create the translation table from the
    # SQLAlchemy model if older databases were initialized before multilingual
    # article storage existed, then add any newly introduced nullable columns.
    bind = db.get_bind()
    ArticleTranslation.__table__.create(bind=bind, checkfirst=True)
    ArticleView.__table__.create(bind=bind, checkfirst=True)
    MediaAsset.__table__.create(bind=bind, checkfirst=True)
    publish_at_type = "DATETIME" if bind.dialect.name == "sqlite" else "TIMESTAMP"
    for statement in [
        "ALTER TABLE articles ADD COLUMN slug VARCHAR(500)",
        "ALTER TABLE articles ADD COLUMN narration_enabled BOOLEAN DEFAULT true",
        "ALTER TABLE articles ADD COLUMN meta_description TEXT",
        "ALTER TABLE articles ADD COLUMN is_featured BOOLEAN DEFAULT false",
        "ALTER TABLE articles ADD COLUMN is_trending BOOLEAN DEFAULT false",
        "ALTER TABLE articles ADD COLUMN homepage_order INTEGER DEFAULT 100",
        "ALTER TABLE articles ADD COLUMN view_count INTEGER DEFAULT 0",
        f"ALTER TABLE articles ADD COLUMN publish_at {publish_at_type}",
        "ALTER TABLE article_translations ADD COLUMN slug VARCHAR(500)",
        "ALTER TABLE article_translations ADD COLUMN meta_description TEXT",
        "ALTER TABLE article_translations ADD COLUMN tags VARCHAR(500)",
        "ALTER TABLE media_assets ADD COLUMN url VARCHAR(1000)",
        "ALTER TABLE media_assets ADD COLUMN mime_type VARCHAR(120)",
        "ALTER TABLE media_assets ADD COLUMN width INTEGER",
        "ALTER TABLE media_assets ADD COLUMN height INTEGER",
    ]:
        try:
            db.execute(text(statement))
            db.commit()
        except Exception:
            db.rollback()
    for statement in [
        "CREATE INDEX IF NOT EXISTS ix_articles_view_count ON articles (view_count)",
        "CREATE INDEX IF NOT EXISTS ix_articles_publish_at ON articles (publish_at)",
        "CREATE INDEX IF NOT EXISTS ix_article_translations_article_id ON article_translations (article_id)",
        "CREATE INDEX IF NOT EXISTS ix_article_translations_language ON article_translations (language)",
        "CREATE INDEX IF NOT EXISTS ix_article_translations_slug ON article_translations (slug)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_article_translations_article_language ON article_translations (article_id, language)",
        "CREATE INDEX IF NOT EXISTS ix_article_translations_language_slug ON article_translations (language, slug)",
        "CREATE INDEX IF NOT EXISTS ix_article_views_article_id ON article_views (article_id)",
        "CREATE INDEX IF NOT EXISTS ix_article_views_viewed_at ON article_views (viewed_at)",
        "CREATE INDEX IF NOT EXISTS ix_article_views_visitor_key ON article_views (visitor_key)",
        "CREATE INDEX IF NOT EXISTS ix_article_views_traffic_source ON article_views (traffic_source)",
        "UPDATE media_assets SET url = path WHERE url IS NULL OR url = ''",
        "UPDATE media_assets SET mime_type = content_type WHERE mime_type IS NULL OR mime_type = ''",
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
    scheduler.add_job(run_scheduled_publish_check, "interval", seconds=60, id="scheduled_publish_job", replace_existing=True)
    if not scheduler.running:
        scheduler.start()


@app.get("/", response_class=HTMLResponse)
@app.get("/{language}/", response_class=HTMLResponse)
def home(request: Request, language: str = "az", q: str = "", category: str = "", db=Depends(get_db)):
    language = language if language in SUPPORTED_LANGUAGES else "az"
    publish_due_scheduled_articles(db)
    ensure_categories(db)
    query = db.query(Article).options(selectinload(Article.translations)).filter(public_article_visibility_filter())
    if q:
        translation_matches = db.query(ArticleTranslation.article_id).filter(
            ArticleTranslation.language == language,
            (ArticleTranslation.title.ilike(f"%{q}%")) | (ArticleTranslation.summary.ilike(f"%{q}%")),
        )
        query = query.filter((Article.title.ilike(f"%{q}%")) | (Article.summary.ilike(f"%{q}%")) | (Article.id.in_(translation_matches.scalar_subquery())))
    if category:
        query = query.filter(Article.category == category)
    articles = attach_real_view_counts(db, query.order_by(public_article_datetime_expression().desc(), Article.created_at.desc(), Article.id.desc()).limit(30).all())
    category_labels = public_category_labels(language)
    article_cards = [article_card(a, language, category_labels) for a in articles]
    hero = article_cards[0] if article_cards else None
    latest_cards = [row for row in article_cards if not hero or row["article"].id != hero["article"].id]
    sidebar_query = db.query(Article).options(selectinload(Article.translations)).filter(public_article_visibility_filter())
    if hero:
        sidebar_query = sidebar_query.filter(Article.id != hero["article"].id)
    sidebar_articles = attach_real_view_counts(db, sidebar_query.order_by(public_article_datetime_expression().desc(), Article.created_at.desc(), Article.id.desc()).limit(8).all())
    sidebar_cards = [article_card(a, language, category_labels) for a in sidebar_articles]
    categories = public_category_navigation(db)
    alt_links = {lang: f"/{lang}/" for lang in SUPPORTED_LANGUAGES}
    settings_map = get_settings_map(db)
    canonical = canonical_url(request, f'{language}/')
    schema_graph = [
        build_organization_schema(settings_map),
        build_website_schema(settings_map, language),
        build_breadcrumb_schema([("Home", canonical)]),
    ]
    return templates.TemplateResponse("public/home.html", {"request": request, "articles": article_cards, "latest_articles": latest_cards, "sidebar_articles": sidebar_cards, "hero": hero, "categories": categories["primary"], "secondary_categories": categories["secondary"], "q": q, "category": category, "site_url": settings.site_url, "canonical": canonical, "language": language, "languages": SUPPORTED_LANGUAGES, "alt_links": alt_links, "ui": public_labels(language), "category_labels": category_labels, "settings_map": settings_map, "verification_meta": seo_verification_meta(settings_map), "schema_graph": schema_graph, "site_name": site_name_from_settings(settings_map), "app_version": APP_VERSION})


@app.get("/privacy", response_class=HTMLResponse)
def privacy_policy(request: Request, db=Depends(get_db)):
    language = "en"
    ensure_categories(db)
    categories = public_category_navigation(db)
    category_labels = public_category_labels(language)
    settings_map = get_settings_map(db)
    canonical = canonical_url(request, "privacy")
    schema_graph = [
        build_organization_schema(settings_map),
        build_website_schema(settings_map, language),
        build_breadcrumb_schema([("Home", f"{settings.site_url.rstrip('/')}/en/"), ("Privacy Policy", canonical)]),
    ]
    return templates.TemplateResponse("public/privacy.html", {
        "request": request,
        "categories": categories["primary"],
        "secondary_categories": categories["secondary"],
        "q": "",
        "site_url": settings.site_url,
        "canonical": canonical,
        "language": language,
        "languages": SUPPORTED_LANGUAGES,
        "alt_links": {"en": "/privacy"},
        "ui": public_labels(language),
        "category_labels": category_labels,
        "settings_map": settings_map,
        "verification_meta": seo_verification_meta(settings_map),
        "schema_graph": schema_graph,
        "site_name": site_name_from_settings(settings_map),
        "app_version": APP_VERSION,
    })


@app.get("/terms", response_class=HTMLResponse)
def terms_of_use(request: Request, db=Depends(get_db)):
    language = "en"
    ensure_categories(db)
    categories = public_category_navigation(db)
    category_labels = public_category_labels(language)
    settings_map = get_settings_map(db)
    canonical = canonical_url(request, "terms")
    schema_graph = [
        build_organization_schema(settings_map),
        build_website_schema(settings_map, language),
        build_breadcrumb_schema([("Home", f"{settings.site_url.rstrip('/')}/en/"), ("Terms of Use", canonical)]),
    ]
    return templates.TemplateResponse("public/terms.html", {
        "request": request,
        "categories": categories["primary"],
        "secondary_categories": categories["secondary"],
        "q": "",
        "site_url": settings.site_url,
        "canonical": canonical,
        "language": language,
        "languages": SUPPORTED_LANGUAGES,
        "alt_links": {"en": "/terms"},
        "ui": public_labels(language),
        "category_labels": category_labels,
        "settings_map": settings_map,
        "verification_meta": seo_verification_meta(settings_map),
        "schema_graph": schema_graph,
        "site_name": site_name_from_settings(settings_map),
        "app_version": APP_VERSION,
    })


def render_article_page(slug: str, request: Request, language: str = "az", db=Depends(get_db)):
    language = language if language in SUPPORTED_LANGUAGES else "az"
    publish_due_scheduled_articles(db)
    article = find_published_article_by_slug(db, slug, language)
    if not article:
        raise HTTPException(404)
    record_article_view(db, article, request, language)
    article.real_view_count = article_view_count_map(db, [article.id]).get(article.id, 0)
    view = localized_article_view(article, language)
    narration = db.query(ArticleNarration).filter(ArticleNarration.article_id == article.id, ArticleNarration.language == language).first()
    alt_links = {lang: article_url(lang, localized_slug(article, lang)) for lang in SUPPORTED_LANGUAGES}
    related = db.query(Article).options(selectinload(Article.translations)).filter(public_article_visibility_filter(), Article.id != article.id, Article.category == article.category).order_by(public_article_datetime_expression().desc(), Article.created_at.desc()).limit(3).all()
    if len(related) < 3:
        related = related + db.query(Article).options(selectinload(Article.translations)).filter(public_article_visibility_filter(), Article.id != article.id, Article.category != article.category).order_by(public_article_datetime_expression().desc(), Article.created_at.desc()).limit(3 - len(related)).all()
    related = attach_real_view_counts(db, related)
    canonical = canonical_url(request, f"{language}/{view.slug}")
    navigation = public_category_navigation(db)
    category_labels = public_category_labels(language)
    settings_map = get_settings_map(db)
    image_exists = uploaded_image_exists(article.image_url)
    image_url = public_absolute_url(public_image_url(article.image_url)) if image_exists else public_absolute_url('/assets/og-cover.jpg')
    schema_graph = [
        build_organization_schema(settings_map),
        build_website_schema(settings_map, language),
        build_breadcrumb_schema([("Home", canonical_url(request, f'{language}/')), (view.category_label, canonical_url(request, f'{language}/?category={article.category or ""}')), (view.title, canonical)]),
        build_news_article_schema(article, view, canonical, image_url, settings_map, language),
    ]
    seo_audit = article_seo_audit(article, language)
    return templates.TemplateResponse("public/article.html", {"request": request, "article": view, "root_article": article, "image_exists": image_exists, "narration": narration, "related_articles": [article_card(a, language, category_labels) for a in related], "categories": navigation["primary"], "secondary_categories": navigation["secondary"], "share_url": canonical, "site_url": settings.site_url, "canonical": canonical, "language": language, "languages": SUPPORTED_LANGUAGES, "alt_links": alt_links, "ui": public_labels(language), "category_labels": category_labels, "settings_map": settings_map, "verification_meta": seo_verification_meta(settings_map), "schema_graph": schema_graph, "seo_audit": seo_audit, "site_name": site_name_from_settings(settings_map), "og_image": image_url, "app_version": APP_VERSION})


@app.get("/article/{slug}", response_class=HTMLResponse)
@app.get("/{language}/article/{slug}", response_class=HTMLResponse)
def article_by_slug(slug: str, request: Request, language: str = "az", db=Depends(get_db)):
    return render_article_page(slug, request, language, db)


@app.get('/search', response_class=HTMLResponse)
def search(request: Request, q: str = "", db=Depends(get_db)):
    return home(request, q=q, db=db)


@app.get('/category/{category}', response_class=HTMLResponse)
def category_page(category: str, request: Request, db=Depends(get_db)):
    return home(request, category=category, db=db)


@app.get('/sitemap.xml')
def sitemap(db=Depends(get_db)):
    publish_due_scheduled_articles(db)
    base_url = settings.site_url.rstrip("/")
    url_entries = [
        f"<url><loc>{xml_escape(base_url + '/')}</loc><changefreq>hourly</changefreq><priority>1.0</priority></url>"
    ]
    url_entries.extend(
        f"<url><loc>{xml_escape(base_url + '/' + lang + '/')}</loc><changefreq>hourly</changefreq><priority>0.9</priority></url>"
        for lang in SUPPORTED_LANGUAGES
    )
    url_entries.extend(
        f"<url><loc>{xml_escape(base_url + path)}</loc><changefreq>monthly</changefreq><priority>0.5</priority></url>"
        for path in ("/privacy", "/terms")
    )
    articles = db.query(Article).options(selectinload(Article.translations)).filter(public_article_visibility_filter()).order_by(public_article_datetime_expression().desc()).all()
    for article in articles:
        for lang in SUPPORTED_LANGUAGES:
            if lang != "az" and not article_translation_complete(article, lang):
                continue
            url = f"{base_url}{article_url(lang, localized_slug(article, lang))}"
            lastmod = (article.updated_at or public_article_datetime(article))
            url_entries.append(
                f"<url><loc>{xml_escape(url)}</loc><lastmod>{xml_escape(iso_datetime(lastmod))}</lastmod><changefreq>daily</changefreq><priority>0.8</priority></url>"
            )
    content = f'''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{''.join(url_entries)}</urlset>'''
    return render_xml_response(content)


@app.get('/news-sitemap.xml')
def news_sitemap(db=Depends(get_db)):
    publish_due_scheduled_articles(db)
    base_url = settings.site_url.rstrip("/")
    news_cutoff = datetime_for_database(current_server_utc() - timedelta(days=2))
    articles = db.query(Article).options(selectinload(Article.translations)).filter(public_article_visibility_filter(), public_article_datetime_expression() >= news_cutoff).order_by(public_article_datetime_expression().desc()).limit(1000).all()
    entries = []
    for article in articles:
        view = localized_article_view(article, "az")
        entries.append(
            "<url>"
            f"<loc>{xml_escape(base_url + article_url('az', article.slug or str(article.id)))}</loc>"
            "<news:news>"
            "<news:publication><news:name>VREYC</news:name><news:language>az</news:language></news:publication>"
            f"<news:publication_date>{xml_escape(iso_datetime(public_article_datetime(article)))}</news:publication_date>"
            f"<news:title>{xml_escape(view.title)}</news:title>"
            "</news:news>"
            "</url>"
        )
    content = f'''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">{''.join(entries)}</urlset>'''
    return render_xml_response(content)


@app.get('/rss.xml')
@app.get('/feed.xml')
def rss_feed(db=Depends(get_db)):
    publish_due_scheduled_articles(db)
    base_url = settings.site_url.rstrip("/")
    articles = db.query(Article).options(selectinload(Article.translations)).filter(public_article_visibility_filter()).order_by(public_article_datetime_expression().desc(), Article.created_at.desc()).limit(50).all()
    items = []
    for article in articles:
        view = localized_article_view(article, "az")
        link = f"{base_url}{article_url('az', article.slug or str(article.id))}"
        pub_date = format_datetime(public_article_datetime(article) or datetime.utcnow())
        enclosure = ""
        if uploaded_image_exists(article.image_url):
            enclosure = f'<enclosure url="{xml_escape(public_absolute_url(public_image_url(article.image_url)))}" type="image/jpeg" />'
        items.append(
            "<item>"
            f"<title>{xml_escape(view.title)}</title>"
            f"<link>{xml_escape(link)}</link>"
            f'<guid isPermaLink="true">{xml_escape(link)}</guid>'
            f"<description>{xml_escape(view.summary or view.meta_description or view.title)}</description>"
            f"<pubDate>{xml_escape(pub_date)}</pubDate>"
            f"{enclosure}"
            "</item>"
        )
    content = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>VREYC Latest News</title><link>{xml_escape(base_url + '/')}</link><description>Latest VREYC news updates</description>{''.join(items)}</channel></rss>'''
    return render_xml_response(content, media_type="application/rss+xml")


@app.get('/robots.txt')
def robots():
    base_url = settings.site_url.rstrip('/')
    content = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin\n"
        f"Sitemap: {base_url}/sitemap.xml\n"
        f"Sitemap: {base_url}/news-sitemap.xml\n"
        f"RSS: {base_url}/rss.xml\n"
    )
    return Response(content=content, media_type='text/plain')


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
    return templates.TemplateResponse('admin/login.html', {'request': request, 'error': 'Wrong username or password'}, status_code=401)


@app.post('/admin/logout')
def logout(request: Request):
    clear_session(request)
    return RedirectResponse('/admin/login', status_code=302)


@app.get('/admin', response_class=HTMLResponse)
def admin_dashboard(request: Request, db=Depends(get_db), _=Depends(require_auth)):
    publish_due_scheduled_articles(db)
    drafts = db.query(Article).filter(Article.status == 'draft').count()
    published = db.query(Article).filter(Article.status == 'published').count()
    scheduled = db.query(Article).filter(Article.status.in_(SCHEDULED_STATUS_VALUES)).count()
    next_scheduled_article = (
        db.query(Article)
        .filter(Article.status.in_(SCHEDULED_STATUS_VALUES), Article.publish_at.isnot(None))
        .order_by(Article.publish_at.asc(), Article.created_at.asc(), Article.id.asc())
        .first()
    )
    total_articles = db.query(Article).count()
    categories = db.query(Category).count() or db.query(Article.category).filter(Article.category.isnot(None)).distinct().count()
    media_count = db.query(MediaAsset).count()
    logs = db.query(FetchLog).order_by(FetchLog.created_at.desc()).limit(8).all()
    latest_articles = attach_real_view_counts(db, db.query(Article).order_by(Article.created_at.desc(), Article.id.desc()).limit(10).all())
    most_viewed_articles = (
        db.query(Article, func.count(ArticleView.id).label("real_view_count"))
        .join(ArticleView, ArticleView.article_id == Article.id)
        .group_by(Article.id)
        .order_by(func.count(ArticleView.id).desc(), Article.published_at.desc(), Article.created_at.desc(), Article.id.desc())
        .limit(10)
        .all()
    )
    most_viewed_articles = [setattr(article, "real_view_count", int(real_view_count or 0)) or article for article, real_view_count in most_viewed_articles]
    analytics = analytics_summary(db)
    dashboard_status = dashboard_status_context(db, total_articles, published, drafts, scheduled)
    return templates.TemplateResponse('admin/dashboard.html', {'request': request, 'drafts': drafts, 'published': published, 'scheduled': scheduled, 'next_scheduled_article': next_scheduled_article, 'total_articles': total_articles, 'categories': categories, 'media_count': media_count, 'logs': logs, 'recent_articles': latest_articles, 'latest_articles': latest_articles, 'most_viewed_articles': most_viewed_articles, 'analytics': analytics, 'dashboard_status': dashboard_status, 'top_categories': top_category_rows(db), 'traffic_charts': traffic_charts(db), "languages": SUPPORTED_LANGUAGES, "ai_translation_status": ai_translation_status()})


@app.get('/admin/articles', response_class=HTMLResponse)
def admin_articles(
    request: Request,
    q: str = "",
    status: str = "all",
    category: str = "",
    language: str = "",
    date_from: str = "",
    date_to: str = "",
    sort: str = "newest",
    page: int = 1,
    per_page: int = 25,
    db=Depends(get_db),
    _=Depends(require_auth),
):
    page = safe_positive_int(page, 1)
    per_page = safe_positive_int(per_page, 25, 100)
    publish_due_scheduled_articles(db)
    query = filtered_admin_article_query(db, q, status, category, language, date_from, date_to)
    total = query.count()
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, total_pages)
    articles = attach_real_view_counts(db, apply_admin_article_sort(query, sort).offset((page - 1) * per_page).limit(per_page).all())
    narration_map = {n.article_id: n for n in db.query(ArticleNarration).filter(ArticleNarration.article_id.in_([a.id for a in articles] or [0])).all()}
    translation_missing_map = {a.id: missing_translation_languages(a) for a in articles}
    seo_score_map = {a.id: article_seo_audit(a, 'az')['score'] for a in articles}
    categories = admin_article_categories(db)
    filters = {"q": q, "status": status, "category": category, "language": language, "date_from": date_from, "date_to": date_to, "sort": sort, "page": page, "per_page": per_page}
    return templates.TemplateResponse("admin/articles.html", {"request": request, "articles": articles, "status": status, "narration_map": narration_map, "translation_missing_map": translation_missing_map, "seo_score_map": seo_score_map, "languages": SUPPORTED_LANGUAGES, "language_labels": LANGUAGE_LABELS, "categories": categories, "filters": filters, "total": total, "total_pages": total_pages, "page": page, "per_page": per_page, "ai_translation_status": ai_translation_status()})



def admin_publish_due_redirect(return_to: str, published_count: int) -> str:
    target = return_to if return_to.startswith("/admin") else "/admin/articles"
    separator = "&" if "?" in target else "?"
    return f"{target}{separator}published_due={published_count}"


@app.post('/admin/articles/publish-due')
def admin_publish_due_scheduled_articles(request: Request, return_to: str = "/admin/articles", db=Depends(get_db), _=Depends(require_auth)):
    published_count = publish_due_scheduled_articles(db)
    return RedirectResponse(admin_publish_due_redirect(return_to, published_count), status_code=302)



@app.post('/admin/articles/bulk')
async def bulk_articles(request: Request, db=Depends(get_db), _=Depends(require_auth)):
    form = await request.form()
    selected_ids = [int(value) for value in form.getlist('article_ids') if str(value).isdigit()]
    action = form.get('bulk_action', '')
    redirect_url = admin_articles_redirect(request)
    if not selected_ids or not action:
        return RedirectResponse(redirect_url, status_code=302)
    articles = db.query(Article).filter(Article.id.in_(selected_ids)).all()
    now = datetime.utcnow()
    if action == 'delete':
        if form.get('confirm_bulk_delete', '').strip().upper() != 'DELETE':
            return RedirectResponse(redirect_url, status_code=302)
        for article in articles:
            db.delete(article)
    elif action == 'publish':
        for article in articles:
            article.status = 'published'
            article.publish_at = None
            article.published_at = article.published_at or now
            article.slug = article.slug or unique_article_slug(db, article.title, article.id)
            article.updated_at = now
            touch_sitemap_refresh(db)
            queue_narration(db, article)
    elif action == 'unpublish':
        for article in articles:
            article.status = 'draft'
            article.publish_at = None
            article.updated_at = now
    elif action == 'category':
        new_category = form.get('bulk_category', '').strip()
        if new_category:
            for article in articles:
                article.category = new_category
                article.updated_at = now
    db.commit()
    return RedirectResponse(redirect_url, status_code=302)


@app.get('/admin/articles/new', response_class=HTMLResponse)
def new_article_page(request: Request, db=Depends(get_db), _=Depends(require_auth)):
    context = article_form_context(db)
    context.update({'request': request, 'article': None, 'mode': 'new', 'narration': None})
    return templates.TemplateResponse('admin/edit.html', context)


@app.post('/admin/articles/new')
async def create_article(request: Request, db=Depends(get_db), _=Depends(require_auth)):
    form = await request.form()
    status = normalize_article_status(form.get('status'))
    publish_at = parse_admin_datetime(form.get('publish_at'))
    if not require_scheduled_publish_at(status, publish_at):
        return RedirectResponse('/admin/articles/new?error=publish_at_required', status_code=302)
    uploaded_image = save_image_upload(form.get('hero_image'), form.get('hero_alt_text', ''))
    if uploaded_image:
        db.add(uploaded_image)
        db.flush()
    title = form.get('title_az') or form.get('title') or 'Untitled article'
    now = datetime.utcnow()
    article = Article(
        title=title,
        slug=unique_article_slug(db, form.get('slug_az') or title),
        summary=form.get('summary_az', ''),
        content=sanitize_article_html(form.get('content_az', '')),
        seo_title=form.get('seo_title_az', ''),
        meta_description=form.get('meta_description_az', ''),
        tags=form.get('tags_az', ''),
        image_url=uploaded_image.path if uploaded_image else form.get('image_url', ''),
        category=form.get('category', ''),
        status=status,
        language='az',
        narration_enabled=form.get('narration_enabled') == 'on',
        is_featured=form.get('is_featured') == 'on',
        is_trending=form.get('is_trending') == 'on',
        homepage_order=int(form.get('homepage_order') or 100),
        publish_at=publish_at if status == 'scheduled' else None,
        published_at=now if status == 'published' else None,
    )
    db.add(article)
    db.flush()
    for lang in SUPPORTED_LANGUAGES:
        if lang == 'az':
            continue
        if any(form.get(f'{field}_{lang}', '') for field in ['title', 'summary', 'content', 'seo_title', 'meta_description', 'tags', 'slug']):
            row = ArticleTranslation(article_id=article.id, language=lang)
            row.title = form.get(f'title_{lang}', '')
            row.slug = unique_translation_slug(db, lang, form.get(f'slug_{lang}') or row.title or f'{article.slug}-{lang}')
            row.summary = form.get(f'summary_{lang}', '')
            row.content = sanitize_article_html(form.get(f'content_{lang}', ''))
            row.seo_title = form.get(f'seo_title_{lang}', '')
            row.meta_description = form.get(f'meta_description_{lang}', '')
            row.tags = form.get(f'tags_{lang}', '')
            db.add(row)
    if article.status == 'published':
        touch_sitemap_refresh(db)
    db.commit()
    if is_ai_translation_configured():
        scheduler.add_job(generate_missing_translations, args=[article.id], id=f"article_translation_{article.id}_{datetime.utcnow().timestamp()}", replace_existing=False)
    return RedirectResponse('/admin/articles', status_code=302)


@app.post('/admin/articles/{article_id}/publish')
def publish_article(article_id: int, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    a = db.query(Article).get(article_id)
    if a:
        a.status = 'published'
        a.publish_at = None
        a.published_at = a.published_at or datetime.utcnow()
        a.slug = a.slug or unique_article_slug(db, a.title, a.id)
        a.updated_at = datetime.utcnow()
        touch_sitemap_refresh(db)
        db.commit()
        queue_narration(db, a)
        if is_ai_translation_configured():
            scheduler.add_job(generate_missing_translations, args=[a.id], id=f"article_translation_{a.id}_{datetime.utcnow().timestamp()}", replace_existing=False)
        db.commit()
    return RedirectResponse('/admin/articles?status=published', status_code=302)


@app.post('/admin/articles/{article_id}/unpublish')
def unpublish_article(article_id: int, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    a = db.query(Article).get(article_id)
    if a:
        a.status = 'draft'
        a.publish_at = None
        a.updated_at = datetime.utcnow()
        db.commit()
    return RedirectResponse('/admin/articles?status=draft', status_code=302)


@app.get('/admin/articles/{article_id}/analytics', response_class=HTMLResponse)
def admin_article_analytics(article_id: int, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(404)
    context = article_analytics_context(db, article)
    return templates.TemplateResponse('admin/article_analytics.html', {'request': request, 'article': article, **context})


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
    requested_status = normalize_article_status(form.get('status'))
    requested_publish_at = parse_admin_datetime(form.get('publish_at'))
    if not require_scheduled_publish_at(requested_status, requested_publish_at):
        return RedirectResponse(f'/admin/articles/{article_id}/edit?error=publish_at_required', status_code=302)
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
    a.content = sanitize_article_html(form.get('content_az', ''))
    a.seo_title = form.get('seo_title_az', '')
    a.meta_description = form.get('meta_description_az', '')
    a.tags = form.get('tags_az', '')
    a.image_url = uploaded_image.path if uploaded_image else form.get('image_url', '')
    a.category = form.get('category', '')
    old_status = a.status
    a.status = requested_status
    a.publish_at = requested_publish_at if a.status == 'scheduled' else None
    if a.status == 'scheduled':
        a.published_at = None
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
        row.slug = unique_translation_slug(db, lang, form.get(f'slug_{lang}') or row.slug or row.title or f'{a.slug}-{lang}', row.id)
        row.summary = form.get(f'summary_{lang}', '')
        row.content = sanitize_article_html(form.get(f'content_{lang}', ''))
        row.seo_title = form.get(f'seo_title_{lang}', '')
        row.meta_description = form.get(f'meta_description_{lang}', '')
        row.tags = form.get(f'tags_{lang}', '')
        row.updated_at = datetime.utcnow()
    if a.status == 'published':
        touch_sitemap_refresh(db)
    db.commit()
    translation_status = "queued" if is_ai_translation_configured() else "not_configured"
    if is_ai_translation_configured():
        scheduler.add_job(generate_missing_translations, args=[a.id], id=f"article_translation_{a.id}_{datetime.utcnow().timestamp()}", replace_existing=False)
    return RedirectResponse(f'/admin/articles/{a.id}/edit?saved=1&translations={translation_status}', status_code=302)


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
def media_page(request: Request, q: str = '', date_from: str = '', date_to: str = '', sort: str = 'newest', page: int = 1, db=Depends(get_db), _=Depends(require_auth)):
    page = max(1, page)
    per_page = 24
    query = db.query(MediaAsset)
    if q.strip():
        query = query.filter(MediaAsset.filename.ilike(f"%{q.strip()}%"))
    if date_from.strip():
        try:
            query = query.filter(MediaAsset.created_at >= datetime.fromisoformat(date_from.strip()))
        except ValueError:
            pass
    if date_to.strip():
        try:
            query = query.filter(MediaAsset.created_at < datetime.fromisoformat(date_to.strip()) + timedelta(days=1))
        except ValueError:
            pass
    query = query.order_by(MediaAsset.created_at.asc() if sort == 'oldest' else MediaAsset.created_at.desc())
    total, media_rows = media_assets_for_display(db, query, page, per_page)
    total_pages = max(1, (total + per_page - 1) // per_page)
    filters = {'q': q, 'date_from': date_from, 'date_to': date_to, 'sort': sort}
    return templates.TemplateResponse('admin/media.html', {'request': request, 'media_rows': media_rows, 'assets': [row.asset for row in media_rows], 'filters': filters, 'page': page, 'per_page': per_page, 'total': total, 'total_pages': total_pages, 'upload_dir': str(UPLOAD_DIR)})


@app.post('/admin/media')
async def upload_media(request: Request, files: list[UploadFile] = File(default=[]), file: UploadFile | None = File(default=None), alt_text: str = Form(''), db=Depends(get_db), _=Depends(require_auth)):
    uploads = [upload for upload in (files or []) if is_uploaded_file(upload)]
    if is_uploaded_file(file):
        uploads.append(file)
    for upload in uploads:
        asset = save_image_upload(upload, alt_text)
        if asset:
            db.add(asset)
    db.commit()
    return RedirectResponse('/admin/media', status_code=302)


@app.post('/admin/media/{asset_id}/delete')
def delete_media(asset_id: int, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    asset = db.query(MediaAsset).get(asset_id)
    if asset:
        if media_usage_count(db, asset) > 0:
            return RedirectResponse('/admin/media?warning=used', status_code=302)
        public_path = media_asset_public_path(asset)
        local_path = local_uploaded_image_path(public_path) or Path(public_path.lstrip('/'))
        if local_path.exists() and local_path.is_file():
            local_path.unlink()
        for width in IMAGE_VARIANT_WIDTHS:
            variant = local_path.with_name(f"{local_path.stem}-{width}.webp")
            if variant.exists() and variant.is_file():
                variant.unlink()
        db.delete(asset)
        db.commit()
    return RedirectResponse('/admin/media', status_code=302)


@app.get('/admin/seo', response_class=HTMLResponse)
def admin_seo_diagnostics(request: Request, db=Depends(get_db), _=Depends(require_auth)):
    articles = db.query(Article).options(selectinload(Article.translations)).order_by(Article.status.desc(), Article.published_at.desc(), Article.updated_at.desc()).all()
    rows = []
    issue_counts = {
        'Missing meta title': 0,
        'Missing meta description': 0,
        'Missing image': 0,
        'Missing schema': 0,
        'Missing canonical': 0,
        'Missing hreflang': 0,
        'Missing translation': 0,
    }
    for article in articles:
        audit = article_seo_audit(article, 'az')
        for issue in audit['issues']:
            if issue.startswith('Missing schema'):
                issue_counts['Missing schema'] += 1
            elif issue in issue_counts:
                issue_counts[issue] += 1
            elif issue == 'Missing hreflang translation':
                issue_counts['Missing hreflang'] += 1
        rows.append({'article': article, 'audit': audit})
    settings_map = get_settings_map(db)
    return templates.TemplateResponse('admin/seo.html', {'request': request, 'rows': rows, 'issue_counts': issue_counts, 'settings_map': settings_map, 'languages': SUPPORTED_LANGUAGES, 'ai_translation_status': ai_translation_status()})


@app.get('/admin/settings', response_class=HTMLResponse)
def settings_page(request: Request, db=Depends(get_db), _=Depends(require_auth)):
    admin_settings = get_settings_map(db)
    return templates.TemplateResponse('admin/settings.html', {'request': request, 'settings_map': admin_settings, 'config': settings, 'languages': SUPPORTED_LANGUAGES, 'ai_translation_status': ai_translation_status()})


@app.post('/admin/settings')
def save_settings(request: Request, site_name: str = Form('VREYC'), editor_name: str = Form('Editor'), publish_mode: str = Form('manual'), default_language: str = Form('az'), google_search_console_verification: str | None = Form(None), bing_webmaster_verification: str | None = Form(None), organization_logo_url: str | None = Form(None), youtube_url: str | None = Form(None), tiktok_url: str | None = Form(None), db=Depends(get_db), _=Depends(require_auth)):
    values = {
        'site_name': site_name,
        'editor_name': editor_name,
        'publish_mode': publish_mode,
        'default_language': default_language,
        'google_search_console_verification': google_search_console_verification.strip() if google_search_console_verification is not None else None,
        'bing_webmaster_verification': bing_webmaster_verification.strip() if bing_webmaster_verification is not None else None,
        'organization_logo_url': organization_logo_url.strip() if organization_logo_url is not None else None,
        'youtube_url': youtube_url.strip() if youtube_url is not None else None,
        'tiktok_url': tiktok_url.strip() if tiktok_url is not None else None,
    }
    for key, value in values.items():
        if value is not None:
            save_setting(db, key, value)
    db.commit()
    return RedirectResponse('/admin/settings?saved=1', status_code=302)


@app.get('/admin/translations', response_class=HTMLResponse)
def admin_translations(request: Request, db=Depends(get_db), _=Depends(require_auth)):
    articles = db.query(Article).options(selectinload(Article.translations)).order_by(Article.updated_at.desc(), Article.created_at.desc()).all()
    translation_missing_map = {a.id: missing_translation_languages(a) for a in articles}
    return templates.TemplateResponse('admin/translations.html', {'request': request, 'articles': articles, 'languages': SUPPORTED_LANGUAGES, 'translation_missing_map': translation_missing_map, 'ai_translation_status': ai_translation_status()})


@app.post('/admin/translations/{article_id}/generate')
def admin_generate_translations(article_id: int, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    if not db.query(Article).get(article_id):
        return RedirectResponse('/admin/translations?queued=missing_article', status_code=302)
    if not is_ai_translation_configured():
        db.add(FetchLog(level="WARNING", message=AI_TRANSLATION_WARNING))
        db.commit()
        return RedirectResponse('/admin/translations?warning=ai_not_configured', status_code=302)
    scheduler.add_job(generate_missing_translations, args=[article_id], id=f"manual_article_translation_{article_id}_{datetime.utcnow().timestamp()}", replace_existing=False)
    return RedirectResponse('/admin/translations?queued=article', status_code=302)


@app.post('/admin/translations/generate-missing')
def admin_generate_all_missing_translations(request: Request, db=Depends(get_db), _=Depends(require_auth)):
    if not is_ai_translation_configured():
        db.add(FetchLog(level="WARNING", message=AI_TRANSLATION_WARNING))
        db.commit()
        return RedirectResponse('/admin/translations?warning=ai_not_configured', status_code=302)
    scheduler.add_job(generate_all_missing_translations, id=f"bulk_article_translations_{datetime.utcnow().timestamp()}", replace_existing=False)
    return RedirectResponse('/admin/translations?queued=bulk', status_code=302)


@app.post('/admin/articles/{article_id}/translations/generate')
def admin_generate_article_missing_translations(article_id: int, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    if not db.query(Article).get(article_id):
        return RedirectResponse('/admin/articles', status_code=302)
    if not is_ai_translation_configured():
        db.add(FetchLog(level="WARNING", message=AI_TRANSLATION_WARNING))
        db.commit()
        return RedirectResponse(f'/admin/articles/{article_id}/edit?warning=ai_not_configured', status_code=302)
    scheduler.add_job(generate_missing_translations, args=[article_id], id=f"edit_article_translation_{article_id}_{datetime.utcnow().timestamp()}", replace_existing=False)
    return RedirectResponse(f'/admin/articles/{article_id}/edit?translations=queued', status_code=302)


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


@app.get("/{language}/{slug}", response_class=HTMLResponse)
def article_by_language_slug(language: str, slug: str, request: Request, db=Depends(get_db)):
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(404)
    return render_article_page(slug, request, language, db)


@app.exception_handler(404)
def not_found(request: Request, exc):
    return templates.TemplateResponse('public/404.html', {'request': request}, status_code=404)


@app.exception_handler(500)
def server_error(request: Request, exc):
    return templates.TemplateResponse('public/500.html', {'request': request}, status_code=500)
