"""Klucze upstream (szyfrowane) i konfiguracja okien subskrypcji per provider."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .. import db
from ..deps import current_user
from ..security import encrypt_secret, key_hint

router = APIRouter(prefix="/api", tags=["credentials"])

Provider = Literal["openai", "anthropic"]


class CredentialIn(BaseModel):
    api_key: str = Field(min_length=10, max_length=512)


class WindowIn(BaseModel):
    token_limit:    int | None = Field(default=None, ge=1)
    window_seconds: int | None = Field(default=None, ge=60, le=31 * 86400)


@router.get("/credentials")
async def list_credentials(user: dict = Depends(current_user)):
    rows = await db.pool().fetch(
        "SELECT provider_name, key_hint, created_at FROM gw_provider_credentials WHERE user_id = $1",
        user["id"],
    )
    return [dict(r) for r in rows]


@router.put("/credentials/{provider}")
async def set_credential(provider: Provider, body: CredentialIn, user: dict = Depends(current_user)):
    key = body.api_key.strip()
    await db.pool().execute(
        """
        INSERT INTO gw_provider_credentials (user_id, provider_name, encrypted_api_key, key_hint)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (user_id, provider_name) DO UPDATE
           SET encrypted_api_key = EXCLUDED.encrypted_api_key, key_hint = EXCLUDED.key_hint, created_at = NOW()
        """,
        user["id"], provider, encrypt_secret(key), key_hint(key),
    )
    return {"provider_name": provider, "key_hint": key_hint(key)}


@router.delete("/credentials/{provider}", status_code=204)
async def delete_credential(provider: Provider, user: dict = Depends(current_user)):
    await db.pool().execute(
        "DELETE FROM gw_provider_credentials WHERE user_id = $1 AND provider_name = $2", user["id"], provider,
    )


@router.put("/windows/{provider}")
async def set_window(provider: Literal["openai", "anthropic", "litellm"], body: WindowIn,
                     user: dict = Depends(current_user)):
    """Własne okno subskrypcji, np. 1 000 000 tokenów / 10 800 s (3h). Puste pola = wyłączone."""
    await db.pool().execute(
        """
        INSERT INTO gw_rate_limit_windows (user_id, provider_name, token_limit, window_seconds)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (user_id, provider_name) DO UPDATE
           SET token_limit = EXCLUDED.token_limit, window_seconds = EXCLUDED.window_seconds, updated_at = NOW()
        """,
        user["id"], provider, body.token_limit, body.window_seconds,
    )
    return {"provider": provider, **body.model_dump()}
