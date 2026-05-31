# Deploy Guide

Use `DEPLOYMENT.md` as the canonical VPS production checklist for launching VREYC at **https://vreyc.com**.

Quick production summary:
1. Copy `.env.example` to `.env` and set `ENVIRONMENT=production` plus `SITE_URL=https://vreyc.com`.
2. Fill all secrets, PostgreSQL credentials, `OPENAI_API_KEY`, and `PEXELS_API_KEY`.
3. Run `python scripts/validate_production.py` before starting the service.
4. Deploy with Docker Compose or systemd as described in `DEPLOYMENT.md`.
5. Run `python scripts/production_smoke_check.py`, then verify `https://vreyc.com/`, `/sitemap.xml`, `/robots.txt`, multilingual pages, narration, and `/admin/login`.
