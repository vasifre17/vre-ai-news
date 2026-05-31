from datetime import datetime
import re
import shutil
from pathlib import Path
from uuid import uuid4
from sqlalchemy import or_, text
from fastapi import FastAPI, Request, Depends, Form, HTTPException, UploadFile, File
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
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/assets", StaticFiles(directory="assets"), name="assets")
templates = Jinja2Templates(directory="templates")
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
scheduler = BackgroundScheduler()
ai_engine = AIEngine()
SUPPORTED_LANGUAGES = ["az", "en", "ru", "tr", "zh", "es"]
LANGUAGE_LABELS = {"az": "Azerbaijani", "en": "English", "ru": "Russian", "tr": "Turkish", "zh": "Chinese", "es": "Spanish"}
UPLOAD_DIR = Path("static/uploads/media")

DEFAULT_CATEGORIES = [
    {"name": "Politics", "description": "Policy, elections, diplomacy and public leadership.", "color": "#e11d48"},
    {"name": "World", "description": "Global affairs, conflicts, climate and society.", "color": "#2563eb"},
    {"name": "Economy", "description": "Markets, macroeconomics, labor and public finance.", "color": "#16a34a"},
    {"name": "Technology", "description": "AI, platforms, cybersecurity, science and innovation.", "color": "#7c3aed"},
    {"name": "Business", "description": "Companies, startups, leadership and industry strategy.", "color": "#f97316"},
    {"name": "Sports", "description": "Scores, tournaments, athletes and sports business.", "color": "#06b6d4"},
    {"name": "Health", "description": "Medicine, wellbeing, research and public health.", "color": "#db2777"},
    {"name": "Agriculture", "description": "Food systems, farming technology and rural economies.", "color": "#65a30d"},
]


