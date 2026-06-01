from pydantic import BaseModel
from dotenv import load_dotenv
import os
from urllib.parse import urlparse

load_dotenv()

PRODUCTION_DOMAIN = "vreyc.com"
PRODUCTION_SITE_URL = f"https://{PRODUCTION_DOMAIN}"
PLACEHOLDER_VALUES = {
    "",
    "change-me",
    "replace-with-a-long-random-secret",
    "$2b$12$replace_with_bcrypt_hash",
    "sk-...",
    "...",
}


class Settings(BaseModel):
    app_name: str = "VREYC"
    environment: str = os.getenv("ENVIRONMENT", os.getenv("APP_ENV", "development")).lower()
    secret_key: str = os.getenv("SECRET_KEY", "change-me")
    admin_username: str = os.getenv("ADMIN_USERNAME", "admin")
    admin_password_hash: str = os.getenv("ADMIN_PASSWORD_HASH", "")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./vre_news.db")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    publish_mode: str = os.getenv("PUBLISH_MODE", "manual")
    fetch_interval_min: int = int(os.getenv("FETCH_INTERVAL_MIN", "15"))
    pexels_api_key: str = os.getenv("PEXELS_API_KEY", "")
    site_url: str = os.getenv("SITE_URL", PRODUCTION_SITE_URL).rstrip("/")
    image_upload_dir: str = os.getenv("IMAGE_UPLOAD_DIR", "static/uploads/images")
    image_upload_url_prefix: str = os.getenv("IMAGE_UPLOAD_URL_PREFIX", "/static/uploads/images").rstrip("/")

    @property
    def is_production(self) -> bool:
        return self.environment in {"production", "prod"}

    def production_validation_errors(self) -> list[str]:
        errors: list[str] = []
        parsed_site = urlparse(self.site_url)

        if self.site_url != PRODUCTION_SITE_URL:
            errors.append(f"SITE_URL must be {PRODUCTION_SITE_URL} for live deployment.")
        if parsed_site.scheme != "https" or parsed_site.netloc != PRODUCTION_DOMAIN:
            errors.append("SITE_URL must use HTTPS and the vreyc.com host.")
        if self.secret_key in PLACEHOLDER_VALUES or "replace" in self.secret_key.lower() or len(self.secret_key) < 32:
            errors.append("SECRET_KEY must be a unique random value with at least 32 characters.")
        if not self.admin_username or self.admin_username == "admin" or "replace" in self.admin_username.lower():
            errors.append("ADMIN_USERNAME must be set to a non-default production administrator username.")
        if self.admin_password_hash in PLACEHOLDER_VALUES or not self.admin_password_hash.startswith("$2b$"):
            errors.append("ADMIN_PASSWORD_HASH must be a bcrypt hash generated with scripts/generate_admin_hash.py.")
        if self.openai_api_key in PLACEHOLDER_VALUES or not self.openai_api_key.startswith("sk-"):
            errors.append("OPENAI_API_KEY must be configured so AI rewriting, translation, and narration work.")
        if self.pexels_api_key in PLACEHOLDER_VALUES or "replace" in self.pexels_api_key.lower():
            errors.append("PEXELS_API_KEY must be configured for production image enrichment.")
        if self.database_url.startswith("sqlite"):
            errors.append("DATABASE_URL must point to PostgreSQL for production, not SQLite.")
        if "vre_password" in self.database_url or "replace" in self.database_url.lower():
            errors.append("DATABASE_URL must not contain default or placeholder credentials.")
        if self.publish_mode not in {"manual", "auto"}:
            errors.append("PUBLISH_MODE must be either manual or auto.")
        if not 1 <= self.fetch_interval_min <= 120:
            errors.append("FETCH_INTERVAL_MIN must be between 1 and 120 minutes.")
        return errors

    def validate_production_or_raise(self) -> None:
        if not self.is_production:
            return
        errors = self.production_validation_errors()
        if errors:
            joined = "\n- ".join(errors)
            raise RuntimeError(f"Production environment validation failed:\n- {joined}")


settings = Settings()
