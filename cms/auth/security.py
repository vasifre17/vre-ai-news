import bcrypt
from passlib.context import CryptContext
from fastapi import Request
from itsdangerous import URLSafeSerializer
from config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
serializer = URLSafeSerializer(settings.secret_key, salt="session")


def verify_password(plain: str, hashed: str) -> bool:
    if hashed.startswith(("$2a$", "$2b$", "$2y$")):
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    return pwd_context.verify(plain, hashed)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def set_session(request: Request, username: str) -> None:
    request.session["auth"] = serializer.dumps({"u": username})


def is_authenticated(request: Request) -> bool:
    token = request.session.get("auth")
    if not token:
        return False
    try:
        serializer.loads(token)
        return True
    except Exception:
        return False


def clear_session(request: Request) -> None:
    request.session.pop("auth", None)
