# VREYC VPS Deployment Checklist for vreyc.com (Ubuntu)

This checklist prepares VREYC for a live production launch at **https://vreyc.com** without changing the existing branding.

## 1. DNS and VPS prerequisites
- [ ] Ubuntu 22.04+ VPS is provisioned with a sudo user.
- [ ] `vreyc.com` DNS `A` record points to the VPS public IPv4 address.
- [ ] Ports `22`, `80`, and `443` are open in the VPS firewall/security group.
- [ ] Cloudflare, if used, is set to **Full (strict)** SSL mode after the certificate is installed.

## 2. Install server packages
```bash
sudo apt update
sudo apt install -y git curl ufw fail2ban python3 python3-venv python3-pip nginx certbot python3-certbot-nginx docker.io docker-compose-plugin postgresql-client
sudo systemctl enable --now docker nginx fail2ban
```

## 3. Clone the project
```bash
cd /opt
sudo git clone <your-private-repo-url> vre-ai-news
sudo chown -R $USER:$USER /opt/vre-ai-news
cd /opt/vre-ai-news
```

## 4. Configure production environment
```bash
cp .env.example .env
nano .env
```

Set these required values before launch:
- [ ] `ENVIRONMENT=production`
- [ ] `SITE_URL=https://vreyc.com`
- [ ] `SECRET_KEY` is a unique random value with at least 32 characters.
- [ ] `ADMIN_USERNAME` is not the default `admin`.
- [ ] `ADMIN_PASSWORD_HASH` is generated with `python scripts/generate_admin_hash.py`.
- [ ] `OPENAI_API_KEY` is configured for rewriting, translation, and AI audio narration.
- [ ] `PEXELS_API_KEY` is configured for image enrichment.
- [ ] `POSTGRES_PASSWORD` is a strong unique password.
- [ ] `DATABASE_URL=postgresql+psycopg2://vre_user:<POSTGRES_PASSWORD>@db:5432/vre_news` for Docker deployment.
- [ ] `PUBLISH_MODE` is `manual` for editorial approval or `auto` for automatic publishing.
- [ ] `FETCH_INTERVAL_MIN` is set to the desired fetch interval.
- [ ] article uploads use the fixed host path `/opt/vre-ai-news/uploads/images`; Docker Compose bind-mounts that same path into the container, and the app serves it at `/static/uploads/images/...` so existing article paths stay valid.

Validate the production environment locally on the server:
```bash
python scripts/validate_production.py
```

## 5. Docker deployment (recommended)
```bash
mkdir -p logs static/audio /opt/vre-ai-news/uploads/images
docker compose up -d --build
docker compose exec app python scripts/init_db.py
docker compose logs -f app
```

Persistence check after rebuild:
```bash
test -d /opt/vre-ai-news/uploads/images
docker compose down
docker compose up -d --build
test -d /opt/vre-ai-news/uploads/images
```
Do not use `docker compose down -v` for routine deploys because it removes Docker-managed volumes; uploaded images remain protected in the host bind mount at `/opt/vre-ai-news/uploads/images`.

## 6. Nginx reverse proxy for vreyc.com
```bash
sudo cp deploy/nginx/vre-ai-news.conf /etc/nginx/sites-available/vre-ai-news
sudo ln -sf /etc/nginx/sites-available/vre-ai-news /etc/nginx/sites-enabled/vre-ai-news
sudo nginx -t
sudo systemctl reload nginx
```

The committed Nginx config already uses `server_name vreyc.com` and proxies the FastAPI app on `127.0.0.1:8000`.

## 7. SSL certificate
```bash
sudo certbot --nginx -d vreyc.com
sudo certbot renew --dry-run
```

Choose the HTTPS redirect option when Certbot prompts for it.

## 8. Launch smoke checks
Run the local application smoke checks from the project root:
```bash
python scripts/production_smoke_check.py
```

Then verify the live site:
- [ ] `https://vreyc.com/` loads the public home page.
- [ ] `https://vreyc.com/az/`, `/en/`, `/ru/`, and `/tr/` load multilingual home pages; `/es/` and `/zh/` should return 404 or redirect safely.
- [ ] A published translated article shows correct `hreflang`, canonical metadata, and translated content.
- [ ] AI narration appears on published article pages after the background narration job completes.
- [ ] `https://vreyc.com/sitemap.xml` contains only `https://vreyc.com` URLs.
- [ ] `https://vreyc.com/robots.txt` points to `https://vreyc.com/sitemap.xml` and disallows `/admin`.
- [ ] `https://vreyc.com/admin/login` accepts the production admin credentials.
- [ ] Draft, publish, edit, translation generation, and narration regeneration actions work in the admin panel.

## 9. Backups
```bash
export DATABASE_URL='postgresql+psycopg2://vre_user:<POSTGRES_PASSWORD>@localhost:5432/vre_news'
./scripts/backup_db.sh
```

This also archives `/opt/vre-ai-news/uploads/images`, the persistent host directory used by the app for article images. Add a daily cron job after confirming backups restore successfully.

## 10. Update flow
```bash
cd /opt/vre-ai-news
git pull
mkdir -p /opt/vre-ai-news/uploads/images
docker compose down
docker compose up -d --build
docker compose exec app python scripts/init_db.py
docker compose logs -f app
```

Persistence check after rebuild:
```bash
test -d /opt/vre-ai-news/uploads/images
docker compose down
docker compose up -d --build
test -d /opt/vre-ai-news/uploads/images
```

## 11. Non-Docker systemd option
```bash
cd /opt/vre-ai-news
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/validate_production.py
python scripts/init_db.py
sudo cp deploy/systemd/vre-ai-news.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vre-ai-news
sudo systemctl status vre-ai-news
```
