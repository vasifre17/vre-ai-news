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
from database.models import Article, ArticleRevision, FetchLog, Setting
from cms.auth.security import is_authenticated, set_session, verify_password
from scheduler.jobs import run_fetch_pipeline

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


def canonical_url(request: Request, path: str = "") -> str:
    return f"{settings.site_url.rstrip('/')}/{path.lstrip('/')}"


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


@app.on_event("startup")
def startup() -> None:
    init_db()
    db = SessionLocal()
    try:
        # lightweight migration for slug support
        db.execute("ALTER TABLE articles ADD COLUMN slug VARCHAR(500)")
        db.commit()
    except Exception:
        db.rollback()
    ensure_slugs(db)
    db.close()
    scheduler.add_job(run_fetch_pipeline, "interval", minutes=max(13, min(17, settings.fetch_interval_min)), id="fetch_job", replace_existing=True)
    scheduler.start()


@app.get("/", response_class=HTMLResponse)
def home(request: Request, q: str = "", category: str = "", db=Depends(get_db)):
    query = db.query(Article).filter(Article.status == "published")
    if q:
        query = query.filter((Article.title.ilike(f"%{q}%")) | (Article.summary.ilike(f"%{q}%")))
    if category:
        query = query.filter(Article.category == category)
    articles = query.order_by(Article.published_at.desc(), Article.created_at.desc()).limit(30).all()
    categories = [c[0] for c in db.query(Article.category).filter(Article.status == "published").distinct().all() if c[0]]
    return templates.TemplateResponse("public/home.html", {"request": request, "articles": articles, "categories": categories, "q": q, "category": category, "site_url": settings.site_url, "canonical": canonical_url(request)})


@app.get("/search", response_class=HTMLResponse)
def search(request: Request, q: str = "", db=Depends(get_db)):
    return home(request, q=q, db=db)


@app.get("/category/{category}", response_class=HTMLResponse)
def category_page(category: str, request: Request, db=Depends(get_db)):
    return home(request, category=category, db=db)


@app.get("/article/{article_id}", response_class=HTMLResponse)
def article_by_id(article_id: int, request: Request, db=Depends(get_db)):
    article = db.query(Article).filter(Article.id == article_id, Article.status == "published").first()
    if not article:
        raise HTTPException(404)
    return templates.TemplateResponse("public/article.html", {"request": request, "article": article, "site_url": settings.site_url, "canonical": canonical_url(request, f"article/{article.slug or article.id}")})


@app.get("/article/{slug}", response_class=HTMLResponse)
def article_by_slug(slug: str, request: Request, db=Depends(get_db)):
    article = db.query(Article).filter(Article.slug == slug, Article.status == "published").first()
    if not article:
        raise HTTPException(404)
    return templates.TemplateResponse("public/article.html", {"request": request, "article": article, "site_url": settings.site_url, "canonical": canonical_url(request, f"article/{article.slug}")})


@app.get('/sitemap.xml')
def sitemap(db=Depends(get_db)):
    urls = [f"<url><loc>{settings.site_url.rstrip('/')}/</loc></url>"]
    for a in db.query(Article).filter(Article.status == 'published').all():
        urls.append(f"<url><loc>{settings.site_url.rstrip('/')}/article/{a.slug or a.id}</loc></url>")
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{"".join(urls)}</urlset>'
    return Response(content=xml, media_type="application/xml")


@app.get('/robots.txt')
def robots():
    body = f"User-agent: *\nAllow: /\nDisallow: /admin\nSitemap: {settings.site_url.rstrip('/')}/sitemap.xml\n"
    return Response(content=body, media_type="text/plain")


@app.get("/admin/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("admin/login.html", {"request": request})


@app.post("/admin/login")
@limiter.limit("5/minute")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == settings.admin_username and settings.admin_password_hash and verify_password(password, settings.admin_password_hash):
        set_session(request, username)
        return RedirectResponse("/admin", status_code=302)
    return templates.TemplateResponse("admin/login.html", {"request": request, "error": "Invalid credentials"})


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, db=Depends(get_db), _=Depends(require_auth)):
    drafts = db.query(Article).filter(Article.status == "draft").count()
    published = db.query(Article).filter(Article.status == "published").count()
    categories = db.query(Article.category).filter(Article.status == "published").distinct().count()
    logs = db.query(FetchLog).order_by(FetchLog.created_at.desc()).limit(20).all()
    return templates.TemplateResponse("admin/dashboard.html", {"request": request, "drafts": drafts, "published": published, "categories": categories, "logs": logs})


@app.get("/admin/articles", response_class=HTMLResponse)
def admin_articles(request: Request, status: str = "draft", db=Depends(get_db), _=Depends(require_auth)):
    articles = db.query(Article).filter(Article.status == status).order_by(Article.created_at.desc()).all()
    return templates.TemplateResponse("admin/articles.html", {"request": request, "articles": articles, "status": status})


@app.post("/admin/articles/{article_id}/publish")
def publish_article(article_id: int, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    a = db.query(Article).get(article_id)
    if a:
        a.status = "published"
        a.published_at = datetime.utcnow()
        a.slug = a.slug or slugify(a.title)
        db.commit()
    return RedirectResponse("/admin/articles?status=draft", status_code=302)


@app.get('/admin/articles/{article_id}/edit', response_class=HTMLResponse)
def edit_page(article_id: int, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    article = db.query(Article).get(article_id)
    return templates.TemplateResponse('admin/edit.html', {'request': request, 'article': article})


@app.post('/admin/articles/{article_id}/edit')
def edit_article(article_id: int, request: Request, title: str = Form(...), content: str = Form(...), image_url: str = Form(''), category: str = Form(...), seo_title: str = Form(''), tags: str = Form(''), db=Depends(get_db), _=Depends(require_auth)):
    a = db.query(Article).get(article_id)
    if not a:
        return RedirectResponse('/admin/articles', status_code=302)
    db.add(ArticleRevision(article_id=a.id, title=a.title, content=a.content, image_url=a.image_url, category=a.category, seo_title=a.seo_title, tags=a.tags))
    a.title = title
    a.content = content
    a.image_url = image_url
    a.category = category
    a.seo_title = seo_title
    a.tags = tags
    a.slug = slugify(title)
    db.commit()
    return RedirectResponse(f'/admin/articles?status={a.status}', status_code=302)


@app.post('/admin/settings/mode')
def set_mode(request: Request, mode: str = Form(...), db=Depends(get_db), _=Depends(require_auth)):
    row = db.query(Setting).filter(Setting.key == 'publish_mode').first()
    if not row:
        row = Setting(key='publish_mode', value=mode)
        db.add(row)
    else:
        row.value = mode
    db.commit()
    return RedirectResponse('/admin', status_code=302)


@app.exception_handler(404)
def not_found(request: Request, exc):
    return templates.TemplateResponse('public/404.html', {'request': request}, status_code=404)


@app.exception_handler(500)
def server_error(request: Request, exc):
    return templates.TemplateResponse('public/500.html', {'request': request}, status_code=500)
