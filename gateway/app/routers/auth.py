from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field

from .. import db
from ..config import get_settings
from ..deps import SESSION_COOKIE, current_user
from ..security import create_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    email:    EmailStr
    password: str = Field(min_length=10, max_length=128)


def _set_session(response: Response, user_id: str, role: str) -> None:
    s = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        create_token(user_id, role),
        max_age=s.gateway_jwt_ttl_hours * 3600,
        httponly=True,
        secure=s.gateway_cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/register", status_code=201)
async def register(body: Credentials, response: Response):
    pool = db.pool()
    # Pierwszy użytkownik zostaje adminem i może się zarejestrować zawsze
    has_users = await pool.fetchval("SELECT EXISTS (SELECT 1 FROM gw_users)")
    if has_users and not get_settings().gateway_allow_signup:
        raise HTTPException(403, "Registration is disabled")
    role = "user" if has_users else "admin"
    try:
        user = await pool.fetchrow(
            "INSERT INTO gw_users (email, password_hash, role) VALUES ($1, $2, $3) RETURNING id, email, role",
            body.email.lower(), hash_password(body.password), role,
        )
    except asyncpg.UniqueViolationError:
        raise HTTPException(409, "Email already registered")
    _set_session(response, str(user["id"]), user["role"])
    return {"id": str(user["id"]), "email": user["email"], "role": user["role"]}


@router.post("/login")
async def login(body: Credentials, response: Response):
    user = await db.pool().fetchrow(
        "SELECT id, email, role, password_hash FROM gw_users WHERE email = $1", body.email.lower(),
    )
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")
    _set_session(response, str(user["id"]), user["role"])
    return {"id": str(user["id"]), "email": user["email"], "role": user["role"]}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(current_user)):
    return {"id": str(user["id"]), "email": user["email"], "role": user["role"]}
