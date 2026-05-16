from pydantic import BaseModel
from dotenv import load_dotenv
import os

load_dotenv()


class Settings(BaseModel):
    app_name: str = "VRE AI NEWS"
    secret_key: str = os.getenv("SECRET_KEY", "change-me")
    admin_username: str = os.getenv("ADMIN_USERNAME", "admin")
    admin_password_hash: str = os.getenv("ADMIN_PASSWORD_HASH", "")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./vre_news.db")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    publish_mode: str = os.getenv("PUBLISH_MODE", "manual")
    fetch_interval_min: int = int(os.getenv("FETCH_INTERVAL_MIN", "15"))
    pexels_api_key: str = os.getenv("PEXELS_API_KEY", "")


settings = Settings()
