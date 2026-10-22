"""
Cost Gate — bramka kosztowa dla wywołań LLM.

Działanie:
  GREEN  (< $0.50):       auto-approve, agent działa bez pytania
  AMBER  ($0.50–$5.00):   WhatsApp notification z Approve/Reject (timeout 5 min)
  RED    (> $5.00):       blokada + natychmiastowy alert

Budżety dzienne:
  - Per agent: $10 → przełącz na Ollama
  - Globalny:  $50 → wszystkie na Ollama + alert
  - Miesięczny: $500 → tylko Ollama
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime

import redis.asyncio as aioredis

from .models import CostDecision

# Cennik LiteLLM (USD / 1K tokenów) — aktualizuj przy zmianach modeli
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-20250514":      {"input": 0.015,  "output": 0.075},
    "claude-opus-4":               {"input": 0.015,  "output": 0.075},
    "claude-sonnet-4-20250514":    {"input": 0.003,  "output": 0.015},
    "claude-sonnet-4":             {"input": 0.003,  "output": 0.015},
    "claude-haiku-4-5-20251001":   {"input": 0.0008, "output": 0.004},
    "claude-haiku-4":              {"input": 0.0008, "output": 0.004},
    "gpt-4o":                      {"input": 0.005,  "output": 0.015},
    "gpt-4o-mini":                 {"input": 0.00015,"output": 0.0006},
    "ollama-llama3-70b":           {"input": 0.0,    "output": 0.0},
    "ollama-mistral":              {"input": 0.0,    "output": 0.0},
}

# Model fallback gdy budżet wyczerpany
OLLAMA_FALLBACK_MODEL = "ollama-llama3-70b"


@dataclass
class CostEstimate:
    model:              str
    input_tokens:       int
    output_tokens:      int
    num_calls:          int
    estimated_cost_usd: float
    decision:           CostDecision

    def __str__(self) -> str:
        return (
            f"{self.model}: {self.num_calls}x call(s), "
            f"{self.input_tokens}in/{self.output_tokens}out tokens "
            f"→ ${self.estimated_cost_usd:.4f} [{self.decision.value.upper()}]"
        )


class CostGate:
    def __init__(
        self,
        redis_client: aioredis.Redis,
        whatsapp_client: object,
        agent_name: str,
    ):
        self.redis        = redis_client
        self.whatsapp     = whatsapp_client
        self.agent_name   = agent_name

        self.threshold_green        = float(os.getenv("COST_GATE_GREEN", "0.50"))
        self.threshold_amber        = float(os.getenv("COST_GATE_AMBER", "5.00"))
        self.budget_daily_per_agent = float(os.getenv("BUDGET_DAILY_PER_AGENT", "10.00"))
        self.budget_daily_global    = float(os.getenv("BUDGET_DAILY_GLOBAL", "50.00"))
        self.budget_monthly_cap     = float(os.getenv("BUDGET_MONTHLY_CAP", "500.00"))

    # ─── Szacowanie kosztu ────────────────────────────────────────────────

    def estimate(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        num_calls: int = 1,
    ) -> CostEstimate:
        pricing = MODEL_PRICING.get(model, {"input": 0.01, "output": 0.03})
        cost = (
            (input_tokens * pricing["input"] + output_tokens * pricing["output"])
            / 1000
            * num_calls
        )

        if cost < self.threshold_green:
            decision = CostDecision.GREEN
        elif cost < self.threshold_amber:
            decision = CostDecision.AMBER
        else:
            decision = CostDecision.RED

        return CostEstimate(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            num_calls=num_calls,
            estimated_cost_usd=round(cost, 6),
            decision=decision,
        )

    # ─── Główna bramka ───────────────────────────────────────────────────

    async def check_and_gate(
        self,
        estimate: CostEstimate,
        context: str = "",
    ) -> tuple[bool, str]:
        """
        Zwraca (proceed: bool, model_to_use: str).
        Jeśli proceed=False → pomiń call.
        Jeśli model_to_use != estimate.model → użyj tańszego modelu.
        """
        # 1. Sprawdź budżety
        daily_agent  = await self._get_daily_spend(self.agent_name)
        daily_global = await self._get_daily_spend("__global__")
        monthly      = await self._get_monthly_spend()

        if monthly >= self.budget_monthly_cap:
            await self.whatsapp.send_alert(
                f"🔴 MIESIĘCZNY CAP ${self.budget_monthly_cap} WYCZERPANY. "
                f"Wszystkie agenty przełączone na Ollama."
            )
            return True, OLLAMA_FALLBACK_MODEL

        if daily_global >= self.budget_daily_global:
            await self.whatsapp.send_alert(
                f"⚠️ Dzienny budżet globalny ${self.budget_daily_global} wyczerpany. "
                f"Przełączam {self.agent_name} na Ollama."
            )
            return True, OLLAMA_FALLBACK_MODEL

        if daily_agent + estimate.estimated_cost_usd > self.budget_daily_per_agent:
            await self.whatsapp.send_alert(
                f"⚠️ {self.agent_name}: limit dzienny ${self.budget_daily_per_agent}. "
                f"Wydane: ${daily_agent:.2f}. Przełączam na Ollama."
            )
            return True, OLLAMA_FALLBACK_MODEL

        # 2. Decision gate
        if estimate.decision == CostDecision.GREEN:
            return True, estimate.model

        if estimate.decision == CostDecision.RED:
            await self.whatsapp.send_alert(
                f"🔴 BLOKADA [{self.agent_name}] "
                f"Model: {estimate.model}, koszt: ${estimate.estimated_cost_usd:.2f}\n"
                f"Kontekst: {context}\n"
                f"Akcja ZABLOKOWANA. Zmień próg lub użyj tańszego modelu."
            )
            return False, estimate.model

        # AMBER — czekaj na zatwierdzenie WhatsApp
        approved = await self._request_whatsapp_approval(estimate, context)
        return approved, estimate.model if approved else ""

    # ─── Zapis kosztu po wykonaniu calla ─────────────────────────────────

    async def record_actual_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        pricing = MODEL_PRICING.get(model, {"input": 0.01, "output": 0.03})
        cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1000

        today = datetime.utcnow().strftime("%Y-%m-%d")
        month = datetime.utcnow().strftime("%Y-%m")

        pipe = self.redis.pipeline()
        pipe.incrbyfloat(f"cost:daily:{self.agent_name}:{today}", cost)
        pipe.incrbyfloat(f"cost:daily:__global__:{today}", cost)
        pipe.incrbyfloat(f"cost:monthly:{month}", cost)
        # Przechowuj dane przez 7 dni
        pipe.expire(f"cost:daily:{self.agent_name}:{today}", 86400 * 7)
        pipe.expire(f"cost:daily:__global__:{today}", 86400 * 7)
        await pipe.execute()

        return round(cost, 6)

    # ─── Budget warnings ─────────────────────────────────────────────────

    async def check_budget_warnings(self):
        daily_global = await self._get_daily_spend("__global__")
        ratio = daily_global / self.budget_daily_global

        if ratio >= 1.0:
            await self.redis.set("budget:daily:exhausted", "1", ex=3600)
        elif ratio >= 0.8:
            key = "budget:daily:warned"
            if not await self.redis.exists(key):
                await self.redis.set(key, "1", ex=3600)
                await self.whatsapp.send_alert(
                    f"⚠️ 80% dziennego budżetu globalnego wykorzystane. "
                    f"Wydane: ${daily_global:.2f} / ${self.budget_daily_global:.2f}"
                )

    # ─── Helpers ─────────────────────────────────────────────────────────

    async def _get_daily_spend(self, agent_name: str) -> float:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        value = await self.redis.get(f"cost:daily:{agent_name}:{today}")
        return float(value) if value else 0.0

    async def _get_monthly_spend(self) -> float:
        month = datetime.utcnow().strftime("%Y-%m")
        value = await self.redis.get(f"cost:monthly:{month}")
        return float(value) if value else 0.0

    async def _request_whatsapp_approval(
        self, estimate: CostEstimate, context: str
    ) -> bool:
        import uuid
        approval_id = str(uuid.uuid4())[:8].upper()

        await self.redis.setex(f"approval:{approval_id}", 300, "pending")

        await self.whatsapp.send_approval_request(
            approval_id=approval_id,
            agent_name=self.agent_name,
            model=estimate.model,
            cost=estimate.estimated_cost_usd,
            context=context,
        )

        # Poll przez 5 minut (60 × 5s)
        for _ in range(60):
            await asyncio.sleep(5)
            result = await self.redis.get(f"approval:{approval_id}")
            if result == b"approved":
                return True
            if result == b"rejected":
                return False

        # Timeout → odrzuć
        await self.redis.set(f"approval:{approval_id}", "timeout", ex=60)
        return False
