# VREYC VPS DEPLOYMENT (Ubuntu)

This is a beginner-friendly production guide for deploying on a private Ubuntu VPS.

## A. Server prerequisites
1. Ubuntu 22.04+ VPS with sudo user.
2. Domain pointed to VPS public IP.
3. Open ports: 22, 80, 443.

## B. Install base packages
```bash
sudo apt update
sudo apt install -y git curl ufw fail2ban python3 python3-venv python3-pip nginx certbot python3-certbot-nginx docker.io docker-compose-plugin postgresql-client
```

## C. Clone project
```bash
cd /opt
sudo git clone <your-private-repo-url> vre-ai-news
sudo chown -R $USER:$USER /opt/vre-ai-news
cd /opt/vre-ai-news
```

## D. Configure environment
```bash
cp .env.example .env
nano .env
```
Set all required values:
- `SECRET_KEY`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD_HASH` (generated using `python scripts/generate_admin_hash.py`)
- `OPENAI_API_KEY`
- `PEXELS_API_KEY`
- `DATABASE_URL`
- `SITE_URL`
- `PUBLISH_MODE`
- `FETCH_INTERVAL_MIN`

## E. Docker deployment (recommended)
1. Update `.env` DATABASE_URL for compose network:
   - `postgresql+psycopg2://vre_user:vre_password@db:5432/vre_news`
2. Start stack:
```bash
docker compose up -d --build
```
3. Initialize DB once:
```bash
docker compose exec app python scripts/init_db.py
```
4. Check logs:
```bash
docker compose logs -f app
```

## F. Nginx reverse proxy
1. Copy sample config:
```bash
sudo cp deploy/nginx/vre-ai-news.conf /etc/nginx/sites-available/vre-ai-news
sudo ln -s /etc/nginx/sites-available/vre-ai-news /etc/nginx/sites-enabled/vre-ai-news
sudo nginx -t
sudo systemctl reload nginx
```
2. Replace `server_name` with your domain before reloading.

## G. SSL with Certbot
```bash
sudo certbot --nginx -d vreyc.com
```
- Choose HTTPS redirect when prompted.
- Test renewal:
```bash
sudo certbot renew --dry-run
```

## H. Non-Docker (systemd) deployment option
```bash
cd /opt/vre-ai-news
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/init_db.py
sudo cp deploy/systemd/vre-ai-news.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vre-ai-news
sudo systemctl status vre-ai-news
```

## I. Cloudflare checklist
- [ ] DNS `A` record points domain to VPS IP.
- [ ] Proxy status orange-cloud enabled.
- [ ] SSL/TLS mode set to **Full (strict)**.
- [ ] Always Use HTTPS enabled.
- [ ] Automatic HTTPS rewrites enabled.
- [ ] WAF basic protections enabled.
- [ ] Caching rules exclude `/admin*` pages.

## J. Backups
```bash
export DATABASE_URL='postgresql+psycopg2://vre_user:vre_password@localhost:5432/vre_news'
./scripts/backup_db.sh
```
Use cron for daily backups.

## K. Update flow
```bash
cd /opt/vre-ai-news
git pull
docker compose up -d --build
```
