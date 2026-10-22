"""Hasła (bcrypt), sesje (JWT), klucze aplikacji (SHA-256) i szyfrowanie kluczy upstream (Fernet)."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings

APP_KEY_PREFIX = "agx_"


# ─── Hasła ────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


# ─── JWT ──────────────────────────────────────────────────────────────────

def create_token(user_id: str, role: str) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub":  user_id,
        "role": role,
        "iat":  now,
        "exp":  now + timedelta(hours=s.gateway_jwt_ttl_hours),
    }
    return jwt.encode(payload, s.gateway_jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, get_settings().gateway_jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


# ─── Klucze aplikacji ─────────────────────────────────────────────────────

def generate_app_key() -> tuple[str, str, str]:
    """Zwraca (pełny klucz, hash, prefix do wyświetlania)."""
    key = APP_KEY_PREFIX + secrets.token_urlsafe(32)
    return key, hash_app_key(key), key[:12]


def hash_app_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


# ─── Szyfrowanie kluczy upstream ──────────────────────────────────────────

def _fernet() -> Fernet:
    key = get_settings().gateway_encryption_key
    if not key:
        raise RuntimeError("GATEWAY_ENCRYPTION_KEY is not set")
    return Fernet(key.encode())


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None


def key_hint(key: str) -> str:
    return f"{key[:7]}…{key[-4:]}" if len(key) > 12 else "…"
