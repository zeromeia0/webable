import hashlib
import hmac
import os
from base64 import b64encode, b64decode
from typing import Optional

from fastapi import Request
from sqlalchemy.orm import Session

from .models import User

SESSION_COOKIE = "webable_session"


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return f"{b64encode(salt).decode()}${b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        salt_b64, digest_b64 = encoded.split("$", 1)
        salt = b64decode(salt_b64.encode())
        expected = b64decode(digest_b64.encode())
    except ValueError:
        return False
    got = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return hmac.compare_digest(got, expected)


def issue_session(user: User) -> str:
    payload = f"{user.id}:{user.username}".encode("utf-8")
    return b64encode(payload).decode("utf-8")


def parse_session(token: str) -> Optional[tuple[int, str]]:
    try:
        raw = b64decode(token.encode("utf-8")).decode("utf-8")
        user_id_str, username = raw.split(":", 1)
        return int(user_id_str), username
    except Exception:
        return None


def current_user(request: Request, db: Session) -> Optional[User]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    parsed = parse_session(token)
    if not parsed:
        return None
    user_id, username = parsed
    user = db.query(User).filter(User.id == user_id, User.username == username).first()
    return user
