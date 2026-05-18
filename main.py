from datetime import datetime
import re
from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from apscheduler.schedulers.background import BackgroundScheduler

from config import settings
from database.session import SessionLocal, init_db
from database.models import Article, ArticleRevision, FetchLog, Setting, ArticleTranslation
from cms.auth.security import is_authenticated, set_session, verify_password
from scheduler.jobs import run_fetch_pipeline, run_translation_pipeline
from i18n import SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE, LANGUAGE_LABELS, t, category_label

app = FastAPI(title=settings.app_name)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/assets", StaticFiles(directory="assets"), name="assets")
templates = Jinja2Templates(directory="templates")
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
scheduler = BackgroundScheduler()


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


def canonical_url(path: str = "") -> str:
    return f"{settings.site_url.rstrip('/')}/{path.lstrip('/')}"


def hreflang_map(path_suffix: str):
    return {lang: canonical_url(f"{lang}/{path_suffix}".rstrip('/')) for lang in SUPPORTED_LANGUAGES}


@app.on_event("startup")
def startup() -> None:
    init_db()
    db = SessionLocal()
    for sql in [
        "ALTER TABLE articles ADD COLUMN slug VARCHAR(500)",
        "ALTER TABLE articles ADD COLUMN meta_description VARCHAR(500)",
        "CREATE TABLE article_translations (id INTEGER PRIMARY KEY, article_id INTEGER, language VARCHAR(20), title VARCHAR(500), summary TEXT, content TEXT, seo_title VARCHAR(500), meta_description VARCHAR(500), tags VARCHAR(500), slug VARCHAR(500), status VARCHAR(20), last_error TEXT, created_at DATETIME, updated_at DATETIME)",
    ]:
        try:
            db.execute(sql)
            db.commit()
        except Exception:
            db.rollback()
    db.close()
    scheduler.add_job(run_fetch_pipeline, "interval", minutes=max(13, min(17, settings.fetch_interval_min)), id="fetch_job", replace_existing=True)
    scheduler.add_job(run_translation_pipeline, "interval", minutes=5, id="translation_job", replace_existing=True)
    scheduler.start()


def render_home(request: Request, lang: str, q: str, category: str, db):
    query = db.query(Article).filter(Article.status == "published")
    if q:
        query = query.filter((Article.title.ilike(f"%{q}%")) | (Article.summary.ilike(f"%{q}%")))
    if category:
        query = query.filter(Article.category == category)
    articles = query.order_by(Article.published_at.desc(), Article.created_at.desc()).limit(30).all()
    categories = [c[0] for c in db.query(Article.category).filter(Article.status == "published").distinct().all() if c[0]]
    return templates.TemplateResponse("public/home.html", {"request": request, "articles": articles, "categories": categories, "q": q, "category": category, "lang": lang, "labels": LANGUAGE_LABELS, "t": t, "category_label": category_label, "site_url": settings.site_url, "canonical": canonical_url(f"{lang}"), "hreflangs": hreflang_map("")})


@app.get("/", response_class=HTMLResponse)
def root_redirect():
    return RedirectResponse(f"/{DEFAULT_LANGUAGE}/", status_code=302)


@app.get("/{lang}/", response_class=HTMLResponse)
def home(lang: str, request: Request, q: str = "", category: str = "", db=Depends(get_db)):
    if lang not in SUPPORTED_LANGUAGES:
        raise HTTPException(404)
    return render_home(request, lang, q, category, db)


@app.get("/{lang}/search", response_class=HTMLResponse)
def search(lang: str, request: Request, q: str = "", db=Depends(get_db)):
    return home(lang, request, q=q, db=db)


@app.get("/{lang}/category/{category}", response_class=HTMLResponse)
def category_page(lang: str, category: str, request: Request, db=Depends(get_db)):
    return home(lang, request, category=category, db=db)


