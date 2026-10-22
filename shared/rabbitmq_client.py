"""
RabbitMQ client — jedyny kanał komunikacji między agentami.

Architektura:
  Exchange: agent.events (topic)
  Routing key: event.type (np. "qa.failed", "deploy.staging")
  Queue: jedna per agent, durable, z TTL 24h

Przykład:
  await client.publish(Event(type=EventType.QA_PASSED, publisher="qa-agent", payload={...}))
  await client.subscribe("qa-agent", ["pr.opened"], handle_pr)
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Awaitable
from typing import Any

import aio_pika
import aio_pika.exceptions

from .models import Event, EventType

logger = logging.getLogger(__name__)

EXCHANGE_NAME   = "agent.events"
DEAD_LETTER_EX  = "agent.dlx"
MESSAGE_TTL_MS  = 86_400_000   # 24h


class RabbitMQClient:
    def __init__(self, url: str):
        self.url         = url
        self._connection: aio_pika.RobustConnection | None = None
        self._channel:    aio_pika.RobustChannel | None = None
        self._exchange:   aio_pika.Exchange | None = None
        self._dlx:        aio_pika.Exchange | None = None

    async def connect(self):
        self._connection = await aio_pika.connect_robust(
            self.url,
            reconnect_interval=5,
            fail_fast=False,
        )
        self._channel = await self._connection.channel()
        await self._channel.set_qos(prefetch_count=10)

        # Dead-letter exchange dla nieobsłużonych wiadomości
        self._dlx = await self._channel.declare_exchange(
            DEAD_LETTER_EX,
            aio_pika.ExchangeType.FANOUT,
            durable=True,
        )

        self._exchange = await self._channel.declare_exchange(
            EXCHANGE_NAME,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )
        logger.info("RabbitMQ connected", extra={"url": self.url})

    async def publish(self, event: Event) -> None:
        if not self._exchange:
            raise RuntimeError("Not connected to RabbitMQ — call connect() first")

        body = event.model_dump_json().encode()
        message = aio_pika.Message(
            body=body,
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=event.id,
            correlation_id=event.correlation_id or event.id,
        )
        await self._exchange.publish(message, routing_key=event.type)
        logger.debug(
            "Event published",
            extra={"event_type": event.type, "event_id": event.id, "publisher": event.publisher},
        )

    async def subscribe(
        self,
        queue_name:   str,
        routing_keys: list[str],
        handler:      Callable[[Event], Awaitable[None]],
        *,
        auto_ack:     bool = False,
    ) -> None:
        if not self._channel or not self._exchange:
            raise RuntimeError("Not connected to RabbitMQ")

        # Dead-letter queue dla danego agenta
        dlq = await self._channel.declare_queue(
            f"{queue_name}.dlq",
            durable=True,
        )
        await dlq.bind(self._dlx)

        queue = await self._channel.declare_queue(
            queue_name,
            durable=True,
            arguments={
                "x-message-ttl":             MESSAGE_TTL_MS,
                "x-dead-letter-exchange":    DEAD_LETTER_EX,
                "x-dead-letter-routing-key": queue_name,
            },
        )

        for key in routing_keys:
            await queue.bind(self._exchange, routing_key=key)

        async def on_message(message: aio_pika.IncomingMessage) -> None:
            async with message.process(requeue_on_fail=True, ignore_processed=True):
                try:
                    data  = json.loads(message.body)
                    event = Event(**data)
                    await handler(event)
                except Exception:
                    logger.exception(
                        "Error processing event",
                        extra={"queue": queue_name, "body": message.body[:500]},
                    )
                    raise  # requeue_on_fail=True wyśle do DLQ po wyczerpaniu

        await queue.consume(on_message, no_ack=auto_ack)
        logger.info(
            "Subscribed to queue",
            extra={"queue": queue_name, "routing_keys": routing_keys},
        )

    async def close(self) -> None:
        if self._connection:
            await self._connection.close()
            logger.info("RabbitMQ connection closed")

    async def wait_ready(self, timeout: float = 30.0) -> None:
        """Czeka aż RabbitMQ będzie gotowy (przydatne podczas startu kontenera)."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                await self.connect()
                return
            except Exception as e:
                logger.debug(f"RabbitMQ not ready yet: {e}")
                await asyncio.sleep(2)
        raise TimeoutError(f"RabbitMQ not ready after {timeout}s")