def slugify(text: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return base or "article"


def format_published_at(value):
    return value.strftime("%b %d, %Y") if value else ""


templates.env.filters["format_published_at"] = format_published_at


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
    if language == "az":
        return article
    for t in article.translations:
        if t.language == language:
            return t
    return None


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


def article_card(article: Article, language: str) -> dict:
    tr = get_translation(article, language)
    title = tr.title if tr and tr.title else article.title
    summary = tr.summary if tr and tr.summary else article.summary
    slug = tr.slug if tr and tr.slug else (article.slug or str(article.id))
    return {"article": article, "t": tr, "title": title, "summary": summary, "url": article_url(language, slug)}

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
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    db = SessionLocal()
    apply_schema_migrations(db)
    ensure_categories(db)
    ensure_slugs(db)
    db.close()
    scheduler.add_job(run_fetch_pipeline, "interval", minutes=max(13, min(17, settings.fetch_interval_min)), id="fetch_job", replace_existing=True)
    scheduler.add_job(generate_pending_narrations, "interval", seconds=45, id="narration_job", replace_existing=True)
    scheduler.start()


@app.get("/", response_class=HTMLResponse)
@app.get("/{language}/", response_class=HTMLResponse)
def home(request: Request, language: str = "az", q: str = "", category: str = "", db=Depends(get_db)):
    language = language if language in SUPPORTED_LANGUAGES else "az"
    ensure_categories(db)
    query = db.query(Article).filter(Article.status == "published")
    if q:
        query = query.filter((Article.title.ilike(f"%{q}%")) | (Article.summary.ilike(f"%{q}%")))
    if category:
        query = query.filter(Article.category == category)
    articles = query.order_by(Article.homepage_order.asc(), Article.published_at.desc(), Article.created_at.desc()).limit(30).all()
    featured = db.query(Article).filter(Article.status == "published", Article.is_featured == True).order_by(Article.homepage_order.asc(), Article.published_at.desc()).limit(6).all()
    if not featured:
        featured = articles[:6]
    trending = db.query(Article).filter(Article.status == "published", Article.is_trending == True).order_by(Article.homepage_order.asc(), Article.published_at.desc()).limit(8).all()
    if not trending:
        trending = articles[:8]
    article_cards = [article_card(a, language) for a in articles]
    featured_cards = [article_card(a, language) for a in featured]
    trending_cards = [article_card(a, language) for a in trending]
    hero = featured_cards[0] if featured_cards else (article_cards[0] if article_cards else None)
    latest_cards = [row for row in article_cards if not hero or row["article"].id != hero["article"].id]
    categories = category_navigation(db)
    return templates.TemplateResponse("public/home.html", {"request": request, "articles": article_cards, "latest_articles": latest_cards, "featured_articles": featured_cards, "trending_articles": trending_cards, "hero": hero, "categories": categories, "q": q, "category": category, "site_url": settings.site_url, "canonical": canonical_url(request, f'{language}/'), "language": language, "languages": SUPPORTED_LANGUAGES})


@app.get("/article/{slug}", response_class=HTMLResponse)
@app.get("/{language}/article/{slug}", response_class=HTMLResponse)
def article_by_slug(slug: str, request: Request, language: str = "az", db=Depends(get_db)):
    language = language if language in SUPPORTED_LANGUAGES else "az"
    slug_filters = [Article.slug == slug]
    if slug.isdigit():
        slug_filters.append(Article.id == int(slug))
    article = db.query(Article).filter(or_(*slug_filters), Article.status == "published").first()
    if not article and language != "az":
        tr = db.query(ArticleTranslation).filter(ArticleTranslation.slug == slug, ArticleTranslation.language == language).first()
        article = db.query(Article).get(tr.article_id) if tr else None
    if not article:
        raise HTTPException(404)
    tr = get_translation(article, language)
    view = tr if tr else article
    narration = db.query(ArticleNarration).filter(ArticleNarration.article_id == article.id, ArticleNarration.language == language).first()
    alt_links = {lang: article_url(lang, (get_translation(article, lang).slug if get_translation(article, lang) else (article.slug or str(article.id)))) for lang in SUPPORTED_LANGUAGES}
    related = db.query(Article).filter(Article.status == "published", Article.id != article.id, Article.category == article.category).order_by(Article.published_at.desc(), Article.created_at.desc()).limit(3).all()
    if len(related) < 3:
        related = related + db.query(Article).filter(Article.status == "published", Article.id != article.id, Article.category != article.category).order_by(Article.published_at.desc(), Article.created_at.desc()).limit(3 - len(related)).all()
    canonical = canonical_url(request, f"{language}/article/{view.slug or article.slug or article.id}")
    return templates.TemplateResponse("public/article.html", {"request": request, "article": view, "root_article": article, "narration": narration, "related_articles": [article_card(a, language) for a in related], "share_url": canonical, "site_url": settings.site_url, "canonical": canonical, "language": language, "languages": SUPPORTED_LANGUAGES, "alt_links": alt_links})


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
        for tr in a.translations:
            urls.append(f"<url><loc>{base_url}/{tr.language}/article/{tr.slug}</loc></url>")
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
    title = form.get('title_az') or form.get('title') or 'Untitled article'
    article = Article(
        title=title,
        slug=unique_article_slug(db, form.get('slug_az') or title),
        summary=form.get('summary_az', ''),
        content=form.get('content_az', ''),
        seo_title=form.get('seo_title_az', ''),
        meta_description=form.get('meta_description_az', ''),
        tags=form.get('tags_az', ''),
        image_url=form.get('image_url', ''),
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
    db.add(ArticleRevision(article_id=a.id, title=a.title, content=a.content, image_url=a.image_url, category=a.category, seo_title=a.seo_title, tags=a.tags))
    a.title = form.get('title_az') or form.get('title') or a.title
    a.slug = unique_article_slug(db, form.get('slug_az') or a.title, a.id)
    a.summary = form.get('summary_az', '')
    a.content = form.get('content_az', '')
    a.seo_title = form.get('seo_title_az', '')
    a.meta_description = form.get('meta_description_az', '')
    a.tags = form.get('tags_az', '')
    a.image_url = form.get('image_url', '')
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
        if not has_content and row:
            db.delete(row)
            continue
        if has_content:
            row = row or ArticleTranslation(article_id=a.id, language=lang)
            if row.id is None:
                db.add(row)
            row.title = form.get(f'title_{lang}', '')
            row.slug = slugify(form.get(f'slug_{lang}') or row.title or f'{a.slug}-{lang}')
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
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or 'upload.bin').suffix.lower()
    safe_name = f"{uuid4().hex}{suffix}"
    target = UPLOAD_DIR / safe_name
    with target.open('wb') as buffer:
        shutil.copyfileobj(file.file, buffer)
    stat = target.stat()
    asset = MediaAsset(filename=file.filename or safe_name, path=f"/static/uploads/media/{safe_name}", content_type=file.content_type or 'application/octet-stream', size_bytes=stat.st_size, alt_text=alt_text)
    db.add(asset)
    db.commit()
    return RedirectResponse('/admin/media', status_code=302)


@app.post('/admin/media/{asset_id}/delete')
def delete_media(asset_id: int, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    asset = db.query(MediaAsset).get(asset_id)
    if asset:
        local_path = Path(asset.path.lstrip('/'))
        if local_path.exists() and local_path.is_file():
            local_path.unlink()
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