@app.get("/{lang}/article/{slug}", response_class=HTMLResponse)
def article_by_slug(lang: str, slug: str, request: Request, db=Depends(get_db)):
    if lang not in SUPPORTED_LANGUAGES:
        raise HTTPException(404)
    article = db.query(Article).filter(Article.slug == slug, Article.status == "published").first()
    translation = None
    if article and lang != "az":
        translation = db.query(ArticleTranslation).filter_by(article_id=article.id, language=lang).filter(ArticleTranslation.status.in_(["translated", "reviewed", "published"])).first()
    if not article:
        raise HTTPException(404)
    return templates.TemplateResponse("public/article.html", {"request": request, "article": article, "translation": translation, "lang": lang, "labels": LANGUAGE_LABELS, "t": t, "category_label": category_label, "canonical": canonical_url(f"{lang}/article/{translation.slug if translation and translation.slug else article.slug}"), "hreflangs": hreflang_map(f"article/{article.slug}")})


@app.get('/sitemap.xml')
def sitemap(db=Depends(get_db)):
    urls = []
    for lang in SUPPORTED_LANGUAGES:
        urls.append(f"<url><loc>{settings.site_url.rstrip('/')}/{lang}/</loc></url>")
    for a in db.query(Article).filter(Article.status == 'published').all():
        for lang in SUPPORTED_LANGUAGES:
            urls.append(f"<url><loc>{settings.site_url.rstrip('/')}/{lang}/article/{a.slug or a.id}</loc></url>")
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{"".join(urls)}</urlset>'
    return Response(content=xml, media_type="application/xml")

@app.get('/admin/translations', response_class=HTMLResponse)
def admin_translations(request: Request, db=Depends(get_db), _=Depends(require_auth)):
    rows = db.query(ArticleTranslation).order_by(ArticleTranslation.updated_at.desc()).limit(200).all()
    return templates.TemplateResponse('admin/translations.html', {'request': request, 'rows': rows})

@app.post('/admin/translations/{translation_id}/status')
def set_translation_status(translation_id: int, status: str = Form(...), db=Depends(get_db), _=Depends(require_auth)):
    tr = db.query(ArticleTranslation).get(translation_id)
    if tr and status in ["pending", "translated", "reviewed", "published"]:
        tr.status = status
        tr.updated_at = datetime.utcnow()
        db.commit()
    return RedirectResponse('/admin/translations', status_code=302)

# unchanged admin/auth routes omitted for brevity in this compact build
@app.get("/admin/login", response_class=HTMLResponse)
def login_page(request: Request): return templates.TemplateResponse("admin/login.html", {"request": request})
@app.post("/admin/login")
@limiter.limit("5/minute")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == settings.admin_username and settings.admin_password_hash and verify_password(password, settings.admin_password_hash): set_session(request, username); return RedirectResponse("/admin", status_code=302)
    return templates.TemplateResponse("admin/login.html", {"request": request, "error": "Invalid credentials"})
@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, db=Depends(get_db), _=Depends(require_auth)):
    drafts = db.query(Article).filter(Article.status == "draft").count(); published = db.query(Article).filter(Article.status == "published").count(); categories = db.query(Article.category).filter(Article.status == "published").distinct().count(); logs = db.query(FetchLog).order_by(FetchLog.created_at.desc()).limit(20).all(); return templates.TemplateResponse("admin/dashboard.html", {"request": request, "drafts": drafts, "published": published, "categories": categories, "logs": logs})

@app.exception_handler(404)
def not_found(request: Request, exc):
    lang = request.url.path.strip('/').split('/')[0] if request.url.path.strip('/') else DEFAULT_LANGUAGE
    if lang not in SUPPORTED_LANGUAGES: lang = DEFAULT_LANGUAGE
    return templates.TemplateResponse('public/404.html', {'request': request, 'lang': lang, 'labels': LANGUAGE_LABELS, 't': t}, status_code=404)

@app.exception_handler(500)
def server_error(request: Request, exc):
    lang = request.url.path.strip('/').split('/')[0] if request.url.path.strip('/') else DEFAULT_LANGUAGE
    if lang not in SUPPORTED_LANGUAGES: lang = DEFAULT_LANGUAGE
    return templates.TemplateResponse('public/500.html', {'request': request, 'lang': lang, 'labels': LANGUAGE_LABELS, 't': t}, status_code=500)
