# VREYC CMS

AI-powered FastAPI news CMS with scheduler, admin panel, SEO routes, templates, and publishing pipeline.

## Local development
1. Install dependencies:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
2. Configure env:
```bash
cp .env.example .env
# For local development only, set ENVIRONMENT=development in .env.
python scripts/generate_admin_hash.py
```
3. Initialize DB:
```bash
python scripts/init_db.py
```
4. Run app:
```bash
uvicorn main:app --reload
```
5. Open:
- Public site: `http://127.0.0.1:8000`
- Admin login: `http://127.0.0.1:8000/admin/login`

## Production deployment
- Live production domain: `https://vreyc.com`
- Set `ENVIRONMENT=production` and `SITE_URL=https://vreyc.com` in `.env`.
- Run `python scripts/validate_production.py` before starting production.
- Run `python scripts/production_smoke_check.py` before live launch verification.
- Docker + PostgreSQL: use `docker compose up -d --build`; uploaded article images persist directly in `/opt/vre-ai-news/uploads/images`.
- Rebuilds, startups, migrations, and normal deploys do not delete uploads; missing local image files render the built-in VREYC placeholder while existing `/static/uploads/images/...` paths remain valid.
- VPS guide: see `DEPLOYMENT.md`
- Security baseline: see `SECURITY.md`

## Included production assets
- `Dockerfile`
- `docker-compose.yml`
- `.env.example`
- `scripts/generate_admin_hash.py`
- `scripts/init_db.py`
- `scripts/backup_db.sh`
- `deploy/systemd/vre-ai-news.service`
- `deploy/nginx/vre-ai-news.conf`
