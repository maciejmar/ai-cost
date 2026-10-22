from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db, ledger
from ..deps import current_user, require_admin

router = APIRouter(prefix="/api/pricing", tags=["pricing"])


class PriceIn(BaseModel):
    provider_name:         Literal["openai", "anthropic", "litellm"]
    input_per_mtok:        float = Field(ge=0)
    output_per_mtok:       float = Field(ge=0)
    cached_input_per_mtok: float = Field(default=0, ge=0)
    cache_write_per_mtok:  float = Field(default=0, ge=0)


@router.get("")
async def list_pricing(_user: dict = Depends(current_user)):
    rows = await db.pool().fetch("SELECT * FROM gw_model_pricing ORDER BY provider_name, model")
    return [{**dict(r), **{k: float(r[k]) for k in (
        "input_per_mtok", "output_per_mtok", "cached_input_per_mtok", "cache_write_per_mtok")}} for r in rows]


@router.put("/{model}")
async def upsert_price(model: str, body: PriceIn, _admin: dict = Depends(require_admin)):
    await db.pool().execute(
        """
        INSERT INTO gw_model_pricing (model, provider_name, input_per_mtok, output_per_mtok,
                                      cached_input_per_mtok, cache_write_per_mtok, updated_at)
        VALUES ($1,$2,$3,$4,$5,$6,NOW())
        ON CONFLICT (model) DO UPDATE SET
            provider_name = EXCLUDED.provider_name,
            input_per_mtok = EXCLUDED.input_per_mtok,
            output_per_mtok = EXCLUDED.output_per_mtok,
            cached_input_per_mtok = EXCLUDED.cached_input_per_mtok,
            cache_write_per_mtok = EXCLUDED.cache_write_per_mtok,
            updated_at = NOW()
        """,
        model, body.provider_name, body.input_per_mtok, body.output_per_mtok,
        body.cached_input_per_mtok, body.cache_write_per_mtok,
    )
    ledger.invalidate_pricing()
    return {"model": model, **body.model_dump()}


@router.delete("/{model}", status_code=204)
async def delete_price(model: str, _admin: dict = Depends(require_admin)):
    result = await db.pool().execute("DELETE FROM gw_model_pricing WHERE model = $1", model)
    if result.endswith(" 0"):
        raise HTTPException(404, "Model not found")
    ledger.invalidate_pricing()
