from datetime import datetime
from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
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
templates = Jinja2Templates(directory="templates")
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

scheduler = BackgroundScheduler()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_auth(request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=401)


@app.on_event("startup")
def startup() -> None:
    init_db()
    scheduler.add_job(run_fetch_pipeline, "interval", minutes=max(13, min(17, settings.fetch_interval_min)), id="fetch_job", replace_existing=True)
    scheduler.start()


@app.get("/", response_class=HTMLResponse)
def home(request: Request, q: str = "", category: str = "", db=Depends(get_db)):
    query = db.query(Article).filter(Article.status == "published")
    if q:
        query = query.filter(Article.title.ilike(f"%{q}%"))
    if category:
        query = query.filter(Article.category == category)
    articles = query.order_by(Article.created_at.desc()).limit(30).all()
    return templates.TemplateResponse("public/home.html", {"request": request, "articles": articles})


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
    logs = db.query(FetchLog).order_by(FetchLog.created_at.desc()).limit(20).all()
    return templates.TemplateResponse("admin/dashboard.html", {"request": request, "drafts": drafts, "published": published, "logs": logs})


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
        db.commit()
    return RedirectResponse("/admin/articles?status=draft", status_code=302)

@app.get('/admin/articles/{article_id}/edit', response_class=HTMLResponse)
def edit_page(article_id:int, request: Request, db=Depends(get_db), _=Depends(require_auth)):
    article = db.query(Article).get(article_id)
    return templates.TemplateResponse('admin/edit.html', {'request': request, 'article': article})


@app.post('/admin/articles/{article_id}/edit')
def edit_article(article_id:int, request: Request, title: str = Form(...), content: str = Form(...), image_url: str = Form(''), category: str = Form(...), seo_title: str = Form(''), tags: str = Form(''), db=Depends(get_db), _=Depends(require_auth)):
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
