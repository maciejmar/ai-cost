from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request

from . import db
from .security import APP_KEY_PREFIX, decode_token, hash_app_key

SESSION_COOKIE = "agx_session"


async def current_user(request: Request) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    auth = request.headers.get("authorization", "")
    if not token and auth.lower().startswith("bearer ") and not auth[7:].startswith(APP_KEY_PREFIX):
        token = auth[7:]
    claims = decode_token(token) if token else None
    if not claims:
        raise HTTPException(401, "Not authenticated")
    user = await db.pool().fetchrow(
        "SELECT id, email, role, created_at FROM gw_users WHERE id = $1", claims["sub"],
    )
    if not user:
        raise HTTPException(401, "User no longer exists")
    return dict(user)


async def require_admin(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Admin role required")
    return user


def openai_error(status: int, message: str, code: str) -> HTTPException:
    """Błąd w kształcie OpenAI, żeby SDK klientów pokazywały sensowny komunikat."""
    return HTTPException(status, {"error": {"message": message, "type": code, "code": code}})


async def app_from_key(
    authorization: str = Header(default=""),
    x_app_id:      str = Header(default=""),
) -> dict:
    """Uwierzytelnia agenta: Bearer agx_… + wymagany X-App-ID zgodny z aplikacją klucza."""
    key = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    if not key.startswith(APP_KEY_PREFIX):
        raise openai_error(401, "Missing or invalid AIGateway-X key (Authorization: Bearer agx_…)", "invalid_api_key")
    if not x_app_id:
        raise openai_error(400, "Missing required header X-App-ID", "missing_app_id")

    row = await db.pool().fetchrow(
        """
        SELECT a.*, k.id AS key_id
          FROM gw_app_keys k
          JOIN gw_applications a ON a.id = k.app_id
         WHERE k.key_hash = $1 AND NOT k.revoked
        """,
        hash_app_key(key),
    )
    if not row:
        raise openai_error(401, "Unknown or revoked AIGateway-X key", "invalid_api_key")
    if x_app_id not in (row["app_name"], str(row["id"])):
        raise openai_error(403, f"X-App-ID '{x_app_id}' does not match this key's application", "app_id_mismatch")
    if not row["active"]:
        raise openai_error(403, f"Application '{row['app_name']}' is disabled", "app_disabled")

    await db.pool().execute("UPDATE gw_app_keys SET last_used_at = NOW() WHERE id = $1", row["key_id"])
    return dict(row)
