from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo
import hashlib
import json
import logging
import os
import time
import threading
from email.utils import format_datetime
import html
from types import SimpleNamespace
import re
import shutil
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree
from pathlib import Path
from uuid import uuid4
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import selectinload
from fastapi import FastAPI, Request, Depends, Form, HTTPException, UploadFile, File
from PIL import Image, UnidentifiedImageError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
import requests

from config import PLACEHOLDER_VALUES, settings
from database.session import SessionLocal, init_db
from database.models import Article, ArticleRevision, ArticleView, FetchLog, Setting, ArticleNarration, ArticleTranslation, Category, MediaAsset
from cms.auth.security import is_authenticated, set_session, clear_session, verify_password
from scheduler.jobs import run_fetch_pipeline, queue_narration, generate_pending_narrations
from ai.pipeline import AIEngine, OPENAI_MODEL_OPTIONS, openai_runtime_settings
from ai.translation_service import (
    AI_TRANSLATION_WARNING,
    TRANSLATION_LANGUAGES,
    ai_translation_status,
    enqueue_missing_translations,
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
app.state.dashboard_analytics_cache = {"expires_at": 0.0, "payload": None}
app.state.youtube_shorts_cache = {"expires_at": 0.0, "payload": None}
app.state.youtube_shorts_cache_lock = threading.Lock()
scheduler = BackgroundScheduler()
SUPPORTED_LANGUAGES = ["az", "en", "ru", "tr"]
LANGUAGE_LABELS = {"az": "Azerbaijani", "en": "English", "ru": "Russian", "tr": "Turkish"}
LANGUAGE_NEWS_PATHS = {"az": "xeber", "en": "news", "ru": "news", "tr": "haber"}
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
PUBLIC_DISPLAY_TIMEZONE = ZoneInfo("Asia/Baku")
logger = logging.getLogger(__name__)
NEWSLETTER_SUBSCRIPTIONS_FILE = Path(os.getenv("NEWSLETTER_SUBSCRIPTIONS_FILE", "data/newsletter_subscriptions.jsonl"))
NEWSLETTER_LOCK = threading.Lock()
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def ensure_upload_dir() -> None:
    """Create the persistent host upload directory before serving or saving images."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


ensure_upload_dir()
app.mount(UPLOAD_URL_PREFIX, StaticFiles(directory=UPLOAD_DIR), name="uploaded_images")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/assets", StaticFiles(directory="assets"), name="assets")


@app.middleware("http")
async def track_authenticated_admin_traffic(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/admin") and is_authenticated(request) and request.url.path != "/admin/dashboard/analytics":
        db = SessionLocal()
        try:
            country_code, country_name = visitor_country(request)
            db.add(ArticleView(
                article_id=None,
                visitor_key=visitor_fingerprint(request),
                traffic_source="Admin",
                path=str(request.url.path),
                language="admin",
                device_type=visitor_device_type(request),
                country_code=country_code,
                country_name=country_name,
                is_admin_traffic=True,
            ))
            db.commit()
            app.state.dashboard_analytics_cache = {"expires_at": 0.0, "payload": None}
        except Exception:
            db.rollback()
        finally:
            db.close()
    return response


PUBLIC_LABELS = {
    "az": {
        "latest": "Son",
        "latest_news": "Son xəbərlər",
        "most_watched": "Xəbər lenti",
        "most_viewed": "Ən çox oxunanlar",
        "trending_label": "Trenddə",
        "author_label": "Müəllif",
        "source_label": "Mənbə",
        "copy_link": "Linki kopyala",
        "copy_success": "Link kopyalandı",
        "newsletter_label": "Bülleten",
        "newsletter_headline": "Xəbərləri ilk siz alın",
        "newsletter_text": "Ən vacib xəbər və təhlilləri birbaşa e-poçtunuzda oxuyun.",
        "subscribe_label": "Abunə ol",
        "newsletter_success": "Abunəlik uğurla yadda saxlanıldı.",
        "newsletter_invalid": "Zəhmət olmasa düzgün e-poçt ünvanı daxil edin.",
        "newsletter_error": "Abunəlik yadda saxlanılmadı. Yenidən cəhd edin.",
        "date_label": "Tarix",
        "views_label": "Baxış",
        "related": "Oxşar xəbərlər",
        "reading_time_prefix": "Oxuma müddəti",
        "reading_time_minute": "dəqiqə",
        "reader_reaction_title": "Bu xəbər sizə necə təsir etdi?",
        "reaction_interesting": "Maraqlıdır",
        "reaction_important": "Vacibdir",
        "reaction_surprising": "Təəccüblü",
        "reaction_useful": "Faydalıdır",
        "like_label": "Like",
        "dislike_label": "Dislike",
        "comments_label": "Şərhlər",
        "comments_coming_soon": "Şərh sistemi tezliklə aktiv olacaq.",
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
        "load_more": "Daha çox göstər",
    },
    "en": {
        "latest": "Latest",
        "latest_news": "Latest news",
        "most_watched": "News feed",
        "most_viewed": "Most viewed",
        "trending_label": "Trending",
        "author_label": "Author",
        "source_label": "Source",
        "copy_link": "Copy link",
        "copy_success": "Link copied",
        "newsletter_label": "Newsletter",
        "newsletter_headline": "Get breaking news first",
        "newsletter_text": "A premium inbox briefing for the biggest stories, launches and analysis.",
        "subscribe_label": "Subscribe",
        "newsletter_success": "Subscription saved successfully.",
        "newsletter_invalid": "Please enter a valid email address.",
        "newsletter_error": "Subscription could not be saved. Please try again.",
        "date_label": "Date",
        "views_label": "Views",
        "related": "Related articles",
        "reading_time_prefix": "Reading time",
        "reading_time_minute": "min",
        "reader_reaction_title": "How did this news feel?",
        "reaction_interesting": "Maraqlıdır",
        "reaction_important": "Vacibdir",
        "reaction_surprising": "Təəccüblü",
        "reaction_useful": "Faydalıdır",
        "like_label": "Like",
        "dislike_label": "Dislike",
        "comments_label": "Comments",
        "comments_coming_soon": "Comment system will be active soon.",
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
        "load_more": "Load more",
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
}

CATEGORY_LABELS = {
    "az": {"Politics": "Siyasət", "World": "Dünya", "Economy": "İqtisadiyyat", "Technology": "Texnologiya", "Business": "Biznes", "Sports": "İdman", "Health": "Sağlamlıq", "Country": "Ölkə", "Incident": "Hadisə", "Science and Education": "Elm və Təhsil", "Show Business": "Şou Biznes", "Agriculture": "Kənd təsərrüfatı"},
    "en": {"Politics": "Politics", "World": "World", "Economy": "Economy", "Technology": "Technology", "Business": "Business", "Sports": "Sports", "Health": "Health", "Country": "Country", "Incident": "Incident", "Science and Education": "Science & Education", "Show Business": "Show Business", "Agriculture": "Agriculture"},
    "ru": {"Politics": "Политика", "World": "Мир", "Economy": "Экономика", "Technology": "Технологии", "Business": "Бизнес", "Sports": "Спорт", "Health": "Здоровье", "Country": "Страна", "Incident": "Происшествия", "Science and Education": "Наука и образование", "Show Business": "Шоу-бизнес", "Agriculture": "Сельское хозяйство"},
    "tr": {"Politics": "Siyaset", "World": "Dünya", "Economy": "Ekonomi", "Technology": "Teknoloji", "Business": "İş dünyası", "Sports": "Spor", "Health": "Sağlık", "Country": "Ülke", "Incident": "Olay", "Science and Education": "Bilim ve Eğitim", "Show Business": "Şov Biznes", "Agriculture": "Tarım"},
}




PUBLIC_LABELS["az"].update({
    "newsroom_label": "Premium xəbər otağı",
    "language_label": "Dil",
    "open_menu": "Menyunu aç",
    "breaking_news": "Təcili xəbər",
    "editorial_flow": "Canlı redaksiya lenti",
    "sidebar_label": "Xəbər paneli",
    "most_viewed": "Ən çox oxunanlar",
    "trending_label": "Trenddə",
    "sections_label": "Bölmələr",
    "category_blocks_title": "Kateqoriyalar üzrə xəbərlər",
    "view_all": "Hamısına bax",
    "category_empty": "Yeni xəbərlər tezliklə burada görünəcək.",
    "newsletter_label": "Xəbər bülleteni",
    "newsletter_headline": "Xəbərləri ilk siz alın",
    "newsletter_text": "Ən vacib xəbərlər, təhlillər və yeniliklər üçün premium e-poçt bülleteni.",
    "subscribe_label": "Abunə ol",
    "privacy_label": "Məxfilik",
    "sitemap_label": "Sayt xəritəsi",
    "quick_access_title": "Oxucu paneli",
    "quick_access_kicker": "Sürətli giriş",
    "latest_count_label": "Son xəbərlər",
    "today_views_label": "Bugünkü baxış",
    "seo_ready_label": "Google News / SEO hazır",
    "latest_quick_link": "Ən son xəbərlər",
    "newsletter_success": "Abunəliyiniz uğurla qeydə alındı.",
    "newsletter_duplicate": "Bu e-poçt artıq abunədir.",
    "newsletter_invalid": "Düzgün e-poçt ünvanı daxil edin.",
    "newsletter_error": "Abunəliyi saxlamaq mümkün olmadı. Zəhmət olmasa yenidən cəhd edin.",
    "latest_video_label": "Son Shorts",
    "load_more": "Daha çox göstər",
    "news_hub_eyebrow": "Premium xəbər otağı",
    "news_hub_title": "Xəbər Mərkəzi",
    "news_hub_breaking": "Son dəqiqə",
    "news_hub_world": "Dünya",
    "news_hub_economy": "İqtisadiyyat",
    "news_hub_technology": "Texnologiya",
    "news_hub_sports": "İdman",
    "news_hub_empty": "Bu bölmə üçün yeni xəbərlər tezliklə əlavə olunacaq.",
})
PUBLIC_LABELS["en"].update({
    "newsroom_label": "Premium newsroom",
    "language_label": "Language",
    "open_menu": "Open menu",
    "breaking_news": "Breaking news",
    "editorial_flow": "Live editorial flow",
    "sidebar_label": "News sidebar",
    "most_viewed": "Most viewed",
    "trending_label": "Trending",
    "sections_label": "Sections",
    "category_blocks_title": "Explore by category",
    "view_all": "View all",
    "category_empty": "Fresh stories will appear here soon.",
    "newsletter_label": "Newsletter",
    "newsletter_headline": "Get breaking news first",
    "newsletter_text": "A premium inbox briefing for the biggest stories, launches and analysis.",
    "subscribe_label": "Subscribe",
    "privacy_label": "Privacy Policy",
    "sitemap_label": "Sitemap",
    "quick_access_title": "Reader panel",
    "quick_access_kicker": "Quick Access",
    "latest_count_label": "Latest news",
    "today_views_label": "Today views",
    "seo_ready_label": "Google News / SEO ready",
    "latest_quick_link": "Latest news",
    "newsletter_success": "Subscription saved successfully.",
    "newsletter_duplicate": "This email is already subscribed.",
    "newsletter_invalid": "Please enter a valid email address.",
    "newsletter_error": "Subscription could not be saved. Please try again.",
    "latest_video_label": "Latest Shorts",
    "load_more": "Load more",
    "news_hub_eyebrow": "Premium newsroom",
    "news_hub_title": "News Hub",
    "news_hub_breaking": "Breaking",
    "news_hub_world": "World",
    "news_hub_economy": "Economy",
    "news_hub_technology": "Technology",
    "news_hub_sports": "Sports",
    "news_hub_empty": "Fresh stories for this section will appear soon.",
})


PUBLIC_LABELS["az"].update({
    "home": "Ana səhifə",
    "news_feed": "Xəbər lenti",
    "read_more": "Daha ətraflı",
    "privacy_policy": "Məxfilik Siyasəti",
    "terms": "Şərtlər",
    "terms_of_use": "İstifadə Şərtləri",
    "copyright": "Müəllif hüquqları",
    "all_rights_reserved": "Bütün hüquqlar qorunur",
    "about_text_1": "\"vreyc.com\" saytı 2026-cı ilin mayın 31-də fəaliyyətə başlayıb və müstəqil informasiya siyasəti həyata keçirən media qurumudur.",
    "about_text_2": "www.vreyc.com saytında Azərbaycanın ictimai, siyasi, sosial və mədəni həyatında baş verən yeniliklərlə yanaşı, digər Qafqaz ölkələrində və dünyada baş verən maraqlı xəbərlər oxuculara çatdırılır. Saytda müxtəlif sahələri əhatə edən müsahibələr, təhlillər, reportajlar, müəllif yazıları və aktual informasiya materialları yayımlanır.",
    "advertisement": "Reklam",
    "advertisement_slot": "Reklam yeri",
    "switch_dark_mode": "Qaranlıq rejimə keç",
    "social_links": "Sosial linklər və tema dəyişdiricisi",
    "carousel_controls": "slayder idarəetməsi",
    "previous_featured_article": "Əvvəlki əsas xəbər",
    "next_featured_article": "Növbəti əsas xəbər",
    "show_featured_article": "Əsas xəbəri göstər",
    "article_metadata": "Məqalə məlumatları",
    "like_or_dislike": "Bəyən və ya bəyənmə",
    "privacy_label": "Məxfilik Siyasəti",
})
PUBLIC_LABELS["en"].update({
    "home": "Home",
    "news_feed": "News Feed",
    "read_more": "Read More",
    "privacy_policy": "Privacy Policy",
    "terms": "Terms",
    "terms_of_use": "Terms of Use",
    "copyright": "Copyright",
    "all_rights_reserved": "All rights reserved",
    "about_text_1": "VREYC launched on May 31, 2026 as an independent media organization with an independent information policy.",
    "about_text_2": "VREYC delivers updates from Azerbaijan, the Caucasus and the world, including interviews, analysis, reports, opinion pieces and timely news materials.",
    "advertisement": "Advertisement",
    "advertisement_slot": "Advertisement",
    "switch_dark_mode": "Switch to dark mode",
    "social_links": "Social links and theme switcher",
    "carousel_controls": "carousel controls",
    "previous_featured_article": "Previous featured article",
    "next_featured_article": "Next featured article",
    "show_featured_article": "Show featured article",
    "article_metadata": "Article metadata",
    "like_or_dislike": "Like or dislike",
    "privacy_label": "Privacy Policy",
})
PUBLIC_LABELS["ru"].update({
    "home": "Главная",
    "news_feed": "Лента новостей",
    "most_viewed": "Самое читаемое",
    "trending_label": "В тренде",
    "author_label": "Автор",
    "source_label": "Источник",
    "copy_link": "Скопировать ссылку",
    "copy_success": "Ссылка скопирована",
    "newsletter_label": "Рассылка",
    "newsletter_headline": "Получайте главные новости первыми",
    "newsletter_text": "Премиальная email-рассылка с главными новостями, запусками и аналитикой.",
    "subscribe_label": "Подписаться",
    "newsletter_success": "Подписка успешно сохранена.",
    "newsletter_duplicate": "Этот адрес уже подписан.",
    "newsletter_invalid": "Введите корректный адрес электронной почты.",
    "newsletter_error": "Не удалось сохранить подписку. Попробуйте еще раз.",
    "reading_time_prefix": "Время чтения",
    "reading_time_minute": "мин",
    "reader_reaction_title": "Как на вас повлияла эта новость?",
    "reaction_interesting": "Интересно",
    "reaction_important": "Важно",
    "reaction_surprising": "Неожиданно",
    "reaction_useful": "Полезно",
    "like_label": "Нравится",
    "dislike_label": "Не нравится",
    "comments_label": "Комментарии",
    "comments_coming_soon": "Система комментариев скоро будет доступна.",
    "read_more": "Читать далее",
    "contact": "Контакты",
    "about": "О нас",
    "privacy_policy": "Политика конфиденциальности",
    "terms": "Условия",
    "terms_of_use": "Условия использования",
    "copyright": "Авторское право",
    "all_rights_reserved": "Все права защищены",
    "about_text_1": "VREYC начал работу 31 мая 2026 года как независимая медиаплатформа с самостоятельной информационной политикой.",
    "about_text_2": "VREYC публикует новости Азербайджана, Кавказа и мира, а также интервью, аналитику, репортажи, авторские материалы и актуальную информацию.",
    "site_name": "Название",
    "domain_owner": "Владелец домена",
    "mobile_whatsapp": "Мобильный и WhatsApp",
    "founder_ceo": "Основатель и генеральный директор VREYC — Васиф Джабраилли.",
    "language_label": "Язык",
    "open_menu": "Открыть меню",
    "breaking_news": "Срочная новость",
    "editorial_flow": "Живая редакционная лента",
    "sidebar_label": "Новостная панель",
    "sections_label": "Разделы",
    "category_blocks_title": "Новости по категориям",
    "view_all": "Смотреть все",
    "category_empty": "Новые материалы скоро появятся здесь.",
    "privacy_label": "Политика конфиденциальности",
    "sitemap_label": "Карта сайта",
    "latest_video_label": "Последние Shorts",
    "load_more": "Показать еще",
    "advertisement": "Реклама",
    "advertisement_slot": "Место для рекламы",
    "switch_dark_mode": "Переключиться на темный режим",
    "social_links": "Социальные ссылки и переключатель темы",
    "carousel_controls": "управление каруселью",
    "previous_featured_article": "Предыдущая главная статья",
    "next_featured_article": "Следующая главная статья",
    "show_featured_article": "Показать главную статью",
    "article_metadata": "Метаданные статьи",
    "like_or_dislike": "Нравится или не нравится",
})
PUBLIC_LABELS["tr"].update({
    "home": "Ana Sayfa",
    "news_feed": "Haber Akışı",
    "most_viewed": "En çok okunanlar",
    "trending_label": "Trend",
    "author_label": "Yazar",
    "source_label": "Kaynak",
    "copy_link": "Bağlantıyı kopyala",
    "copy_success": "Bağlantı kopyalandı",
    "newsletter_label": "Bülten",
    "newsletter_headline": "Son dakika haberlerini ilk alın",
    "newsletter_text": "En önemli haberler, gelişmeler ve analizler için premium e-posta özeti.",
    "subscribe_label": "Abone ol",
    "newsletter_success": "Abonelik başarıyla kaydedildi.",
    "newsletter_duplicate": "Bu e-posta zaten abone.",
    "newsletter_invalid": "Lütfen geçerli bir e-posta adresi girin.",
    "newsletter_error": "Abonelik kaydedilemedi. Lütfen tekrar deneyin.",
    "reading_time_prefix": "Okuma süresi",
    "reading_time_minute": "dk",
    "reader_reaction_title": "Bu haber sizi nasıl etkiledi?",
    "reaction_interesting": "İlginç",
    "reaction_important": "Önemli",
    "reaction_surprising": "Şaşırtıcı",
    "reaction_useful": "Faydalı",
    "like_label": "Beğen",
    "dislike_label": "Beğenme",
    "comments_label": "Yorumlar",
    "comments_coming_soon": "Yorum sistemi yakında aktif olacak.",
    "read_more": "Devamını Oku",
    "contact": "İletişim",
    "about": "Hakkımızda",
    "privacy_policy": "Gizlilik Politikası",
    "terms": "Şartlar",
    "terms_of_use": "Kullanım Şartları",
    "copyright": "Telif hakkı",
    "all_rights_reserved": "Tüm hakları saklıdır",
    "about_text_1": "VREYC, 31 Mayıs 2026'da bağımsız yayın politikası yürüten bir medya kuruluşu olarak faaliyete başladı.",
    "about_text_2": "VREYC; Azerbaycan, Kafkasya ve dünyadan haberlerin yanı sıra röportajlar, analizler, haber dosyaları, köşe yazıları ve güncel bilgi materyalleri sunar.",
    "site_name": "Ad",
    "domain_owner": "Alan adı sahibi",
    "mobile_whatsapp": "Mobil ve WhatsApp",
    "founder_ceo": "VREYC'in kurucusu ve CEO'su Vasif Jabrayilli'dir.",
    "language_label": "Dil",
    "open_menu": "Menüyü aç",
    "breaking_news": "Son dakika",
    "editorial_flow": "Canlı editoryal akış",
    "sidebar_label": "Haber paneli",
    "sections_label": "Bölümler",
    "category_blocks_title": "Kategoriye göre haberler",
    "view_all": "Tümünü gör",
    "category_empty": "Yeni haberler yakında burada görünecek.",
    "privacy_label": "Gizlilik Politikası",
    "sitemap_label": "Site haritası",
    "latest_video_label": "Son Shorts",
    "load_more": "Daha fazla göster",
    "advertisement": "Reklam",
    "advertisement_slot": "Reklam alanı",
    "switch_dark_mode": "Karanlık moda geç",
    "social_links": "Sosyal bağlantılar ve tema değiştirici",
    "carousel_controls": "karusel kontrolleri",
    "previous_featured_article": "Önceki öne çıkan haber",
    "next_featured_article": "Sonraki öne çıkan haber",
    "show_featured_article": "Öne çıkan haberi göster",
    "article_metadata": "Makale bilgileri",
    "like_or_dislike": "Beğen veya beğenme",
})

CATEGORY_UI_KEYS = {'az': {'politics': 'Siyasət', 'world': 'Dünya', 'economy': 'İqtisadiyyat', 'technology': 'Texnologiya', 'business': 'Biznes', 'sports': 'İdman', 'health': 'Sağlamlıq', 'country': 'Ölkə', 'incident': 'Hadisə', 'science_and_education': 'Elm və Təhsil', 'show_business': 'Şou Biznes', 'agriculture': 'Kənd təsərrüfatı'}, 'en': {'politics': 'Politics', 'world': 'World', 'economy': 'Economy', 'technology': 'Technology', 'business': 'Business', 'sports': 'Sports', 'health': 'Health', 'country': 'Country', 'incident': 'Incident', 'science_and_education': 'Science and Education', 'show_business': 'Show Business', 'agriculture': 'Agriculture'}, 'ru': {'politics': 'Политика', 'world': 'Мир', 'economy': 'Экономика', 'technology': 'Технологии', 'business': 'Бизнес', 'sports': 'Спорт', 'health': 'Здоровье', 'country': 'Страна', 'incident': 'Происшествия', 'science_and_education': 'Наука и образование', 'show_business': 'Шоу-бизнес', 'agriculture': 'Сельское хозяйство'}, 'tr': {'politics': 'Siyaset', 'world': 'Dünya', 'economy': 'Ekonomi', 'technology': 'Teknoloji', 'business': 'İş dünyası', 'sports': 'Spor', 'health': 'Sağlık', 'country': 'Ülke', 'incident': 'Olay', 'science_and_education': 'Bilim ve Eğitim', 'show_business': 'Şov Biznes', 'agriculture': 'Tarım'}}
for _lang, _labels in CATEGORY_UI_KEYS.items():
    PUBLIC_LABELS[_lang].update(_labels)

def t(key: str, lang: str = "az") -> str:
    """Translate a public UI key for the requested language, falling back to Azerbaijani."""
    safe_lang = lang if lang in SUPPORTED_LANGUAGES else "az"
    return PUBLIC_LABELS.get(safe_lang, PUBLIC_LABELS["az"]).get(key, PUBLIC_LABELS["az"].get(key, key))

templates.env.globals["t"] = t

def estimate_reading_time_minutes(content: str | None) -> int:
    """Estimate article reading time using a conservative news-reading pace."""
    text = BeautifulSoup(content or "", "html.parser").get_text(" ")
    word_count = len(re.findall(r"\w+", text, flags=re.UNICODE))
    return max(1, (word_count + 199) // 200)


def public_labels(language: str) -> dict[str, str]:
    labels = dict(PUBLIC_LABELS["az"])
    labels.update(PUBLIC_LABELS.get(language, PUBLIC_LABELS["az"]))
    return labels


def public_category_labels(language: str) -> dict[str, str]:
    labels = dict(CATEGORY_LABELS.get(language, CATEGORY_LABELS["az"]))
    az_labels = CATEGORY_LABELS["az"]
    target_labels = CATEGORY_LABELS.get(language, CATEGORY_LABELS["az"])
    for canonical, az_label in az_labels.items():
        labels.setdefault(az_label, target_labels.get(canonical, az_label))
    return labels

PRIMARY_CATEGORY_NAMES = ["Country", "World", "Economy", "Technology", "Business", "Sports", "Politics", "Incident"]
SECONDARY_CATEGORY_NAMES = ["Health", "Agriculture", "Show Business", "Science and Education"]
CATEGORY_BLOCK_NAMES = ["Country", "World", "Economy", "Technology", "Sports", "Health", "Agriculture", "Business"]
NEWS_HUB_CATEGORY_BLOCKS = [
    {"key": "breaking", "category": None, "label_key": "news_hub_breaking", "fallback": "Son dəqiqə"},
    {"key": "world", "category": "World", "label_key": "news_hub_world", "fallback": "Dünya"},
    {"key": "economy", "category": "Economy", "label_key": "news_hub_economy", "fallback": "İqtisadiyyat"},
    {"key": "technology", "category": "Technology", "label_key": "news_hub_technology", "fallback": "Texnologiya"},
    {"key": "sports", "category": "Sports", "label_key": "news_hub_sports", "fallback": "İdman"},
]

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
    {"name": "Agriculture", "description": "Agriculture, food systems, rural economy and climate-smart farming.", "color": "#65a30d"},
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



YOUTUBE_CHANNEL_URL = "https://www.youtube.com/@vasifreyc"
FEATURED_YOUTUBE_SHORT_ID = settings.youtube_shorts_fallback_video_id.strip() or "LXh-sCJWvkA"
YOUTUBE_SHORTS_PAGE_URL = f"{YOUTUBE_CHANNEL_URL}/shorts"
YOUTUBE_RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
YOUTUBE_API_BASE_URL = "https://www.googleapis.com/youtube/v3"
YOUTUBE_CACHE_TTL_SECONDS = 60 * 30
YOUTUBE_HTTP_TIMEOUT_SECONDS = 4
YOUTUBE_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def youtube_thumbnail_url(video_id: str | None) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else ""


def youtube_watch_url(video_id: str | None, *, short: bool = False) -> str:
    if not video_id:
        return YOUTUBE_CHANNEL_URL
    path = "shorts" if short else "watch"
    return f"https://www.youtube.com/{path}/{video_id}" if short else f"https://www.youtube.com/watch?v={video_id}"


def youtube_embed_url(video_id: str | None, *, short: bool = False) -> str:
    if not video_id:
        return ""
    if short:
        params = f"autoplay=1&mute=1&loop=1&playlist={video_id}&playsinline=1&rel=0"
    else:
        params = "enablejsapi=1&autoplay=1&mute=1&playsinline=1&rel=0&modestbranding=1"
    return f"https://www.youtube.com/embed/{video_id}?{params}"


def youtube_video_payload(video_id: str | None, *, short: bool = False) -> dict[str, str] | None:
    video_id = (video_id or "").strip()
    if not YOUTUBE_VIDEO_ID_RE.fullmatch(video_id):
        return None
    return {
        "video_id": video_id,
        "url": youtube_watch_url(video_id, short=short),
        "embed_url": youtube_embed_url(video_id, short=short),
        "thumbnail": youtube_thumbnail_url(video_id),
        "kind": "short" if short else "video",
    }


def unique_youtube_ids(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if not YOUTUBE_VIDEO_ID_RE.fullmatch(value or "") or value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def parse_youtube_shorts_ids(page_html: str) -> list[str]:
    """Extract Shorts IDs in page order from the Vasif REYC Shorts tab HTML."""
    normalized = (page_html or "").replace("\\/", "/")
    ids = re.findall(r"/shorts/([A-Za-z0-9_-]{11})", normalized)
    return unique_youtube_ids(ids)


def parse_youtube_channel_id(page_html: str) -> str | None:
    normalized = page_html or ""
    for pattern in (r'"channelId":"([A-Za-z0-9_-]+)"', r'"externalId":"([A-Za-z0-9_-]+)"', r'channel_id=([A-Za-z0-9_-]+)'):
        match = re.search(pattern, normalized)
        if match:
            return match.group(1)
    return None


def fetch_youtube_text(url: str) -> str:
    response = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; VREYC-News/1.0; +https://vreyc.com)"},
        timeout=YOUTUBE_HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.text


def fetch_youtube_json(url: str, params: dict[str, str | int]) -> dict:
    response = requests.get(
        url,
        params=params,
        headers={"User-Agent": "VREYC-News/1.0 (+https://vreyc.com)"},
        timeout=YOUTUBE_HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def parse_youtube_duration_seconds(duration: str | None) -> int | None:
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration or "")
    if not match:
        return None
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def youtube_channel_id_from_api() -> str | None:
    api_key = (settings.youtube_api_key or "").strip()
    if not api_key:
        return None
    payload = fetch_youtube_json(
        f"{YOUTUBE_API_BASE_URL}/channels",
        {"key": api_key, "part": "id", "forHandle": "@vasifreyc"},
    )
    for item in payload.get("items", []):
        channel_id = (item.get("id") or "").strip()
        if channel_id:
            return channel_id
    return None


def latest_youtube_short_from_api(channel_id: str | None) -> str | None:
    api_key = (settings.youtube_api_key or "").strip()
    if not api_key:
        return None
    channel_id = channel_id or youtube_channel_id_from_api()
    if not channel_id:
        return None
    search_payload = fetch_youtube_json(
        f"{YOUTUBE_API_BASE_URL}/search",
        {
            "key": api_key,
            "part": "id",
            "channelId": channel_id,
            "maxResults": 10,
            "order": "date",
            "type": "video",
        },
    )
    candidate_ids = unique_youtube_ids([item.get("id", {}).get("videoId", "") for item in search_payload.get("items", [])])
    if not candidate_ids:
        return None
    videos_payload = fetch_youtube_json(
        f"{YOUTUBE_API_BASE_URL}/videos",
        {
            "key": api_key,
            "part": "contentDetails",
            "id": ",".join(candidate_ids),
            "maxResults": 10,
        },
    )
    durations = {
        item.get("id"): parse_youtube_duration_seconds(item.get("contentDetails", {}).get("duration"))
        for item in videos_payload.get("items", [])
    }
    for video_id in candidate_ids:
        duration = durations.get(video_id)
        if duration is not None and duration <= 60:
            return video_id
    return None


def latest_channel_video_ids(channel_id: str | None) -> list[str]:
    if not channel_id:
        return []
    feed_xml = fetch_youtube_text(YOUTUBE_RSS_URL.format(channel_id=channel_id))
    root = ElementTree.fromstring(feed_xml)
    namespaces = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
    video_ids = [
        entry.findtext("yt:videoId", default="", namespaces=namespaces).strip()
        for entry in root.findall("atom:entry", namespaces)
    ]
    return unique_youtube_ids(video_ids)


def latest_channel_video_id(channel_id: str | None) -> str | None:
    video_ids = latest_channel_video_ids(channel_id)
    return video_ids[0] if video_ids else None


def build_youtube_shorts_widget() -> dict[str, object]:
    configured_fallback_id = FEATURED_YOUTUBE_SHORT_ID if YOUTUBE_VIDEO_ID_RE.fullmatch(FEATURED_YOUTUBE_SHORT_ID) else "LXh-sCJWvkA"
    fallback_short = youtube_video_payload(configured_fallback_id, short=True)
    payload: dict[str, object] = {"channel_url": YOUTUBE_CHANNEL_URL, "short": fallback_short, "fallback": fallback_short}
    shorts_ids: list[str] = []
    rss_video_ids: list[str] = []
    channel_id = None
    latest_short_id = None

    try:
        latest_short_id = latest_youtube_short_from_api(channel_id)
    except Exception as exc:
        logger.warning("Could not refresh Vasif REYC latest Shorts through YouTube API: %s", exc)

    try:
        shorts_html = fetch_youtube_text(YOUTUBE_SHORTS_PAGE_URL)
        shorts_ids = parse_youtube_shorts_ids(shorts_html)
        channel_id = parse_youtube_channel_id(shorts_html)
    except Exception as exc:
        logger.warning("Could not refresh Vasif REYC Shorts tab fallback: %s", exc)

    if not latest_short_id:
        try:
            rss_video_ids = latest_channel_video_ids(channel_id)
        except Exception as exc:
            logger.warning("Could not refresh Vasif REYC latest channel RSS fallback: %s", exc)

    if not latest_short_id and rss_video_ids and shorts_ids:
        latest_short_id = next((video_id for video_id in rss_video_ids if video_id in shorts_ids), None)

    if not latest_short_id and shorts_ids:
        latest_short_id = shorts_ids[0]

    if not latest_short_id and rss_video_ids:
        latest_short_id = rss_video_ids[0]

    payload["short"] = youtube_video_payload(latest_short_id, short=True) or fallback_short
    return payload


def latest_youtube_shorts_widget() -> dict[str, object]:
    now = time.monotonic()
    cache = getattr(app.state, "youtube_shorts_cache", {"expires_at": 0.0, "payload": None})
    if cache.get("payload") and float(cache.get("expires_at") or 0) > now:
        return cache["payload"]

    with app.state.youtube_shorts_cache_lock:
        cache = getattr(app.state, "youtube_shorts_cache", {"expires_at": 0.0, "payload": None})
        if cache.get("payload") and float(cache.get("expires_at") or 0) > now:
            return cache["payload"]
        try:
            payload = build_youtube_shorts_widget()
            ttl = YOUTUBE_CACHE_TTL_SECONDS
        except Exception as exc:
            logger.warning("Could not refresh Vasif REYC YouTube Shorts widget: %s", exc)
            fallback_short = youtube_video_payload(FEATURED_YOUTUBE_SHORT_ID, short=True) or youtube_video_payload("LXh-sCJWvkA", short=True)
            payload = cache.get("payload") or {"channel_url": YOUTUBE_CHANNEL_URL, "short": fallback_short, "fallback": fallback_short}
            ttl = 5 * 60
        app.state.youtube_shorts_cache = {"expires_at": time.monotonic() + ttl, "payload": payload}
        return payload


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


AZERBAIJANI_MONTH_NAMES = {
    1: "Yanvar",
    2: "Fevral",
    3: "Mart",
    4: "Aprel",
    5: "May",
    6: "İyun",
    7: "İyul",
    8: "Avqust",
    9: "Sentyabr",
    10: "Oktyabr",
    11: "Noyabr",
    12: "Dekabr",
}


def public_display_datetime(value: datetime | None) -> datetime | None:
    if not value:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(PUBLIC_DISPLAY_TIMEZONE)


def format_published_at(value):
    return value.strftime("%b %d, %Y") if value else ""


def format_public_published_at(value):
    local_value = public_display_datetime(value)
    return local_value.strftime("%b %d, %Y") if local_value else ""


def format_article_meta_datetime(value):
    local_value = public_display_datetime(value)
    if not local_value:
        return ""
    month = AZERBAIJANI_MONTH_NAMES.get(local_value.month, local_value.strftime("%B"))
    return f"{local_value.day:02d} {month} {local_value.year} • {local_value:%H:%M}"


def format_article_publish_time(value):
    local_value = public_display_datetime(value)
    return local_value.strftime("%H:%M") if local_value else ""


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


def media_library_stats(db) -> dict:
    assets = db.query(MediaAsset).all()
    week_start = datetime.utcnow() - timedelta(days=7)
    unused_count = sum(1 for asset in assets if media_usage_count(db, asset) == 0)
    storage_used = sum((asset.size_bytes or 0) for asset in assets)
    images_this_week = sum(1 for asset in assets if asset.created_at and asset.created_at >= week_start)
    return {
        "total_images": len(assets),
        "storage_used": format_bytes(storage_used),
        "images_this_week": images_this_week,
        "unused_images": unused_count,
    }


def media_asset_article_values(asset: MediaAsset) -> set[str]:
    public_path = media_asset_public_path(asset)
    raw_values = [getattr(asset, "path", None), getattr(asset, "url", None)]
    values = {public_path, media_asset_absolute_url(asset)}
    values.update(value for value in raw_values if value)
    values.update(public_image_url(value) for value in raw_values if value)
    return {value for value in values if value}


templates.env.filters["format_published_at"] = format_published_at
templates.env.filters["format_public_published_at"] = format_public_published_at
templates.env.filters["format_article_meta_datetime"] = format_article_meta_datetime
templates.env.filters["format_article_publish_time"] = format_article_publish_time
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
    language = language if language in SUPPORTED_LANGUAGES else "az"
    return f"/{language}/{slug}"


def article_hreflang_links(article: Article) -> dict[str, str]:
    """Build complete alternate-language URLs for every supported article page."""
    return {lang: article_url(lang, localized_slug(article, lang)) for lang in SUPPORTED_LANGUAGES}


def article_has_complete_hreflang(article: Article) -> bool:
    links = article_hreflang_links(article)
    return all((links.get(lang) or "").strip() for lang in SUPPORTED_LANGUAGES)


def public_traffic_filter():
    return or_(ArticleView.is_admin_traffic.is_(False), ArticleView.is_admin_traffic.is_(None))


def admin_traffic_filter():
    return ArticleView.is_admin_traffic.is_(True)


def get_translation(article: Article, language: str):
    """Return the stored translation row for a public language, if one exists.

    Azerbaijani content is stored directly on the Article row. EN/RU/TR
    content is stored in ArticleTranslation rows created by the admin form or
    translation generator.
    """
    normalized_language = (language or "az").lower()
    if normalized_language == "az":
        return article
    for translation in getattr(article, "translations", []) or []:
        if (translation.language or "").lower() == normalized_language:
            if (getattr(translation, "status", None) or "published") == "published":
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
        focus_keywords=localized_value(article, translation, "focus_keywords"),
        google_news_description=localized_value(article, translation, "google_news_description"),
        image_alt_text=localized_value(article, translation, "image_alt_text"),
        reading_time_minutes=localized_value(article, translation, "reading_time_minutes"),
        facebook_share_text=localized_value(article, translation, "facebook_share_text"),
        telegram_share_text=localized_value(article, translation, "telegram_share_text"),
        x_share_text=localized_value(article, translation, "x_share_text"),
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
    language = (language or "").lower()
    for pending in db.new:
        if (
            isinstance(pending, ArticleTranslation)
            and pending.article_id == article.id
            and (pending.language or "").lower() == language
        ):
            return pending
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
        translation = db.query(ArticleTranslation).filter(ArticleTranslation.language == language, ArticleTranslation.slug == slug, ArticleTranslation.status == "published").first()
        if translation:
            article = db.query(Article).options(selectinload(Article.translations)).filter(Article.id == translation.article_id, public_article_visibility_filter()).first()
    if not article and language == "az":
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
        "published_at": public_article_datetime(article),
        "view_count": getattr(article, "real_view_count", 0) or 0,
    }

def real_article_view_count_subquery():
    return (
        select(
            ArticleView.article_id.label("article_id"),
            func.count(ArticleView.id).label("real_view_count"),
        )
        .filter(public_traffic_filter())
        .group_by(ArticleView.article_id)
        .subquery()
    )


def article_view_count_map(db, article_ids: list[int]) -> dict[int, int]:
    if not article_ids:
        return {}
    rows = (
        db.query(ArticleView.article_id, func.count(ArticleView.id))
        .filter(public_traffic_filter(), ArticleView.article_id.in_(article_ids))
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
        "hreflang": article_has_complete_hreflang(article),
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


def google_news_status_from_audit(audit: dict) -> dict:
    checks = audit.get("checks", {})
    required = ["meta_title", "meta_description", "image", "schema", "canonical", "hreflang", "translation"]
    missing = [key for key in required if not checks.get(key)]
    if not missing:
        return {"status": "ready", "label": "Ready", "helper": "All discovery checks passed"}
    if len(missing) <= 2:
        return {"status": "warning", "label": "Warning", "helper": ", ".join(missing).replace("_", " ")}
    return {"status": "error", "label": "Error", "helper": ", ".join(missing[:3]).replace("_", " ")}


def article_language_status(article: Article) -> dict:
    available = [lang for lang in SUPPORTED_LANGUAGES if article_translation_complete(article, lang)]
    return {"available": available, "missing": [lang for lang in SUPPORTED_LANGUAGES if lang not in available], "full": len(available) == len(SUPPORTED_LANGUAGES)}


def article_health_score(audit: dict, google_news_status: dict, language_status: dict) -> int:
    checks = audit.get("checks", {})
    meta_score = round((sum(1 for key in ["meta_title", "meta_description", "canonical", "schema"] if checks.get(key)) / 4) * 100)
    image_score = 100 if checks.get("image") else 0
    translation_score = round((len(language_status.get("available", [])) / max(1, len(SUPPORTED_LANGUAGES))) * 100)
    google_score = 100 if google_news_status.get("status") == "ready" else 70 if google_news_status.get("status") == "warning" else 35
    return round((audit.get("score", 0) * 0.4) + (meta_score * 0.2) + (image_score * 0.15) + (translation_score * 0.15) + (google_score * 0.1))


def admin_article_statistics(db) -> SimpleNamespace:
    total = db.query(Article).count()
    published = db.query(Article).filter(Article.status == "published").count()
    scheduled = db.query(Article).filter(Article.status.in_(SCHEDULED_STATUS_VALUES)).count()
    drafts = db.query(Article).filter(Article.status == "draft").count()
    seo_issues = db.query(Article).filter(or_(Article.seo_title.is_(None), Article.seo_title == "", Article.meta_description.is_(None), Article.meta_description == "", Article.image_url.is_(None), Article.image_url == "", Article.slug.is_(None), Article.slug == "")).count()
    google_news_ready = db.query(Article).filter(Article.seo_title.isnot(None), Article.seo_title != "", Article.meta_description.isnot(None), Article.meta_description != "", Article.image_url.isnot(None), Article.image_url != "", Article.slug.isnot(None), Article.slug != "", Article.published_at.isnot(None)).count()
    return SimpleNamespace(total=total, published=published, scheduled=scheduled, drafts=drafts, seo_issues=seo_issues, google_news_ready=google_news_ready)


def build_organization_schema(settings_map: dict[str, str]) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "Organization",
        "@id": f"{settings.site_url.rstrip('/')}/#organization",
        "name": site_name_from_settings(settings_map),
        "url": f"{settings.site_url.rstrip('/')}/",
        "logo": {
            "@type": "ImageObject",
            "url": public_absolute_url(seo_setting(settings_map, "organization_logo_url", "/assets/vreyc-search-logo.svg")),
            "width": 512,
            "height": 512,
        },
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


COUNTRY_NAMES = {
    "AZ": "Azerbaijan",
    "US": "United States",
    "GB": "United Kingdom",
    "TR": "Turkey",
    "RU": "Russia",
    "DE": "Germany",
    "FR": "France",
    "ES": "Spain",
    "CN": "China",
    "JP": "Japan",
    "KR": "South Korea",
    "IN": "India",
    "PK": "Pakistan",
    "IR": "Iran",
    "SA": "Saudi Arabia",
    "AE": "United Arab Emirates",
    "IL": "Israel",
    "GE": "Georgia",
    "UA": "Ukraine",
    "NL": "Netherlands",
    "SE": "Sweden",
    "NO": "Norway",
    "FI": "Finland",
    "PL": "Poland",
    "IT": "Italy",
    "PT": "Portugal",
    "CA": "Canada",
    "BR": "Brazil",
    "MX": "Mexico",
}
LANGUAGE_COUNTRY_FALLBACKS = {"az": "AZ", "en": "US", "ru": "RU", "tr": "TR"}


def country_flag(country_code: str) -> str:
    code = (country_code or "XX").upper()
    if len(code) != 2 or not code.isalpha() or code == "XX":
        return "🌐"
    return "".join(chr(ord(char) + 127397) for char in code)


def visitor_country(request: Request) -> tuple[str, str]:
    for header in ("cf-ipcountry", "x-vercel-ip-country", "x-country-code", "x-geo-country", "x-appengine-country", "x-client-geo-location"):
        value = (request.headers.get(header) or "").strip().upper()
        if value and value != "XX":
            code = re.sub(r"[^A-Z]", "", value)[:2] or "XX"
            return code, COUNTRY_NAMES.get(code, code)
    country_name = (request.headers.get("x-country-name") or "").strip()
    if country_name:
        for code, name in COUNTRY_NAMES.items():
            if name.lower() == country_name.lower():
                return code, name
    accept_language = (request.headers.get("accept-language") or "").lower()
    locale_match = re.search(r"[-_]([a-z]{2})(?:[;,]|$)", accept_language)
    if locale_match:
        code = locale_match.group(1).upper()
        if code in COUNTRY_NAMES:
            return code, COUNTRY_NAMES[code]
    language_match = re.match(r"([a-z]{2})", accept_language)
    if language_match:
        code = LANGUAGE_COUNTRY_FALLBACKS.get(language_match.group(1))
        if code:
            return code, COUNTRY_NAMES.get(code, code)
    return "XX", "Unknown"


def visitor_device_type(request: Request) -> str:
    user_agent = (request.headers.get("user-agent") or "").lower()
    client_hints_mobile = (request.headers.get("sec-ch-ua-mobile") or "").strip().lower()
    if client_hints_mobile == "?1":
        return "mobile"
    tablet_tokens = ("ipad", "tablet", "kindle", "silk", "playbook", "nexus 7", "nexus 9", "sm-t", "tab ")
    mobile_tokens = ("mobi", "iphone", "ipod", "phone", "blackberry", "opera mini", "windows phone", "android")
    if any(token in user_agent for token in tablet_tokens):
        return "tablet"
    if "android" in user_agent and "mobile" not in user_agent:
        return "tablet"
    if any(token in user_agent for token in mobile_tokens):
        return "mobile"
    return "desktop"


def visitor_fingerprint(request: Request) -> str:
    raw = "|".join([
        get_remote_address(request) or "unknown",
        request.headers.get("user-agent", "unknown"),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def record_article_view(db, article: Article, request: Request, language: str) -> None:
    article.updated_at = article.updated_at or datetime.utcnow()
    country_code, country_name = visitor_country(request)
    db.add(ArticleView(
        article_id=article.id,
        visitor_key=visitor_fingerprint(request),
        traffic_source=classify_traffic_source(request.headers.get("referer"), request),
        path=str(request.url.path),
        language=language,
        device_type=visitor_device_type(request),
        country_code=country_code,
        country_name=country_name,
        is_admin_traffic=False,
    ))
    db.commit()


def analytics_summary(db) -> dict:
    today = utc_start_of_day()
    last_7_days = today - timedelta(days=6)
    last_30_days = today - timedelta(days=29)
    total_views = db.query(func.count(ArticleView.id)).filter(public_traffic_filter()).scalar() or 0
    views_today = db.query(func.count(ArticleView.id)).filter(public_traffic_filter(), ArticleView.viewed_at >= today).scalar() or 0
    views_7 = db.query(func.count(ArticleView.id)).filter(public_traffic_filter(), ArticleView.viewed_at >= last_7_days).scalar() or 0
    views_30 = db.query(func.count(ArticleView.id)).filter(public_traffic_filter(), ArticleView.viewed_at >= last_30_days).scalar() or 0
    unique_visitors = db.query(func.count(func.distinct(ArticleView.visitor_key))).filter(public_traffic_filter(), ArticleView.visitor_key.isnot(None), ArticleView.visitor_key != "").scalar() or 0
    returning_rows = db.query(ArticleView.visitor_key).filter(public_traffic_filter(), ArticleView.visitor_key.isnot(None), ArticleView.visitor_key != "").group_by(ArticleView.visitor_key).having(func.count(ArticleView.id) > 1).all()
    return {
        "total_views": total_views,
        "views_today": views_today,
        "views_7_days": views_7,
        "views_30_days": views_30,
        "unique_visitors": unique_visitors,
        "returning_visitors": len(returning_rows),
        "admin_traffic": db.query(func.count(ArticleView.id)).filter(admin_traffic_filter()).scalar() or 0,
        "public_visitors": unique_visitors,
    }


def percent_rows(rows: list[tuple[str, int]], labels: list[str] | None = None) -> list[dict]:
    counts = {str(name or "unknown").lower(): int(count or 0) for name, count in rows}
    ordered_labels = labels or list(counts.keys())
    total = sum(counts.values()) or 0
    result = []
    for label in ordered_labels:
        value = counts.get(label.lower(), 0)
        result.append({"label": label.title(), "key": label.lower(), "count": value, "percent": round((value / total) * 100) if total else 0})
    return result


def online_visitor_metrics(db) -> dict:
    now = datetime.utcnow()
    windows = {
        "current": now - timedelta(seconds=90),
        "last_5_min": now - timedelta(minutes=5),
        "last_15_min": now - timedelta(minutes=15),
        "last_60_min": now - timedelta(minutes=60),
    }
    metrics = {}
    for key, start in windows.items():
        metrics[key] = db.query(func.count(func.distinct(ArticleView.visitor_key))).filter(
            public_traffic_filter(),
            ArticleView.viewed_at >= start,
            ArticleView.visitor_key.isnot(None),
            ArticleView.visitor_key != "",
        ).scalar() or 0
    return metrics


def device_statistics(db) -> list[dict]:
    rows = db.query(ArticleView.device_type, func.count(ArticleView.id)).filter(public_traffic_filter()).group_by(ArticleView.device_type).all()
    return percent_rows(rows, ["mobile", "desktop", "tablet"])


def top_country_statistics(db, limit: int = 6) -> list[dict]:
    rows = db.query(ArticleView.country_code, ArticleView.country_name, func.count(ArticleView.id)).filter(public_traffic_filter()).group_by(
        ArticleView.country_code,
        ArticleView.country_name,
    ).order_by(func.count(ArticleView.id).desc()).limit(limit).all()
    total = db.query(func.count(ArticleView.id)).filter(public_traffic_filter()).scalar() or 0
    countries = []
    for code, name, count in rows:
        safe_code = (code or "XX").upper()
        safe_name = name or COUNTRY_NAMES.get(safe_code, "Unknown")
        value = int(count or 0)
        countries.append({
            "code": safe_code,
            "flag": country_flag(safe_code),
            "name": safe_name,
            "count": value,
            "percent": round((value / total) * 100) if total else 0,
        })
    return countries


def read_memory_usage_percent() -> int:
    meminfo_path = Path("/proc/meminfo")
    if not meminfo_path.exists():
        return 0
    values = {}
    for line in meminfo_path.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 2:
            values[parts[0].rstrip(":")] = int(parts[1])
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    return round(((total - available) / total) * 100) if total else 0


def server_uptime_label() -> str:
    uptime_path = Path("/proc/uptime")
    if uptime_path.exists():
        seconds = int(float(uptime_path.read_text().split()[0]))
    else:
        seconds = 0
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def vps_health_metrics() -> dict:
    cpu_count = os.cpu_count() or 1
    try:
        load_1m = os.getloadavg()[0]
    except OSError:
        load_1m = 0
    cpu_usage = min(100, round((load_1m / cpu_count) * 100))
    disk_usage = shutil.disk_usage("/")
    disk_percent = round((disk_usage.used / disk_usage.total) * 100) if disk_usage.total else 0
    ram_percent = read_memory_usage_percent()
    worst = max(cpu_usage, ram_percent, disk_percent)
    status = "critical" if worst >= 90 else "warning" if worst >= 75 else "healthy"
    return {
        "cpu_usage": cpu_usage,
        "ram_usage": ram_percent,
        "disk_usage": disk_percent,
        "uptime": server_uptime_label(),
        "status": status,
    }


def dashboard_analytics_payload(db) -> dict:
    public_summary = analytics_summary(db)
    return {
        "online_visitors": online_visitor_metrics(db),
        "vps_health": vps_health_metrics(),
        "device_statistics": device_statistics(db),
        "top_countries": top_country_statistics(db),
        "traffic_quality": {
            "public_views": public_summary["total_views"],
            "public_visitors": public_summary["public_visitors"],
            "admin_traffic": public_summary["admin_traffic"],
        },
        "generated_at": current_server_utc().isoformat(),
    }


def cached_dashboard_analytics(db) -> dict:
    cache = getattr(app.state, "dashboard_analytics_cache", {"expires_at": 0.0, "payload": None})
    now = time.monotonic()
    if cache.get("payload") is not None and cache.get("expires_at", 0) > now:
        return cache["payload"]
    payload = dashboard_analytics_payload(db)
    app.state.dashboard_analytics_cache = {"expires_at": now + 20, "payload": payload}
    return payload

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
    fix_center = seo_fix_center_context(db)
    missing_meta_descriptions = fix_center['missing_meta_descriptions']
    missing_hreflang = fix_center['missing_hreflang']
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
            'total_pages_with_hreflang': fix_center['total_pages_with_hreflang'],
            'total_hreflang_pages': fix_center['total_hreflang_pages'],
            'missing_open_graph': fix_center['missing_open_graph'],
            'missing_canonical': fix_center['missing_canonical'],
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



def generate_article_meta_description(article: Article, language: str = "az") -> str:
    view = localized_article_view(article, language)
    engine = AIEngine()
    return engine.generate_meta_description(
        title=view.title or article.title or "VREYC news update",
        summary=view.summary or "",
        content=view.content or article.content or "",
        language=language,
    )


def fix_missing_meta_descriptions(db) -> int:
    articles = db.query(Article).options(selectinload(Article.translations)).all()
    updated = 0
    for article in articles:
        if not (article.meta_description or "").strip():
            article.meta_description = generate_article_meta_description(article, "az")
            article.updated_at = datetime.utcnow()
            updated += 1
        for translation in getattr(article, "translations", []) or []:
            language = (translation.language or "").lower()
            if language in SUPPORTED_LANGUAGES and not (translation.meta_description or "").strip():
                translation.meta_description = generate_article_meta_description(article, language)
                translation.updated_at = datetime.utcnow()
                updated += 1
    if updated:
        db.commit()
    return updated


def fix_missing_canonical_slugs(db) -> int:
    updated = 0
    articles = db.query(Article).options(selectinload(Article.translations)).all()
    for article in articles:
        if not (article.slug or "").strip():
            article.slug = unique_article_slug(db, article.title or f"article-{article.id}", article.id)
            article.updated_at = datetime.utcnow()
            updated += 1
        for translation in getattr(article, "translations", []) or []:
            if not (translation.slug or "").strip():
                translation.slug = unique_translation_slug(db, translation.language or "az", translation.title or article.title or f"article-{article.id}", translation.id)
                translation.updated_at = datetime.utcnow()
                updated += 1
    if updated:
        db.commit()
    return updated


def seo_fix_center_context(db) -> dict:
    articles = db.query(Article).options(selectinload(Article.translations)).all()
    audits = [article_seo_audit(article, "az") for article in articles]
    total_hreflang_pages = len(articles) * len(SUPPORTED_LANGUAGES)
    pages_with_hreflang = sum(len(article_hreflang_links(article)) for article in articles if article_has_complete_hreflang(article))
    missing_meta_descriptions = sum(1 for article in articles if not (article.meta_description or "").strip())
    missing_meta_descriptions += sum(
        1
        for article in articles
        for translation in getattr(article, "translations", []) or []
        if (translation.language or "").lower() in SUPPORTED_LANGUAGES and not (translation.meta_description or "").strip()
    )
    missing_hreflang = max(total_hreflang_pages - pages_with_hreflang, 0)
    missing_canonical = sum(1 for audit in audits if not audit["checks"].get("canonical"))
    missing_open_graph = sum(1 for audit in audits if not (audit["checks"].get("meta_description") and audit["checks"].get("image")))
    return {
        "total_pages_with_hreflang": pages_with_hreflang,
        "total_hreflang_pages": total_hreflang_pages,
        "missing_meta_descriptions": missing_meta_descriptions,
        "missing_hreflang": missing_hreflang,
        "missing_open_graph": missing_open_graph,
        "missing_canonical": missing_canonical,
    }

def top_category_rows(db, limit: int = 10) -> list[dict]:
    rows = (
        db.query(Article.category, func.count(ArticleView.id))
        .join(ArticleView, ArticleView.article_id == Article.id)
        .filter(public_traffic_filter())
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
    query = db.query(ArticleView).filter(public_traffic_filter(), ArticleView.viewed_at >= start_monthly)
    if article_id is not None:
        query = query.filter(ArticleView.article_id == article_id)
    rows = query.order_by(ArticleView.viewed_at.asc()).all()
    return {
        "daily": period_chart([row for row in rows if row.viewed_at >= start_daily], start_daily, 14, "%b %d"),
        "weekly": weekly_chart([row for row in rows if row.viewed_at >= start_weekly], start_weekly),
        "monthly": monthly_chart(rows),
    }


def article_analytics_context(db, article: Article) -> dict:
    history = db.query(ArticleView).filter(public_traffic_filter(), ArticleView.article_id == article.id).order_by(ArticleView.viewed_at.desc()).limit(100).all()
    sources = db.query(ArticleView.traffic_source, func.count(ArticleView.id)).filter(public_traffic_filter(), ArticleView.article_id == article.id).group_by(ArticleView.traffic_source).order_by(func.count(ArticleView.id).desc()).all()
    publish_start = article.published_at or article.created_at or datetime.utcnow()
    first_24h_end = publish_start + timedelta(days=1)
    first_24h_views = db.query(func.count(ArticleView.id)).filter(public_traffic_filter(), ArticleView.article_id == article.id, ArticleView.viewed_at >= publish_start, ArticleView.viewed_at < first_24h_end).scalar() or 0
    last_7_views = db.query(func.count(ArticleView.id)).filter(public_traffic_filter(), ArticleView.article_id == article.id, ArticleView.viewed_at >= utc_start_of_day() - timedelta(days=6)).scalar() or 0
    unique_visitors = db.query(func.count(func.distinct(ArticleView.visitor_key))).filter(public_traffic_filter(), ArticleView.article_id == article.id, ArticleView.visitor_key.isnot(None), ArticleView.visitor_key != "").scalar() or 0
    return {
        "history": history,
        "sources": [{"name": source or "Direct", "views": int(count or 0)} for source, count in sources],
        "charts": traffic_charts(db, article.id),
        "publish_performance": {
            "total_views": db.query(func.count(ArticleView.id)).filter(public_traffic_filter(), ArticleView.article_id == article.id).scalar() or 0,
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



def article_ai_payload(article: Article) -> dict[str, str]:
    return {
        "title": article.title or "",
        "summary": article.summary or "",
        "content": article.content or "",
        "seo_title": article.seo_title or "",
        "meta_description": article.meta_description or "",
        "focus_keywords": article.focus_keywords or "",
        "google_news_description": article.google_news_description or "",
        "image_alt_text": article.image_alt_text or "",
        "facebook_share_text": article.facebook_share_text or "",
        "telegram_share_text": article.telegram_share_text or "",
        "x_share_text": article.x_share_text or "",
        "tags": article.tags or "",
        "category": article.category or "",
    }


def _ai_runtime_ready(db, feature: str = "seo") -> dict:
    runtime = openai_runtime_settings()
    enabled_key = "translation_enabled" if feature == "translation" else "seo_enabled"
    ready = bool(runtime["configured"] and runtime.get(enabled_key, True))
    if not ready:
        message = f"AI {feature} provider is not configured or {feature} is disabled."
        db.add(FetchLog(level="WARNING", message=message))
        db.commit()
        return {"configured": False, "message": message}
    return {"configured": True, "message": "AI provider ready."}


def apply_ai_seo_pack(db, article: Article) -> dict:
    ready = _ai_runtime_ready(db, "seo")
    if not ready["configured"]:
        return ready
    engine = AIEngine()
    payload = engine.generate_seo_pack(article_ai_payload(article), article.language or "az")
    article.seo_title = payload.get("seo_title") or article.seo_title or article.title
    article.meta_description = payload.get("meta_description") or article.meta_description
    article.focus_keywords = payload.get("focus_keywords") or article.focus_keywords or article.tags
    article.google_news_description = payload.get("google_news_description") or article.google_news_description or article.summary
    article.image_alt_text = payload.get("image_alt_text") or article.image_alt_text or article.title
    article.reading_time_minutes = int(payload.get("reading_time_minutes") or article.reading_time_minutes or 1)
    article.facebook_share_text = payload.get("facebook_share_text") or article.facebook_share_text
    article.telegram_share_text = payload.get("telegram_share_text") or article.telegram_share_text
    article.x_share_text = payload.get("x_share_text") or article.x_share_text
    article.updated_at = datetime.utcnow()
    db.add(FetchLog(level="INFO", message=f"AI SEO generated for article {article.id}."))
    db.commit()
    return {"configured": True, "message": "AI SEO generated."}


def apply_ai_title_rewrite(db, article: Article) -> dict:
    ready = _ai_runtime_ready(db, "seo")
    if not ready["configured"]:
        return ready
    payload = AIEngine().rewrite_title(article_ai_payload(article), article.language or "az")
    article.title = payload.get("title") or article.title
    article.seo_title = payload.get("seo_title") or article.seo_title or article.title
    article.slug = unique_article_slug(db, article.title or f"article-{article.id}", article.id)
    article.updated_at = datetime.utcnow()
    db.add(FetchLog(level="INFO", message=f"AI title rewritten for article {article.id}."))
    db.commit()
    return {"configured": True, "message": "AI title rewritten."}


def apply_ai_article_rewrite(db, article: Article) -> dict:
    ready = _ai_runtime_ready(db, "seo")
    if not ready["configured"]:
        return ready
    payload = AIEngine().rewrite_article(article_ai_payload(article), article.language or "az")
    article.title = payload.get("title") or article.title
    article.summary = payload.get("summary") or article.summary
    article.content = payload.get("content") or article.content
    article.seo_title = payload.get("seo_title") or article.seo_title or article.title
    article.tags = payload.get("tags") or article.tags
    article.category = payload.get("category") or article.category
    article.slug = unique_article_slug(db, article.title or f"article-{article.id}", article.id)
    article.updated_at = datetime.utcnow()
    db.add(FetchLog(level="INFO", message=f"AI article rewritten for article {article.id}."))
    db.commit()
    return {"configured": True, "message": "AI article rewritten."}


def apply_ai_social_pack(db, article: Article) -> dict:
    ready = _ai_runtime_ready(db, "seo")
    if not ready["configured"]:
        return ready
    payload = AIEngine().generate_social_share_pack(article_ai_payload(article), article.language or "az")
    article.facebook_share_text = payload.get("facebook_share_text") or article.facebook_share_text
    article.telegram_share_text = payload.get("telegram_share_text") or article.telegram_share_text
    article.x_share_text = payload.get("x_share_text") or article.x_share_text
    article.updated_at = datetime.utcnow()
    db.add(FetchLog(level="INFO", message=f"AI social share texts generated for article {article.id}."))
    db.commit()
    return {"configured": True, "message": "AI social share texts generated."}


def apply_ai_summary(db, article: Article) -> dict:
    ready = _ai_runtime_ready(db, "seo")
    if not ready["configured"]:
        return ready
    payload = AIEngine().generate_summary(article_ai_payload(article), article.language or "az")
    article.summary = payload.get("summary") or article.summary
    article.updated_at = datetime.utcnow()
    db.add(FetchLog(level="INFO", message=f"AI summary generated for article {article.id}."))
    db.commit()
    return {"configured": True, "message": "AI summary generated."}


def apply_ai_tags(db, article: Article) -> dict:
    ready = _ai_runtime_ready(db, "seo")
    if not ready["configured"]:
        return ready
    payload = AIEngine().generate_tags(article_ai_payload(article), article.language or "az")
    article.tags = payload.get("tags") or article.tags
    article.focus_keywords = article.focus_keywords or article.tags
    article.updated_at = datetime.utcnow()
    db.add(FetchLog(level="INFO", message=f"AI tags generated for article {article.id}."))
    db.commit()
    return {"configured": True, "message": "AI tags generated."}


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
        "ALTER TABLE articles ADD COLUMN focus_keywords VARCHAR(500)",
        "ALTER TABLE articles ADD COLUMN google_news_description TEXT",
        "ALTER TABLE articles ADD COLUMN image_alt_text VARCHAR(500)",
        "ALTER TABLE articles ADD COLUMN reading_time_minutes INTEGER DEFAULT 1",
        "ALTER TABLE articles ADD COLUMN facebook_share_text TEXT",
        "ALTER TABLE articles ADD COLUMN telegram_share_text TEXT",
        "ALTER TABLE articles ADD COLUMN x_share_text TEXT",
        "ALTER TABLE articles ADD COLUMN is_featured BOOLEAN DEFAULT false",
        "ALTER TABLE articles ADD COLUMN is_trending BOOLEAN DEFAULT false",
        "ALTER TABLE articles ADD COLUMN homepage_order INTEGER DEFAULT 100",
        "ALTER TABLE articles ADD COLUMN view_count INTEGER DEFAULT 0",
        f"ALTER TABLE articles ADD COLUMN publish_at {publish_at_type}",
        "ALTER TABLE article_translations ADD COLUMN slug VARCHAR(500)",
        "ALTER TABLE article_translations ADD COLUMN meta_description TEXT",
        "ALTER TABLE article_translations ADD COLUMN focus_keywords VARCHAR(500)",
        "ALTER TABLE article_translations ADD COLUMN google_news_description TEXT",
        "ALTER TABLE article_translations ADD COLUMN image_alt_text VARCHAR(500)",
        "ALTER TABLE article_translations ADD COLUMN reading_time_minutes INTEGER DEFAULT 1",
        "ALTER TABLE article_translations ADD COLUMN facebook_share_text TEXT",
        "ALTER TABLE article_translations ADD COLUMN telegram_share_text TEXT",
        "ALTER TABLE article_translations ADD COLUMN x_share_text TEXT",
        "ALTER TABLE article_translations ADD COLUMN tags VARCHAR(500)",
        "ALTER TABLE article_translations ADD COLUMN status VARCHAR(20) DEFAULT 'published'",
        "ALTER TABLE article_translations ADD COLUMN error_message TEXT",
        "ALTER TABLE media_assets ADD COLUMN url VARCHAR(1000)",
        "ALTER TABLE media_assets ADD COLUMN mime_type VARCHAR(120)",
        "ALTER TABLE media_assets ADD COLUMN width INTEGER",
        "ALTER TABLE media_assets ADD COLUMN height INTEGER",
        "ALTER TABLE article_views ADD COLUMN device_type VARCHAR(40) DEFAULT 'desktop'",
        "ALTER TABLE article_views ADD COLUMN country_code VARCHAR(8) DEFAULT 'XX'",
        "ALTER TABLE article_views ADD COLUMN country_name VARCHAR(120) DEFAULT 'Unknown'",
        "ALTER TABLE article_views ADD COLUMN is_admin_traffic BOOLEAN DEFAULT false",
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
        "CREATE INDEX IF NOT EXISTS ix_article_translations_status ON article_translations (status)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_article_translations_article_language ON article_translations (article_id, language)",
        "CREATE INDEX IF NOT EXISTS ix_article_translations_language_slug ON article_translations (language, slug)",
        "CREATE INDEX IF NOT EXISTS ix_article_views_article_id ON article_views (article_id)",
        "CREATE INDEX IF NOT EXISTS ix_article_views_viewed_at ON article_views (viewed_at)",
        "CREATE INDEX IF NOT EXISTS ix_article_views_visitor_key ON article_views (visitor_key)",
        "CREATE INDEX IF NOT EXISTS ix_article_views_traffic_source ON article_views (traffic_source)",
        "CREATE INDEX IF NOT EXISTS ix_article_views_device_type ON article_views (device_type)",
        "CREATE INDEX IF NOT EXISTS ix_article_views_country_code ON article_views (country_code)",
        "CREATE INDEX IF NOT EXISTS ix_article_views_is_admin_traffic ON article_views (is_admin_traffic)",
        "UPDATE article_translations SET status = 'published' WHERE status IS NULL OR status = ''",
        "DELETE FROM article_translations WHERE lower(language) IN ('es', 'zh')",
        "DELETE FROM article_narrations WHERE lower(language) IN ('es', 'zh')",
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



def today_public_views_count(db) -> int:
    today_start = datetime_for_database(current_server_utc().replace(hour=0, minute=0, second=0, microsecond=0))
    return db.query(ArticleView).filter(ArticleView.viewed_at >= today_start, ArticleView.is_admin_traffic.is_(False)).count()


def read_newsletter_emails() -> set[str]:
    if not NEWSLETTER_SUBSCRIPTIONS_FILE.exists():
        return set()
    emails: set[str] = set()
    for line in NEWSLETTER_SUBSCRIPTIONS_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        email = str(payload.get("email", "")).strip().lower()
        if email:
            emails.add(email)
    return emails


@app.post("/{language}/newsletter/subscribe")
def newsletter_subscribe(request: Request, language: str, email: str = Form("")):
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(404)
    labels = public_labels(language)
    normalized_email = (email or "").strip().lower()
    if not EMAIL_PATTERN.fullmatch(normalized_email):
        return JSONResponse({"ok": False, "message": labels.get("newsletter_invalid", "Please enter a valid email address.")}, status_code=400)

    with NEWSLETTER_LOCK:
        NEWSLETTER_SUBSCRIPTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        if normalized_email in read_newsletter_emails():
            return JSONResponse({"ok": False, "message": labels.get("newsletter_duplicate", "This email is already subscribed.")}, status_code=409)
        payload = {
            "email": normalized_email,
            "language": language,
            "created_at": current_server_utc().isoformat(),
            "source": str(request.url.path),
        }
        with NEWSLETTER_SUBSCRIPTIONS_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    return {"ok": True, "message": labels.get("newsletter_success", "Subscription saved successfully.")}


@app.get("/", response_class=HTMLResponse)
@app.get("/{language}/", response_class=HTMLResponse)
def home(request: Request, language: str = "az", q: str = "", category: str = "", db=Depends(get_db)):
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(404)
    publish_due_scheduled_articles(db)
    ensure_categories(db)
    query = db.query(Article).options(selectinload(Article.translations)).filter(public_article_visibility_filter())
    if language != "az":
        translated_ids = db.query(ArticleTranslation.article_id).filter(ArticleTranslation.language == language, ArticleTranslation.status == "published")
        query = query.filter(Article.id.in_(translated_ids.scalar_subquery()))
    if q:
        translation_matches = db.query(ArticleTranslation.article_id).filter(
            ArticleTranslation.language == language,
            (ArticleTranslation.title.ilike(f"%{q}%")) | (ArticleTranslation.summary.ilike(f"%{q}%")),
        )
        query = query.filter((Article.title.ilike(f"%{q}%")) | (Article.summary.ilike(f"%{q}%")) | (Article.id.in_(translation_matches.scalar_subquery())))
    if category:
        query = query.filter(Article.category == category)
    articles = attach_real_view_counts(
        db,
        query.order_by(Article.is_featured.desc(), Article.homepage_order.asc(), public_article_datetime_expression().desc(), Article.created_at.desc(), Article.id.desc()).limit(30).all(),
    )
    category_labels = public_category_labels(language)
    article_cards = [article_card(a, language, category_labels) for a in articles]
    latest_slide_articles = attach_real_view_counts(
        db,
        query.order_by(public_article_datetime_expression().desc(), Article.created_at.desc(), Article.id.desc()).limit(5).all(),
    )
    hero_slides = [article_card(a, language, category_labels) for a in latest_slide_articles]
    latest_feed_articles = attach_real_view_counts(
        db,
        query.order_by(public_article_datetime_expression().desc(), Article.created_at.desc(), Article.id.desc()).limit(30).all(),
    )
    latest_cards = [article_card(a, language, category_labels) for a in latest_feed_articles]
    hero = hero_slides[0] if hero_slides else (latest_cards[0] if latest_cards else (article_cards[0] if article_cards else None))
    sidebar_query = db.query(Article).options(selectinload(Article.translations)).filter(public_article_visibility_filter())
    sidebar_articles = attach_real_view_counts(db, sidebar_query.order_by(public_article_datetime_expression().desc(), Article.created_at.desc(), Article.id.desc()).limit(30).all())
    sidebar_cards = [article_card(a, language, category_labels) for a in sidebar_articles]
    trending_articles = attach_real_view_counts(
        db,
        sidebar_query.order_by(Article.is_trending.desc(), public_article_datetime_expression().desc(), Article.created_at.desc(), Article.id.desc()).limit(6).all(),
    )
    trending_cards = [article_card(a, language, category_labels) for a in trending_articles]
    view_candidates = attach_real_view_counts(
        db,
        db.query(Article).options(selectinload(Article.translations)).filter(public_article_visibility_filter()).order_by(Article.view_count.desc(), public_article_datetime_expression().desc(), Article.id.desc()).limit(40).all(),
    )
    most_viewed_cards = [article_card(a, language, category_labels) for a in sorted(view_candidates, key=lambda item: (getattr(item, "real_view_count", 0) or item.view_count or 0, public_article_datetime(item) or datetime.min), reverse=True)[:6]]
    latest_news_count = db.query(Article).filter(public_article_visibility_filter()).count()
    today_views = today_public_views_count(db)
    breaking_cards = (trending_cards or latest_cards or article_cards)[:6]
    categories = public_category_navigation(db)
    category_color_map = {c.name: (c.color or "#48a6ff") for c in [*categories["primary"], *categories["secondary"]]}
    category_blocks = []
    for category_name in CATEGORY_BLOCK_NAMES:
        block_articles = attach_real_view_counts(
            db,
            db.query(Article).options(selectinload(Article.translations)).filter(public_article_visibility_filter(), Article.category == category_name).order_by(public_article_datetime_expression().desc(), Article.created_at.desc(), Article.id.desc()).limit(3).all(),
        )
        category_blocks.append({
            "name": category_name,
            "label": category_labels.get(category_name, category_name),
            "color": category_color_map.get(category_name, "#48a6ff"),
            "articles": [article_card(a, language, category_labels) for a in block_articles],
        })
    alt_links = {lang: f"/{lang}/" for lang in SUPPORTED_LANGUAGES}
    settings_map = get_settings_map(db)
    youtube_widget = latest_youtube_shorts_widget()
    canonical = canonical_url(request, f'{language}/')
    schema_graph = [
        build_organization_schema(settings_map),
        build_website_schema(settings_map, language),
        build_breadcrumb_schema([("Home", canonical)]),
    ]
    return templates.TemplateResponse("public/home.html", {"request": request, "articles": article_cards, "latest_articles": latest_cards, "sidebar_articles": sidebar_cards, "trending_articles": trending_cards, "most_viewed_articles": most_viewed_cards, "breaking_articles": breaking_cards, "hero_slides": hero_slides, "latest_news_count": latest_news_count, "today_views": today_views, "category_blocks": category_blocks, "hero": hero, "categories": categories["primary"], "secondary_categories": categories["secondary"], "q": q, "category": category, "site_url": settings.site_url, "canonical": canonical, "language": language, "languages": SUPPORTED_LANGUAGES, "alt_links": alt_links, "ui": public_labels(language), "category_labels": category_labels, "settings_map": settings_map, "verification_meta": seo_verification_meta(settings_map), "schema_graph": schema_graph, "site_name": site_name_from_settings(settings_map), "youtube_widget": youtube_widget, "app_version": APP_VERSION})


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
    alt_links = article_hreflang_links(article)
    related = db.query(Article).options(selectinload(Article.translations)).filter(public_article_visibility_filter(), Article.id != article.id, Article.category == article.category).order_by(public_article_datetime_expression().desc(), Article.created_at.desc()).limit(4).all()
    if len(related) < 4:
        related = related + db.query(Article).options(selectinload(Article.translations)).filter(public_article_visibility_filter(), Article.id != article.id, Article.category != article.category).order_by(public_article_datetime_expression().desc(), Article.created_at.desc()).limit(4 - len(related)).all()
    related = attach_real_view_counts(db, related)
    sidebar_base = db.query(Article).options(selectinload(Article.translations)).filter(public_article_visibility_filter(), Article.id != article.id)
    trending_articles = attach_real_view_counts(
        db,
        sidebar_base.order_by(Article.is_trending.desc(), public_article_datetime_expression().desc(), Article.created_at.desc(), Article.id.desc()).limit(5).all(),
    )
    view_candidates = attach_real_view_counts(
        db,
        db.query(Article).options(selectinload(Article.translations)).filter(public_article_visibility_filter(), Article.id != article.id).order_by(Article.view_count.desc(), public_article_datetime_expression().desc(), Article.id.desc()).limit(30).all(),
    )
    most_viewed_articles = sorted(
        view_candidates,
        key=lambda item: (getattr(item, "real_view_count", 0) or item.view_count or 0, public_article_datetime(item) or datetime.min),
        reverse=True,
    )[:5]
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
    article_published_at = public_article_datetime(article)
    reading_time_minutes = estimate_reading_time_minutes(view.content)
    return templates.TemplateResponse("public/article.html", {"request": request, "article": view, "root_article": article, "article_published_at": article_published_at, "reading_time_minutes": reading_time_minutes, "image_exists": image_exists, "narration": narration, "related_articles": [article_card(a, language, category_labels) for a in related], "trending_articles": [article_card(a, language, category_labels) for a in trending_articles], "most_viewed_articles": [article_card(a, language, category_labels) for a in most_viewed_articles], "categories": navigation["primary"], "secondary_categories": navigation["secondary"], "share_url": canonical, "site_url": settings.site_url, "canonical": canonical, "language": language, "languages": SUPPORTED_LANGUAGES, "alt_links": alt_links, "ui": public_labels(language), "category_labels": category_labels, "settings_map": settings_map, "verification_meta": seo_verification_meta(settings_map), "schema_graph": schema_graph, "seo_audit": seo_audit, "site_name": site_name_from_settings(settings_map), "og_image": image_url, "app_version": APP_VERSION})


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


@app.get('/admin/dashboard/analytics')
def admin_dashboard_analytics(db=Depends(get_db), _=Depends(require_auth)):
    return JSONResponse(cached_dashboard_analytics(db))


@app.post('/admin/seo/generate-missing-meta-descriptions')
def admin_generate_missing_meta_descriptions(db=Depends(get_db), _=Depends(require_auth)):
    updated = fix_missing_meta_descriptions(db)
    app.state.dashboard_analytics_cache = {"expires_at": 0.0, "payload": None}
    return RedirectResponse(f'/admin?meta_descriptions_generated={updated}', status_code=302)


@app.post('/admin/seo/fix-canonical-urls')
def admin_fix_canonical_urls(db=Depends(get_db), _=Depends(require_auth)):
    updated = fix_missing_canonical_slugs(db)
    return RedirectResponse(f'/admin?canonical_fixed={updated}', status_code=302)


@app.post('/admin/seo/generate-hreflang-translations')
def admin_generate_hreflang_translations(db=Depends(get_db), _=Depends(require_auth)):
    if not is_ai_translation_configured():
        return RedirectResponse('/admin?warning=ai_not_configured', status_code=302)
    result = generate_all_missing_translations()
    return RedirectResponse(f'/admin?hreflang_translations_generated={result.get("generated", 0)}', status_code=302)


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
        .filter(public_traffic_filter())
        .group_by(Article.id)
        .order_by(func.count(ArticleView.id).desc(), Article.published_at.desc(), Article.created_at.desc(), Article.id.desc())
        .limit(10)
        .all()
    )
    most_viewed_articles = [setattr(article, "real_view_count", int(real_view_count or 0)) or article for article, real_view_count in most_viewed_articles]
    analytics = analytics_summary(db)
    dashboard_status = dashboard_status_context(db, total_articles, published, drafts, scheduled)
    return templates.TemplateResponse('admin/dashboard.html', {'request': request, 'drafts': drafts, 'published': published, 'scheduled': scheduled, 'next_scheduled_article': next_scheduled_article, 'total_articles': total_articles, 'categories': categories, 'media_count': media_count, 'logs': logs, 'recent_articles': latest_articles, 'latest_articles': latest_articles, 'most_viewed_articles': most_viewed_articles, 'analytics': analytics, 'dashboard_status': dashboard_status, 'top_categories': top_category_rows(db), 'traffic_charts': traffic_charts(db), "languages": SUPPORTED_LANGUAGES, "ai_translation_status": ai_translation_status()})


@app.get('/admin/ai-center', response_class=HTMLResponse)
def admin_ai_center(request: Request, db=Depends(get_db), _=Depends(require_auth)):
    source_drafts = db.query(Article).filter(Article.status == 'draft', Article.source_url.isnot(None)).count()
    waiting_review = db.query(Article).filter(Article.status == 'draft').count()
    failed_tasks = db.query(FetchLog).filter(FetchLog.level == "ERROR", FetchLog.message.ilike("%AI%")).count()
    translated_count = db.query(ArticleTranslation).filter(ArticleTranslation.status.in_(["draft", "published"])).count()
    seo_generated_count = db.query(Article).filter(Article.focus_keywords.isnot(None), Article.focus_keywords != "").count()
    recent_ai_logs = db.query(FetchLog).filter(FetchLog.message.ilike("%AI%") | FetchLog.message.ilike("%translation%") | FetchLog.message.ilike("%SEO%")).order_by(FetchLog.created_at.desc()).limit(8).all()
    recent_ai_errors = db.query(FetchLog).filter(FetchLog.level == "ERROR", (FetchLog.message.ilike("%AI%") | FetchLog.message.ilike("%translation%") | FetchLog.message.ilike("%SEO%"))).order_by(FetchLog.created_at.desc()).limit(5).all()
    runtime = openai_runtime_settings()
    ai_action_articles = db.query(Article).order_by(Article.updated_at.desc(), Article.created_at.desc()).limit(50).all()
    ai_center_stats = {
        "ai_configured": runtime["configured"],
        "api_status": "Active" if runtime["configured"] else "Not configured",
        "translated_count": translated_count,
        "seo_generated_count": seo_generated_count,
        "drafts_generated": source_drafts,
        "waiting_review": waiting_review,
        "published_by_ai": 0,
        "failed_tasks": failed_tasks,
    }
    workflow_steps = [
        "Check news sources",
        "Translate the article",
        "Customize the text",
        "Prepare SEO title",
        "Suggest an image",
        "Add to draft",
        "Wait for editor approval",
    ]
    source_placeholders = [
        {"label": "Open RSS feed", "icon": "RSS", "href": "/rss.xml"},
        {"label": "Create web article", "icon": "WWW", "href": "/admin/articles/new"},
        {"label": "Configure YouTube", "icon": "YT", "href": "/admin/settings"},
        {"label": "Configure Telegram", "icon": "TG", "href": "/admin/settings"},
    ]
    tool_placeholders = [
        {"label": "Rewrite article", "icon": "RW"},
        {"label": "Translate article", "icon": "TR"},
        {"label": "Generate SEO meta", "icon": "SEO"},
        {"label": "Generate social post", "icon": "SOC"},
        {"label": "Suggest image prompt", "icon": "IMG"},
    ]
    return templates.TemplateResponse('admin/ai_center.html', {
        'request': request,
        'ai_center_stats': ai_center_stats,
        'workflow_steps': workflow_steps,
        'source_placeholders': source_placeholders,
        'tool_placeholders': tool_placeholders,
        'recent_ai_logs': recent_ai_logs,
        'recent_ai_errors': recent_ai_errors,
        'ai_action_articles': ai_action_articles,
    })




@app.post('/admin/ai-center/run')
async def admin_ai_center_run(request: Request, db=Depends(get_db), _=Depends(require_auth)):
    form = await request.form()
    action = (form.get('ai_action') or '').strip()
    article_id = form.get('article_id')
    article = db.query(Article).get(int(article_id)) if str(article_id).isdigit() else None
    if not article:
        return RedirectResponse('/admin/ai-center?error=missing_article', status_code=302)
    if action == 'translate':
        if not is_ai_translation_configured():
            db.add(FetchLog(level="WARNING", message=AI_TRANSLATION_WARNING))
            db.commit()
            return RedirectResponse('/admin/ai-center?warning=ai_not_configured', status_code=302)
        scheduler.add_job(generate_missing_translations, args=[article.id], id=f"ai_center_translation_{article.id}_{datetime.utcnow().timestamp()}", replace_existing=False)
        return RedirectResponse('/admin/ai-center?queued=translation', status_code=302)
    action_map = {
        'rewrite_article': apply_ai_article_rewrite,
        'rewrite_title': apply_ai_title_rewrite,
        'generate_seo': apply_ai_seo_pack,
        'generate_social': apply_ai_social_pack,
        'generate_summary': apply_ai_summary,
        'generate_tags': apply_ai_tags,
    }
    handler = action_map.get(action)
    if not handler:
        return RedirectResponse('/admin/ai-center?error=bad_action', status_code=302)
    result = handler(db, article)
    status = 'done' if result.get('configured') else 'ai_not_configured'
    return RedirectResponse(f'/admin/ai-center?action={action}&status={status}', status_code=302)


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
    translation_rows_map = {
        a.id: {(row.language or "").lower(): row for row in getattr(a, "translations", []) or [] if (row.language or "").lower() in TRANSLATION_LANGUAGES}
        for a in articles
    }
    article_image_urls = [public_image_url(a.image_url) for a in articles if public_image_url(a.image_url)]
    media_alt_map = {
        public_image_url(asset.url or asset.path): asset.alt_text
        for asset in db.query(MediaAsset).filter(or_(MediaAsset.url.in_(article_image_urls or [""]), MediaAsset.path.in_(article_image_urls or [""]))).all()
    }
    seo_audit_map = {a.id: article_seo_audit(a, 'az') for a in articles}
    seo_score_map = {article_id: audit['score'] for article_id, audit in seo_audit_map.items()}
    google_news_map = {article_id: google_news_status_from_audit(audit) for article_id, audit in seo_audit_map.items()}
    language_status_map = {article.id: article_language_status(article) for article in articles}
    health_score_map = {article.id: article_health_score(seo_audit_map.get(article.id, {}), google_news_map.get(article.id, {}), language_status_map.get(article.id, {})) for article in articles}
    seo_detail_map = {}
    for article in articles:
        audit = seo_audit_map.get(article.id, {})
        checks = audit.get('checks', {})
        view = localized_article_view(article, 'az')
        image_public_url = public_image_url(article.image_url)
        seo_detail_map[article.id] = {
            "meta_title": {"ok": checks.get("meta_title", False), "value": view.seo_title or ""},
            "meta_description": {"ok": checks.get("meta_description", False), "value": view.meta_description or ""},
            "image_alt": {"ok": bool(media_alt_map.get(image_public_url)), "value": media_alt_map.get(image_public_url) or ""},
            "canonical": {"ok": checks.get("canonical", False), "value": article_url('az', view.slug) if view.slug else ""},
            "schema": {"ok": checks.get("schema", False), "value": "Ready" if checks.get("schema", False) else "Needs published date, title and image"},
            "hreflang": {"ok": checks.get("hreflang", False), "value": ", ".join(SUPPORTED_LANGUAGES)},
        }
    categories = admin_article_categories(db)
    filters = {"q": q, "status": status, "category": category, "language": language, "date_from": date_from, "date_to": date_to, "sort": sort, "page": page, "per_page": per_page}
    return templates.TemplateResponse("admin/articles.html", {"request": request, "articles": articles, "status": status, "narration_map": narration_map, "translation_missing_map": translation_missing_map, "seo_score_map": seo_score_map, "seo_detail_map": seo_detail_map, "google_news_map": google_news_map, "health_score_map": health_score_map, "language_status_map": language_status_map, "admin_article_stats": admin_article_statistics(db), "languages": SUPPORTED_LANGUAGES, "language_labels": LANGUAGE_LABELS, "categories": categories, "filters": filters, "total": total, "total_pages": total_pages, "page": page, "per_page": per_page, "ai_translation_status": ai_translation_status()})



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
    elif action.startswith('ai_'):
        if not is_ai_translation_configured():
            db.add(FetchLog(level="WARNING", message=AI_TRANSLATION_WARNING))
            db.commit()
            return RedirectResponse(f"{redirect_url}{'&' if '?' in redirect_url else '?'}warning=ai_not_configured", status_code=302)
        for article in articles:
            if action == 'ai_translate_missing':
                scheduler.add_job(generate_missing_translations, args=[article.id], id=f"bulk_article_translation_{article.id}_{datetime.utcnow().timestamp()}", replace_existing=False)
            elif action in {'ai_generate_meta', 'ai_fix_seo'}:
                apply_ai_seo_pack(db, article)
            elif action == 'ai_generate_tags':
                apply_ai_tags(db, article)
            elif action == 'ai_generate_summary':
                apply_ai_summary(db, article)
            elif action == 'ai_rewrite_title':
                apply_ai_title_rewrite(db, article)
            elif action == 'ai_generate_social':
                apply_ai_social_pack(db, article)
            else:
                db.add(FetchLog(level="INFO", message=f"AI bulk action {action} requested for article {article.id}."))
    db.commit()
    if action.startswith('ai_'):
        return RedirectResponse(f"{redirect_url}{'&' if '?' in redirect_url else '?'}ai_action={action}", status_code=302)
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
        focus_keywords=form.get('focus_keywords_az', ''),
        google_news_description=form.get('google_news_description_az', ''),
        image_alt_text=form.get('image_alt_text_az', '') or form.get('hero_alt_text', ''),
        reading_time_minutes=int(form.get('reading_time_minutes_az') or 1),
        facebook_share_text=form.get('facebook_share_text_az', ''),
        telegram_share_text=form.get('telegram_share_text_az', ''),
        x_share_text=form.get('x_share_text_az', ''),
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
        if any(form.get(f'{field}_{lang}', '') for field in ['title', 'summary', 'content', 'seo_title', 'meta_description', 'focus_keywords', 'google_news_description', 'image_alt_text', 'facebook_share_text', 'telegram_share_text', 'x_share_text', 'tags', 'slug']):
            row = get_or_create_translation(db, article, lang)
            row.title = form.get(f'title_{lang}', '')
            row.slug = unique_translation_slug(db, lang, form.get(f'slug_{lang}') or row.slug or row.title or f'{article.slug}-{lang}', row.id)
            row.summary = form.get(f'summary_{lang}', '')
            row.content = sanitize_article_html(form.get(f'content_{lang}', ''))
            row.seo_title = form.get(f'seo_title_{lang}', '')
            row.meta_description = form.get(f'meta_description_{lang}', '')
            row.focus_keywords = form.get(f'focus_keywords_{lang}', '')
            row.google_news_description = form.get(f'google_news_description_{lang}', '')
            row.image_alt_text = form.get(f'image_alt_text_{lang}', '')
            row.reading_time_minutes = int(form.get(f'reading_time_minutes_{lang}') or 1)
            row.facebook_share_text = form.get(f'facebook_share_text_{lang}', '')
            row.telegram_share_text = form.get(f'telegram_share_text_{lang}', '')
            row.x_share_text = form.get(f'x_share_text_{lang}', '')
            row.tags = form.get(f'tags_{lang}', '')
            row.status = form.get(f'translation_status_{lang}') or 'published'
    db.flush()
    if article.status == 'published':
        touch_sitemap_refresh(db)
    if article.status == 'published':
        enqueue_missing_translations(db, article)
    db.commit()
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
        enqueue_missing_translations(db, a)
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
    a.focus_keywords = form.get('focus_keywords_az', '')
    a.google_news_description = form.get('google_news_description_az', '')
    a.image_alt_text = form.get('image_alt_text_az', '') or form.get('hero_alt_text', '')
    a.reading_time_minutes = int(form.get('reading_time_minutes_az') or 1)
    a.facebook_share_text = form.get('facebook_share_text_az', '')
    a.telegram_share_text = form.get('telegram_share_text_az', '')
    a.x_share_text = form.get('x_share_text_az', '')
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
        has_content = any(form.get(f'{field}_{lang}', '') for field in ['title', 'summary', 'content', 'seo_title', 'meta_description', 'focus_keywords', 'google_news_description', 'image_alt_text', 'facebook_share_text', 'telegram_share_text', 'x_share_text', 'tags', 'slug'])
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
        row.focus_keywords = form.get(f'focus_keywords_{lang}', '')
        row.google_news_description = form.get(f'google_news_description_{lang}', '')
        row.image_alt_text = form.get(f'image_alt_text_{lang}', '')
        row.reading_time_minutes = int(form.get(f'reading_time_minutes_{lang}') or 1)
        row.facebook_share_text = form.get(f'facebook_share_text_{lang}', '')
        row.telegram_share_text = form.get(f'telegram_share_text_{lang}', '')
        row.x_share_text = form.get(f'x_share_text_{lang}', '')
        row.tags = form.get(f'tags_{lang}', '')
        row.status = form.get(f'translation_status_{lang}') or row.status or 'published'
        row.updated_at = datetime.utcnow()
    if a.status == 'published':
        touch_sitemap_refresh(db)
    if a.status == 'published':
        enqueue_missing_translations(db, a)
    db.commit()
    return RedirectResponse(f'/admin/articles/{a.id}/edit?saved=1&translations=queued', status_code=302)


@app.post('/admin/articles/{article_id}/seo/generate')
def admin_generate_article_seo(article_id: int, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    article = db.query(Article).get(article_id)
    if not article:
        return RedirectResponse('/admin/articles', status_code=302)
    result = apply_ai_seo_pack(db, article)
    status = 'generated' if result.get('configured') else 'ai_not_configured'
    return RedirectResponse(f'/admin/articles/{article_id}/edit?seo={status}', status_code=302)




@app.post('/admin/articles/{article_id}/ai/{action}')
def admin_article_ai_action(article_id: int, action: str, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    article = db.query(Article).get(article_id)
    if not article:
        return RedirectResponse('/admin/articles', status_code=302)
    if action == 'translate':
        if not is_ai_translation_configured():
            db.add(FetchLog(level="WARNING", message=AI_TRANSLATION_WARNING))
            db.commit()
            return RedirectResponse(f'/admin/articles/{article_id}/edit?warning=ai_not_configured', status_code=302)
        scheduler.add_job(generate_missing_translations, args=[article.id], id=f"article_ai_translation_{article.id}_{datetime.utcnow().timestamp()}", replace_existing=False)
        return RedirectResponse(f'/admin/articles/{article_id}/edit?translations=queued', status_code=302)
    action_map = {
        'rewrite': apply_ai_article_rewrite,
        'rewrite-title': apply_ai_title_rewrite,
        'seo': apply_ai_seo_pack,
        'social': apply_ai_social_pack,
        'summary': apply_ai_summary,
        'tags': apply_ai_tags,
    }
    handler = action_map.get(action)
    if not handler:
        return RedirectResponse(f'/admin/articles/{article_id}/edit?ai=bad_action', status_code=302)
    result = handler(db, article)
    status = 'generated' if result.get('configured') else 'ai_not_configured'
    return RedirectResponse(f'/admin/articles/{article_id}/edit?ai={action}&status={status}', status_code=302)


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


@app.post('/admin/articles/{article_id}/duplicate')
def duplicate_article(article_id: int, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    source = db.query(Article).options(selectinload(Article.translations)).filter(Article.id == article_id).first()
    if not source:
        return RedirectResponse('/admin/articles', status_code=302)
    now = datetime.utcnow()
    duplicate = Article(
        original_hash=f"duplicate-{source.id}-{uuid4()}",
        source_title=source.source_title,
        source_url=source.source_url,
        title=f"{source.title or 'Untitled'} Copy",
        slug=unique_article_slug(db, f"{source.slug or source.title or 'article'}-copy"),
        summary=source.summary,
        content=source.content,
        seo_title=source.seo_title,
        meta_description=source.meta_description,
        focus_keywords=source.focus_keywords,
        google_news_description=source.google_news_description,
        image_alt_text=source.image_alt_text,
        reading_time_minutes=source.reading_time_minutes,
        facebook_share_text=source.facebook_share_text,
        telegram_share_text=source.telegram_share_text,
        x_share_text=source.x_share_text,
        tags=source.tags,
        category=source.category,
        image_url=source.image_url,
        language=source.language,
        status='draft',
        narration_enabled=source.narration_enabled,
        is_featured=False,
        is_trending=False,
        homepage_order=100,
        publish_at=None,
        published_at=None,
        created_at=now,
        updated_at=now,
    )
    db.add(duplicate)
    db.flush()
    for translation in source.translations:
        db.add(ArticleTranslation(
            article_id=duplicate.id,
            language=translation.language,
            title=f"{translation.title or source.title or 'Untitled'} Copy",
            slug=unique_translation_slug(db, translation.language, f"{translation.slug or translation.title or source.slug or 'article'}-copy"),
            summary=translation.summary,
            content=translation.content,
            seo_title=translation.seo_title,
            meta_description=translation.meta_description,
            focus_keywords=translation.focus_keywords,
            google_news_description=translation.google_news_description,
            image_alt_text=translation.image_alt_text,
            reading_time_minutes=translation.reading_time_minutes,
            facebook_share_text=translation.facebook_share_text,
            telegram_share_text=translation.telegram_share_text,
            x_share_text=translation.x_share_text,
            tags=translation.tags,
            status='draft',
            created_at=now,
            updated_at=now,
        ))
    db.commit()
    return RedirectResponse(f'/admin/articles/{duplicate.id}/edit?duplicated=1', status_code=302)


@app.post('/admin/articles/{article_id}/delete')
def delete_article(article_id: int, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    article = db.query(Article).get(article_id)
    status = article.status if article else 'all'
    if article:
        db.delete(article)
        db.commit()
    return RedirectResponse(f'/admin/articles?status={status}', status_code=302)


def unique_category_slug(db, value: str, category_id: int | None = None) -> str:
    base = slugify(value) or "category"
    candidate = base
    suffix = 2
    query = db.query(Category).filter(Category.slug == candidate)
    if category_id is not None:
        query = query.filter(Category.id != category_id)
    while query.first():
        candidate = f"{base}-{suffix}"
        suffix += 1
        query = db.query(Category).filter(Category.slug == candidate)
        if category_id is not None:
            query = query.filter(Category.id != category_id)
    return candidate


def category_seo_score(category: Category, article_count: int, latest_article_date: datetime | None) -> int:
    checks = [
        bool((category.name or "").strip()),
        bool((category.slug or "").strip() and slugify(category.slug) == category.slug),
        bool((category.description or "").strip()),
        bool((category.color or "").strip()),
        article_count > 0,
        latest_article_date is not None,
    ]
    return round((sum(1 for passed in checks if passed) / len(checks)) * 100)


def seo_score_class(score: int) -> str:
    if score >= 90:
        return "excellent"
    if score >= 70:
        return "good"
    if score >= 50:
        return "average"
    return "poor"


def category_management_context(db) -> dict:
    categories = db.query(Category).order_by(Category.name.asc()).all()
    article_rows = db.query(Article.category, func.count(Article.id)).group_by(Article.category).all()
    counts = {name or "Uncategorized": int(count or 0) for name, count in article_rows}
    latest_rows = db.query(Article.category, func.max(func.coalesce(Article.published_at, Article.publish_at, Article.created_at))).group_by(Article.category).all()
    latest_dates = {name or "Uncategorized": latest for name, latest in latest_rows}
    view_rows = (
        db.query(Article.category, func.count(ArticleView.id))
        .join(ArticleView, ArticleView.article_id == Article.id)
        .filter(public_traffic_filter())
        .group_by(Article.category)
        .all()
    )
    views = {name or "Uncategorized": int(count or 0) for name, count in view_rows}
    category_names = {c.name for c in categories}
    cards = []
    for category in categories:
        count = counts.get(category.name, 0)
        latest = latest_dates.get(category.name)
        score = category_seo_score(category, count, latest)
        cards.append(SimpleNamespace(
            id=category.id,
            name=category.name,
            slug=category.slug or slugify(category.name),
            description=category.description,
            color=category.color or "#48a6ff",
            article_count=count,
            views=views.get(category.name, 0),
            last_article_date=latest,
            seo_score=score,
            seo_class=seo_score_class(score),
        ))

    total_articles = sum(counts.get(c.name, 0) for c in categories)
    most_viewed = max(cards, key=lambda item: item.views, default=None)
    today = utc_start_of_day()
    recent_rows = db.query(Article.category, func.count(Article.id)).filter(Article.created_at >= today - timedelta(days=29)).group_by(Article.category).all()
    recent_counts = {name or "Uncategorized": int(count or 0) for name, count in recent_rows}
    fastest = max(cards, key=lambda item: recent_counts.get(item.name, 0), default=None)

    top_by_views = sorted(cards, key=lambda item: item.views, reverse=True)[:5]
    top_by_articles = sorted(cards, key=lambda item: item.article_count, reverse=True)[:5]
    lowest = sorted([item for item in cards if item.article_count or item.views], key=lambda item: (item.views, item.article_count))[:5]

    article_only_categories = sorted(name for name in counts if name and name not in category_names and name != "Uncategorized")
    default_missing = [item["name"] for item in DEFAULT_CATEGORIES if item["name"] not in category_names]
    recommended = []
    for name, count in sorted(counts.items(), key=lambda row: row[1], reverse=True):
        if name not in category_names and name != "Uncategorized":
            recommended.append(f"{name} ({count} articles)")
    recommended.extend(name for name in default_missing if name not in recommended)

    slug_groups: dict[str, list[str]] = {}
    normalized_groups: dict[str, list[str]] = {}
    for category in categories:
        slug_groups.setdefault(slugify(category.name), []).append(category.name)
        normalized_groups.setdefault(re.sub(r"[^a-z0-9]+", "", slugify(category.name)), []).append(category.name)
    merge = [" + ".join(names) for names in slug_groups.values() if len(names) > 1]
    duplicates = [" / ".join(names) for names in normalized_groups.values() if len(names) > 1]
    if article_only_categories:
        merge.extend(f"Create or merge article-only category: {name}" for name in article_only_categories[:3])

    return {
        "categories": categories,
        "counts": {c.name: counts.get(c.name, 0) for c in categories},
        "category_cards": cards,
        "category_stats": SimpleNamespace(
            total_categories=len(categories),
            total_articles=total_articles,
            most_viewed_category=SimpleNamespace(name=most_viewed.name if most_viewed else "None", views=most_viewed.views if most_viewed else 0),
            fastest_growing_category=SimpleNamespace(name=fastest.name if fastest else "None", growth=recent_counts.get(fastest.name, 0) if fastest else 0),
        ),
        "ai_suggestions": SimpleNamespace(
            recommended=recommended[:6],
            missing=(article_only_categories + default_missing)[:6],
            merge=merge[:6],
            duplicates=duplicates[:6],
        ),
        "performance": SimpleNamespace(top_by_views=top_by_views, top_by_articles=top_by_articles, lowest=lowest),
    }


@app.get('/admin/categories', response_class=HTMLResponse)
def categories_page(request: Request, db=Depends(get_db), _=Depends(require_auth)):
    context = category_management_context(db)
    context['request'] = request
    return templates.TemplateResponse('admin/categories.html', context)


@app.post('/admin/categories')
def create_category(
    request: Request,
    name: str = Form(...),
    description: str = Form(''),
    slug: str = Form(''),
    color: str = Form('#48a6ff'),
    icon: str = Form(''),
    seo_title: str = Form(''),
    seo_description: str = Form(''),
    db=Depends(get_db),
    _=Depends(require_auth),
):
    name = name.strip()
    if name and not db.query(Category).filter(Category.name == name).first():
        db.add(Category(name=name, slug=unique_category_slug(db, slug or name), description=description, color=color))
        db.commit()
    return RedirectResponse('/admin/categories', status_code=302)


@app.post('/admin/categories/{category_id}/edit')
def update_category(category_id: int, request: Request, name: str = Form(...), description: str = Form(''), slug: str = Form(''), color: str = Form('#48a6ff'), db=Depends(get_db), _=Depends(require_auth)):
    category = db.query(Category).get(category_id)
    name = name.strip()
    duplicate_name = db.query(Category).filter(Category.name == name, Category.id != category_id).first() if name else None
    if category and name and not duplicate_name:
        old_name = category.name
        category.name = name
        category.slug = unique_category_slug(db, slug or name, category_id)
        category.description = description
        category.color = color
        category.updated_at = datetime.utcnow()
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
def media_page(request: Request, q: str = '', article_q: str = '', date_from: str = '', date_to: str = '', image_type: str = 'all', sort: str = 'newest', page: int = 1, db=Depends(get_db), _=Depends(require_auth)):
    page = max(1, page)
    per_page = 24
    query = db.query(MediaAsset)
    if q.strip():
        query = query.filter(MediaAsset.filename.ilike(f"%{q.strip()}%"))
    if article_q.strip():
        matching_articles = db.query(Article.image_url).filter(or_(Article.title.ilike(f"%{article_q.strip()}%"), Article.source_title.ilike(f"%{article_q.strip()}%"))).all()
        article_image_urls = {value for (value,) in matching_articles if value}
        matching_asset_ids = [asset.id for asset in db.query(MediaAsset).all() if media_asset_article_values(asset) & article_image_urls]
        query = query.filter(MediaAsset.id.in_(matching_asset_ids or [0]))
    if image_type in {"jpg", "png", "webp"}:
        if image_type == "jpg":
            query = query.filter(or_(MediaAsset.filename.ilike("%.jpg"), MediaAsset.filename.ilike("%.jpeg"), MediaAsset.content_type == "image/jpeg", MediaAsset.mime_type == "image/jpeg"))
        else:
            query = query.filter(or_(MediaAsset.filename.ilike(f"%.{image_type}"), MediaAsset.content_type == f"image/{image_type}", MediaAsset.mime_type == f"image/{image_type}"))
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
    filters = {'q': q, 'article_q': article_q, 'date_from': date_from, 'date_to': date_to, 'image_type': image_type, 'sort': sort}
    return templates.TemplateResponse('admin/media.html', {'request': request, 'media_rows': media_rows, 'assets': [row.asset for row in media_rows], 'filters': filters, 'page': page, 'per_page': per_page, 'total': total, 'total_pages': total_pages, 'upload_dir': str(UPLOAD_DIR), 'media_stats': media_library_stats(db)})


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
    seo_fix_center = seo_fix_center_context(db)
    total_articles = len(rows)
    health_score = round(sum(row['audit']['score'] for row in rows) / total_articles) if total_articles else 100
    published_count = sum(1 for article in articles if article.status == 'published')
    google_news_ready = published_count > 0 and health_score >= 80 and seo_fix_center['missing_meta_descriptions'] == 0 and issue_counts['Missing schema'] == 0
    adsense_ready = bool((settings.adsense_publisher_id or '').strip())
    google_readiness_level = 'ready' if google_news_ready else 'warning' if published_count else 'critical'
    adsense_level = 'ready' if adsense_ready else 'warning'
    overall_level = 'ready' if google_news_ready and adsense_ready else 'warning' if published_count else 'critical'
    seo_overview = {
        'health_score': health_score,
        'total_articles': total_articles,
        'missing_meta_descriptions': seo_fix_center['missing_meta_descriptions'],
        'missing_hreflang': seo_fix_center['missing_hreflang'],
        'missing_canonical': seo_fix_center['missing_canonical'],
        'missing_images': issue_counts['Missing image'],
        'missing_schema': issue_counts['Missing schema'],
    }
    google_readiness = {
        'xml_sitemap_status': 'Active',
        'news_sitemap_status': 'Active' if published_count else 'Waiting for published articles',
        'news_sitemap_ready': published_count > 0,
        'rss_feed_status': 'Active',
        'last_sitemap_refresh': settings_map.get('sitemap_last_refreshed_at') or 'Dynamic sitemap updates on every request',
        'google_news_readiness': 'Ready' if google_news_ready else 'Needs attention' if published_count else 'Critical',
        'google_news_level': google_readiness_level,
        'adsense_readiness': 'Ready' if adsense_ready else 'Needs attention',
        'adsense_level': adsense_level,
        'overall_label': 'Ready' if overall_level == 'ready' else 'Needs attention' if overall_level == 'warning' else 'Critical',
        'overall_level': overall_level,
    }
    return templates.TemplateResponse('admin/seo.html', {'request': request, 'rows': rows, 'issue_counts': issue_counts, 'settings_map': settings_map, 'seo_overview': seo_overview, 'google_readiness': google_readiness, 'seo_fix_center': seo_fix_center, 'languages': SUPPORTED_LANGUAGES, 'ai_translation_status': ai_translation_status()})


def settings_system_status(db) -> dict[str, bool]:
    database_connected = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        database_connected = False
    return {
        "backup_script_ready": Path("scripts/backup_db.sh").exists(),
        "upload_dir_ready": UPLOAD_DIR.exists() and os.access(UPLOAD_DIR, os.W_OK),
        "persistent_uploads_ready": UPLOAD_DIR.is_absolute() and not str(UPLOAD_DIR).startswith(str(Path.cwd())),
        "database_connected": database_connected,
    }


@app.get('/admin/settings', response_class=HTMLResponse)
def settings_page(request: Request, db=Depends(get_db), _=Depends(require_auth)):
    admin_settings = get_settings_map(db)
    return templates.TemplateResponse('admin/settings.html', {'request': request, 'settings_map': admin_settings, 'config': settings, 'languages': SUPPORTED_LANGUAGES, 'ai_translation_status': ai_translation_status(), 'settings_system_status': settings_system_status(db), 'openai_runtime': openai_runtime_settings(), 'openai_model_options': OPENAI_MODEL_OPTIONS})


@app.post('/admin/settings')
def save_settings(request: Request, site_name: str = Form('VREYC'), editor_name: str = Form('Editor'), publish_mode: str = Form('manual'), default_language: str = Form('az'), site_description: str | None = Form(None), contact_email: str | None = Form(None), logo_url: str | None = Form(None), favicon_url: str | None = Form(None), organization_logo_url: str | None = Form(None), watermark_url: str | None = Form(None), facebook_url: str | None = Form(None), youtube_url: str | None = Form(None), tiktok_url: str | None = Form(None), instagram_url: str | None = Form(None), telegram_url: str | None = Form(None), mailru_url: str | None = Form(None), google_search_console_verification: str | None = Form(None), bing_webmaster_verification: str | None = Form(None), google_analytics_id: str | None = Form(None), google_tag_manager_id: str | None = Form(None), adsense_publisher_id: str | None = Form(None), ads_txt_status: str | None = Form(None), auto_ads_status: str | None = Form(None), header_ad_slot: str | None = Form(None), sidebar_ad_slot: str | None = Form(None), article_ad_slot: str | None = Form(None), openai_api_key: str | None = Form(None), openai_clear_api_key: str | None = Form(None), openai_model: str = Form('gpt-5.5-mini'), ai_translation_enabled: str | None = Form(None), ai_seo_enabled: str | None = Form(None), db=Depends(get_db), _=Depends(require_auth)):
    current_settings = get_settings_map(db)
    submitted_openai_key = (openai_api_key or "").strip()
    stored_openai_key = "" if openai_clear_api_key == "yes" else (submitted_openai_key or current_settings.get('openai_api_key') or settings.openai_api_key or "")
    values = {
        'site_name': site_name,
        'editor_name': editor_name,
        'publish_mode': publish_mode,
        'default_language': default_language,
        'site_description': site_description.strip() if site_description is not None else None,
        'contact_email': contact_email.strip() if contact_email is not None else None,
        'logo_url': logo_url.strip() if logo_url is not None else None,
        'favicon_url': favicon_url.strip() if favicon_url is not None else None,
        'organization_logo_url': organization_logo_url.strip() if organization_logo_url is not None else None,
        'watermark_url': watermark_url.strip() if watermark_url is not None else None,
        'facebook_url': facebook_url.strip() if facebook_url is not None else None,
        'youtube_url': youtube_url.strip() if youtube_url is not None else None,
        'tiktok_url': tiktok_url.strip() if tiktok_url is not None else None,
        'instagram_url': instagram_url.strip() if instagram_url is not None else None,
        'telegram_url': telegram_url.strip() if telegram_url is not None else None,
        'mailru_url': mailru_url.strip() if mailru_url is not None else None,
        'google_search_console_verification': google_search_console_verification.strip() if google_search_console_verification is not None else None,
        'bing_webmaster_verification': bing_webmaster_verification.strip() if bing_webmaster_verification is not None else None,
        'google_analytics_id': google_analytics_id.strip() if google_analytics_id is not None else None,
        'google_tag_manager_id': google_tag_manager_id.strip() if google_tag_manager_id is not None else None,
        'adsense_publisher_id': adsense_publisher_id.strip() if adsense_publisher_id is not None else None,
        'ads_txt_status': ads_txt_status.strip() if ads_txt_status is not None else None,
        'auto_ads_status': auto_ads_status.strip() if auto_ads_status is not None else None,
        'header_ad_slot': header_ad_slot.strip() if header_ad_slot is not None else None,
        'sidebar_ad_slot': sidebar_ad_slot.strip() if sidebar_ad_slot is not None else None,
        'article_ad_slot': article_ad_slot.strip() if article_ad_slot is not None else None,
        'openai_api_key': stored_openai_key,
        'openai_model': openai_model if openai_model in OPENAI_MODEL_OPTIONS else 'gpt-5.5-mini',
        'ai_translation_enabled': 'enabled' if ai_translation_enabled == 'enabled' else 'disabled',
        'ai_seo_enabled': 'enabled' if ai_seo_enabled == 'enabled' else 'disabled',
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
    translation_rows_map = {
        a.id: {(row.language or "").lower(): row for row in getattr(a, "translations", []) or [] if (row.language or "").lower() in TRANSLATION_LANGUAGES}
        for a in articles
    }
    total_articles = len(articles)
    fully_translated = sum(1 for article in articles if not translation_missing_map.get(article.id))
    language_coverage = []
    for language in SUPPORTED_LANGUAGES:
        completed = total_articles if language == "az" else sum(1 for article in articles if language not in translation_missing_map.get(article.id, []))
        language_coverage.append({
            "code": language,
            "label": LANGUAGE_LABELS.get(language, language.upper()),
            "completed": completed,
            "percentage": round((completed / total_articles) * 100) if total_articles else 0,
        })
    translation_status_map = {
        article.id: {
            "existing": [language for language in SUPPORTED_LANGUAGES if language == "az" or translation_rows_map.get(article.id, {}).get(language)],
            "draft": [language for language, row in translation_rows_map.get(article.id, {}).items() if language in TRANSLATION_LANGUAGES and (row.status or "pending") == "draft"],
            "pending": [language for language, row in translation_rows_map.get(article.id, {}).items() if language in TRANSLATION_LANGUAGES and (row.status or "pending") in {"pending", "generating"}],
            "failed": [language for language, row in translation_rows_map.get(article.id, {}).items() if language in TRANSLATION_LANGUAGES and (row.status or "pending") == "failed"],
            "rows": translation_rows_map.get(article.id, {}),
            "complete": not translation_missing_map.get(article.id),
        }
        for article in articles
    }
    translation_job_ids = [job.id for job in scheduler.get_jobs() if "translation" in (job.id or "").lower()]
    failed_translation_count = db.query(FetchLog).filter(FetchLog.level == "ERROR", FetchLog.message.ilike("%translation%")).count()
    last_generated_at = db.query(func.max(ArticleTranslation.updated_at)).scalar()
    queue_stats = {
        "pending": len(translation_job_ids),
        "completed": fully_translated,
        "failed": failed_translation_count,
        "last_generated": last_generated_at,
    }
    translation_stats = {
        "total_articles": total_articles,
        "fully_translated": fully_translated,
        "missing_translations": sum(len(missing) for missing in translation_missing_map.values()),
        "draft_translations": sum(1 for rows in translation_rows_map.values() for row in rows.values() if (row.status or "pending") == "draft"),
        "pending_translations": sum(1 for rows in translation_rows_map.values() for row in rows.values() if (row.status or "pending") in {"pending", "generating"}),
        "supported_languages": len(SUPPORTED_LANGUAGES),
    }
    return templates.TemplateResponse('admin/translations.html', {
        'request': request,
        'articles': articles,
        'languages': SUPPORTED_LANGUAGES,
        'language_labels': LANGUAGE_LABELS,
        'translation_missing_map': translation_missing_map,
        'translation_status_map': translation_status_map,
        'translation_stats': translation_stats,
        'language_coverage': language_coverage,
        'queue_stats': queue_stats,
        'ai_translation_status': ai_translation_status(),
    })


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


@app.post('/admin/translations/{article_id}/generate/{language}')
def admin_generate_translation_language(article_id: int, language: str, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    if language not in TRANSLATION_LANGUAGES:
        return RedirectResponse('/admin/translations?queued=bad_language', status_code=302)
    if not db.query(Article).get(article_id):
        return RedirectResponse('/admin/translations?queued=missing_article', status_code=302)
    if not is_ai_translation_configured():
        db.add(FetchLog(level="WARNING", message=AI_TRANSLATION_WARNING))
        db.commit()
        return RedirectResponse('/admin/translations?warning=ai_not_configured', status_code=302)
    scheduler.add_job(generate_missing_translations, args=[article_id, language], id=f"manual_article_translation_{article_id}_{language}_{datetime.utcnow().timestamp()}", replace_existing=False)
    return RedirectResponse('/admin/translations?queued=article', status_code=302)


@app.post('/admin/translations/{translation_id}/publish')
def admin_publish_translation(translation_id: int, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    row = db.query(ArticleTranslation).get(translation_id)
    if row:
        row.status = 'published'
        row.error_message = None
        row.updated_at = datetime.utcnow()
        db.commit()
    return RedirectResponse('/admin/translations?published=translation', status_code=302)


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


@app.get("/{language}/{section}/{slug}", response_class=HTMLResponse)
def article_by_language_section_slug(language: str, section: str, slug: str, request: Request, db=Depends(get_db)):
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(404)
    expected_section = LANGUAGE_NEWS_PATHS.get(language, "news")
    if section != expected_section:
        return RedirectResponse(article_url(language, slug), status_code=301)
    return render_article_page(slug, request, language, db)


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
