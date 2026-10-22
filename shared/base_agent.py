"""
BaseAgent — klasa bazowa dla wszystkich agentów.

Każdy agent to osobny Docker container z FastAPI + RabbitMQ + CostGate.
Implementacja agenta wymaga tylko dwóch metod:
  - setup():        subscribe to RabbitMQ queues
  - handle_event(): process incoming event

Przykład:
    class MyAgent(BaseAgent):
        async def setup(self):
            await self.rabbitmq.subscribe("my-agent", ["spec.completed"], self.handle_event)

        async def handle_event(self, event: Event) -> None:
            ...
            await self.publish_event(EventType.REPO_CREATED, {"repo_url": "..."})
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import uuid
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import httpx
import structlog
import uvicorn
from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, Gauge, Histogram, make_asgi_app

from .cost_gate import CostGate
from .models import AgentStatus, Event, EventType
from .rabbitmq_client import RabbitMQClient
from .whatsapp_client import WhatsAppClient

_log = logging.getLogger(__name__)


class BaseAgent(ABC):
    def __init__(self, agent_name: str, agent_type: str):
        self.name       = agent_name
        self.type       = agent_type
        self.status     = AgentStatus.IDLE
        self.current_action: str | None = None
        self.started_at = datetime.utcnow()
        self._shutdown  = asyncio.Event()

        # Structured JSON logging → stdout → Promtail → Loki
        structlog.configure(
            processors=[
                structlog.stdlib.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.JSONRenderer(),
            ],
            logger_factory=structlog.PrintLoggerFactory(),
            wrapper_class=structlog.BoundLogger,
        )
        self.log = structlog.get_logger().bind(agent=agent_name)

        # RabbitMQ
        rabbitmq_url = os.environ.get("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
        self.rabbitmq = RabbitMQClient(rabbitmq_url)

        # WhatsApp
        self.whatsapp = WhatsAppClient(
            account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
            auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
            from_number=os.getenv("TWILIO_WHATSAPP_FROM", ""),
            owner_numbers=os.getenv("OWNER_WHATSAPP_NUMBERS", "").split(","),
        )

        # Redis + Cost Gate
        import redis.asyncio as aioredis
        self._redis   = aioredis.from_url(
            os.environ.get("REDIS_URL", "redis://redis:6379/0"),
            encoding="utf-8",
            decode_responses=False,
        )
        self.cost_gate = CostGate(self._redis, self.whatsapp, agent_name)

        # LiteLLM URL
        self.litellm_url = os.getenv("LITELLM_URL", "http://litellm:4000")

        # AIGateway-X — gdy skonfigurowana, LLM idzie przez bramkę (routing, limity, ledger per agent)
        self.gateway_url     = os.getenv("GATEWAY_URL", "")
        self.gateway_app_key = os.getenv("GATEWAY_APP_KEY", "")

        # Prometheus metrics
        labels = {"agent": agent_name}
        self._events_processed = Counter(
            "agent_events_processed_total", "Total events processed",
            ["agent", "event_type", "status"],
        )
        self._llm_cost = Counter(
            "agent_llm_cost_usd_total", "Total LLM cost USD",
            ["agent", "model"],
        )
        self._task_duration = Histogram(
            "agent_task_duration_seconds", "Task processing time",
            ["agent"], buckets=[1, 5, 15, 30, 60, 120, 300, 600, 1800],
        )
        self._status_gauge = Gauge(
            "agent_status_info", "Agent status",
            ["agent", "status"],
        )

        self.app = self._build_fastapi()

    # ─── FastAPI app ─────────────────────────────────────────────────────

    def _build_fastapi(self) -> FastAPI:
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            self.log.info("Agent starting")
            await self.rabbitmq.wait_ready(timeout=60)
            await self.setup()
            self._status_gauge.labels(agent=self.name, status="idle").set(1)
            self.log.info("Agent ready")
            yield
            self.log.info("Agent stopping")
            await self.rabbitmq.close()
            await self._redis.aclose()

        app = FastAPI(title=f"Agent: {self.name}", lifespan=lifespan, docs_url=None)
        app.mount("/metrics", make_asgi_app())

        @app.get("/health")
        def health():
            return {
                "status":         "ok",
                "agent":          self.name,
                "agent_status":   self.status,
                "uptime_seconds": (datetime.utcnow() - self.started_at).total_seconds(),
            }

        @app.get("/status")
        def status():
            return {
                "agent":          self.name,
                "type":           self.type,
                "status":         self.status,
                "current_action": self.current_action,
                "started_at":     self.started_at.isoformat(),
            }

        @app.post("/stop")
        async def stop():
            self.log.warning("Stop requested via API")
            self._shutdown.set()
            return {"status": "stopping"}

        return app

    # ─── Abstrakcyjne metody do implementacji ────────────────────────────

    @abstractmethod
    async def setup(self) -> None:
        """Subscribe to RabbitMQ queues i zainicjuj agenta."""

    @abstractmethod
    async def handle_event(self, event: Event) -> None:
        """Obsłuż przychodzący event."""

    # ─── Helpers do używania przez agenty ────────────────────────────────

    async def publish_event(
        self,
        event_type:     EventType,
        payload:        dict[str, Any],
        correlation_id: str | None = None,
    ) -> None:
        event = Event(
            id=str(uuid.uuid4()),
            type=event_type,
            publisher=self.name,
            payload=payload,
            correlation_id=correlation_id,
        )
        await self.rabbitmq.publish(event)
        self.log.info("Event published", event_type=event_type.value, event_id=event.id)

    async def call_llm(
        self,
        model:        str,
        messages:     list[dict],
        context:      str = "",
        max_tokens:   int = 4096,
        temperature:  float = 0.1,
    ) -> str | None:
        """
        Wywoła LLM przez LiteLLM z Cost Gate.
        Zwraca treść odpowiedzi lub None jeśli zablokowane.
        """
        # Przybliżona liczba tokenów (4 znaki ≈ 1 token)
        input_text = " ".join(m.get("content", "") for m in messages)
        input_tokens  = max(len(input_text) // 4, 100)
        output_tokens = max_tokens

        estimate = self.cost_gate.estimate(model, input_tokens, output_tokens)
        proceed, model_to_use = await self.cost_gate.check_and_gate(estimate, context)

        if not proceed:
            self.log.warning("LLM call blocked by Cost Gate", model=model, cost=estimate.estimated_cost_usd)
            return None

        if model_to_use != model:
            self.log.info(f"Model downgraded: {model} → {model_to_use}")
            model = model_to_use

        self.log.info("LLM call", model=model, estimated_cost=estimate.estimated_cost_usd)
        self._set_working(f"LLM call: {model}")

        use_gateway = bool(self.gateway_url and self.gateway_app_key)
        if use_gateway:
            # X-App-ID = nazwa agenta → koszty i limity w bramce przypisane do tego agenta
            url = f"{self.gateway_url}/v1/chat/completions"
            headers = {"Authorization": f"Bearer {self.gateway_app_key}", "X-App-ID": self.name}
        else:
            url = f"{self.litellm_url}/v1/chat/completions"
            headers = {"Authorization": f"Bearer {os.environ.get('LITELLM_MASTER_KEY', '')}"}

        try:
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.post(
                    url,
                    headers={**headers, "Content-Type": "application/json"},
                    json={
                        "model":       model,
                        "messages":    messages,
                        "max_tokens":  max_tokens,
                        "temperature": temperature,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            if use_gateway:
                # Bramka sama księguje koszt (te same klucze Redis co CostGate) — nie liczymy podwójnie
                model = resp.headers.get("x-gateway-model", model)
                actual_cost = float(resp.headers.get("x-gateway-cost-usd", 0))
            else:
                usage = data.get("usage", {})
                actual_cost = await self.cost_gate.record_actual_cost(
                    model,
                    usage.get("prompt_tokens", input_tokens),
                    usage.get("completion_tokens", output_tokens),
                )
            self._llm_cost.labels(agent=self.name, model=model).inc(actual_cost)

            content = data["choices"][0]["message"]["content"]
            self.log.info("LLM call complete", model=model, actual_cost=actual_cost, via_gateway=use_gateway)
            return content

        except Exception as e:
            self.log.error("LLM call failed", model=model, error=str(e))
            raise
        finally:
            self._set_idle()

    def _set_working(self, action: str) -> None:
        self.status         = AgentStatus.WORKING
        self.current_action = action
        self._status_gauge.labels(agent=self.name, status="working").set(1)
        self._status_gauge.labels(agent=self.name, status="idle").set(0)

    def _set_idle(self) -> None:
        self.status         = AgentStatus.IDLE
        self.current_action = None
        self._status_gauge.labels(agent=self.name, status="working").set(0)
        self._status_gauge.labels(agent=self.name, status="idle").set(1)

    def _set_failed(self, reason: str) -> None:
        self.status         = AgentStatus.FAILED
        self.current_action = reason
        self._status_gauge.labels(agent=self.name, status="failed").set(1)
        self._status_gauge.labels(agent=self.name, status="working").set(0)

    # ─── Uruchomienie ────────────────────────────────────────────────────

    def run(self, port: int | None = None) -> None:
        port = port or int(os.getenv("AGENT_PORT", "8000"))
        uvicorn.run(
            self.app,
            host="0.0.0.0",
            port=port,
            log_config=None,      # structlog przejmuje logowanie
            access_log=False,
        )
