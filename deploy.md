# Deploy Guide

1. Create venv and install dependencies:
   - `pip install -r requirements.txt`
2. Prepare env:
   - `cp .env.example .env`
   - set `SECRET_KEY`, `ADMIN_PASSWORD_HASH`, `OPENAI_API_KEY`
3. Run app:
   - `uvicorn main:app --host 0.0.0.0 --port 8000`
4. For production use nginx reverse proxy and systemd service.
5. Switch to PostgreSQL by setting `DATABASE_URL`.
