"""Aplikacje (agenci), ich kwoty i klucze agx_…"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db, limits
from ..deps import current_user
from ..security import generate_app_key

router = APIRouter(prefix="/api/apps", tags=["apps"])

Period   = Literal["day", "week", "month"]
Strategy = Literal["auto", "cheap", "smart", "fast"]


class AppIn(BaseModel):
    app_name:           str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    token_budget_limit: int | None = Field(default=None, ge=1)
    soft_limit_pct:     int = Field(default=80, ge=1, le=100)
    budget_period:      Period = "month"
    tpm_limit:          int | None = Field(default=None, ge=1)
    default_strategy:   Strategy = "auto"
    active:             bool = True


async def _owned_app(app_id: UUID, user: dict) -> dict:
    row = await db.pool().fetchrow(
        "SELECT * FROM gw_applications WHERE id = $1 AND user_id = $2", app_id, user["id"],
    )
    if not row:
        raise HTTPException(404, "Application not found")
    return dict(row)


def _serialize(app: dict, quota: limits.QuotaStatus | None = None, keys: list | None = None) -> dict:
    out = {k: (str(v) if isinstance(v, UUID) else v) for k, v in app.items()}
    if quota:
        out["usage"] = {
            "used":       quota.used,
            "limit":      quota.limit,
            "soft_limit": quota.soft_limit,
            "resets_at":  quota.resets_at.isoformat(),
            "tpm_used":   quota.tpm_used,
        }
    if keys is not None:
        out["keys"] = keys
    return out


@router.get("")
async def list_apps(user: dict = Depends(current_user)):
    pool = db.pool()
    apps = await pool.fetch("SELECT * FROM gw_applications WHERE user_id = $1 ORDER BY created_at", user["id"])
    keys = await pool.fetch(
        """
        SELECT k.id, k.app_id, k.key_prefix, k.revoked, k.last_used_at, k.created_at
          FROM gw_app_keys k JOIN gw_applications a ON a.id = k.app_id
         WHERE a.user_id = $1 ORDER BY k.created_at
        """,
        user["id"],
    )
    by_app: dict[str, list] = {}
    for k in keys:
        by_app.setdefault(str(k["app_id"]), []).append({
            "id": str(k["id"]), "prefix": k["key_prefix"], "revoked": k["revoked"],
            "last_used_at": k["last_used_at"], "created_at": k["created_at"],
        })
    return [_serialize(dict(a), await limits.app_quota(dict(a)), by_app.get(str(a["id"]), [])) for a in apps]


@router.post("", status_code=201)
async def create_app(body: AppIn, user: dict = Depends(current_user)):
    try:
        row = await db.pool().fetchrow(
            """
            INSERT INTO gw_applications (user_id, app_name, token_budget_limit, soft_limit_pct,
                                         budget_period, tpm_limit, default_strategy, active)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING *
            """,
            user["id"], body.app_name, body.token_budget_limit, body.soft_limit_pct,
            body.budget_period, body.tpm_limit, body.default_strategy, body.active,
        )
    except asyncpg.UniqueViolationError:
        raise HTTPException(409, f"Application '{body.app_name}' already exists")
    return _serialize(dict(row))


@router.put("/{app_id}")
async def update_app(app_id: UUID, body: AppIn, user: dict = Depends(current_user)):
    await _owned_app(app_id, user)
    try:
        row = await db.pool().fetchrow(
            """
            UPDATE gw_applications SET app_name=$3, token_budget_limit=$4, soft_limit_pct=$5,
                   budget_period=$6, tpm_limit=$7, default_strategy=$8, active=$9
             WHERE id=$1 AND user_id=$2 RETURNING *
            """,
            app_id, user["id"], body.app_name, body.token_budget_limit, body.soft_limit_pct,
            body.budget_period, body.tpm_limit, body.default_strategy, body.active,
        )
    except asyncpg.UniqueViolationError:
        raise HTTPException(409, f"Application '{body.app_name}' already exists")
    return _serialize(dict(row))


@router.delete("/{app_id}", status_code=204)
async def delete_app(app_id: UUID, user: dict = Depends(current_user)):
    await _owned_app(app_id, user)
    await db.pool().execute("DELETE FROM gw_applications WHERE id = $1", app_id)


@router.post("/{app_id}/keys", status_code=201)
async def create_key(app_id: UUID, user: dict = Depends(current_user)):
    await _owned_app(app_id, user)
    key, key_hash, prefix = generate_app_key()
    row = await db.pool().fetchrow(
        "INSERT INTO gw_app_keys (app_id, key_hash, key_prefix) VALUES ($1,$2,$3) RETURNING id, created_at",
        app_id, key_hash, prefix,
    )
    # Pełny klucz zwracamy tylko raz
    return {"id": str(row["id"]), "key": key, "prefix": prefix, "created_at": row["created_at"]}


@router.delete("/{app_id}/keys/{key_id}", status_code=204)
async def revoke_key(app_id: UUID, key_id: UUID, user: dict = Depends(current_user)):
    await _owned_app(app_id, user)
    await db.pool().execute("UPDATE gw_app_keys SET revoked = TRUE WHERE id = $1 AND app_id = $2", key_id, app_id)
