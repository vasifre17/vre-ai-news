from passlib.context import CryptContext
from fastapi import Request
from itsdangerous import URLSafeSerializer
from config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
serializer = URLSafeSerializer(settings.secret_key, salt="session")


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


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
