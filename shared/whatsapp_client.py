"""
WhatsApp Business API — klient dla powiadomień i zatwierdzeń.

Typy wiadomości:
  - alert:            informacyjny (budget, błędy, rollback)
  - approval_request: prośba o zatwierdzenie z przyciskami Approve/Reject
  - cost_preview:     preview kosztów przed startem pipeline

Twilio WhatsApp Sandbox:
  numer: whatsapp:+14155238886
  dołącz: wysyłając "join <SŁOWO>" do numeru sandbox

Produkcyjny WhatsApp Business:
  wymaga zatwierdzenia szablonów przez Meta
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ApprovalRequest:
    approval_id:    str
    agent_name:     str
    model:          str
    cost:           float
    context:        str


class WhatsAppClient:
    def __init__(
        self,
        account_sid:    str,
        auth_token:     str,
        from_number:    str,
        owner_numbers:  list[str],
    ):
        self.from_number   = from_number
        self.owner_numbers = [n for n in owner_numbers if n.strip()]
        self._client       = None

        if account_sid and auth_token and account_sid != "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx":
            try:
                from twilio.rest import Client
                self._client = Client(account_sid, auth_token)
            except ImportError:
                logger.warning("twilio package not installed — WhatsApp disabled")
        else:
            logger.warning("Twilio credentials not configured — WhatsApp disabled (using log only)")

    # ─── Publiczne API ────────────────────────────────────────────────────

    async def send_alert(self, message: str) -> None:
        logger.info(f"[WhatsApp ALERT] {message}")
        for number in self.owner_numbers:
            await self._send(number, message)

    async def send_approval_request(
        self,
        approval_id:  str,
        agent_name:   str,
        model:        str,
        cost:         float,
        context:      str,
    ) -> None:
        msg = (
            f"🔶 ZATWIERDZENIE WYMAGANE\n"
            f"ID: {approval_id}\n"
            f"Agent: {agent_name}\n"
            f"Model: {model}\n"
            f"Koszt: ${cost:.4f}\n"
            f"Kontekst: {context[:200]}\n\n"
            f"Odpowiedz:\n"
            f"  APPROVE {approval_id}\n"
            f"  REJECT {approval_id}"
        )
        logger.info(f"[WhatsApp APPROVAL REQUEST] {approval_id}: {agent_name} ${cost:.4f}")
        for number in self.owner_numbers:
            await self._send(number, msg)

    async def send_cost_preview(
        self,
        goal:             str,
        items:            list[dict],
        total_min:        float,
        total_max:        float,
        budget_remaining: float,
    ) -> None:
        lines = [f"📊 COST PREVIEW: {goal}", ""]
        for item in items:
            lines.append(f"  {item['agent']:25s} ~${item['cost']:.2f}  ({item['model']})")
        lines += [
            "",
            f"TOTAL: ${total_min:.2f} – ${total_max:.2f}",
            f"Budżet dzienny pozostały: ${budget_remaining:.2f}",
            "",
            "Odpowiedz: START | OLLAMA | CANCEL",
        ]
        msg = "\n".join(lines)
        logger.info(f"[WhatsApp COST PREVIEW] {goal}: ${total_min:.2f}–${total_max:.2f}")
        for number in self.owner_numbers:
            await self._send(number, msg)

    async def send_deployment_notify(self, app: str, env: str, url: str) -> None:
        msg = f"✅ DEPLOY: {app} → {env}\n{url}"
        await self.send_alert(msg)

    async def send_qa_failure(
        self, task_id: str, agent: str, attempt: int, max_attempts: int
    ) -> None:
        msg = (
            f"❌ QA FAILED [{attempt}/{max_attempts}]\n"
            f"Task: {task_id}\n"
            f"Fix agent pracuje..."
        )
        if attempt >= max_attempts:
            msg = (
                f"🚨 FIX EXHAUSTED — INTERWENCJA WYMAGANA\n"
                f"Task: {task_id}\n"
                f"Fix Agent nie mógł naprawić po {max_attempts} próbach.\n"
                f"Otwórz PR i sprawdź ręcznie."
            )
        await self.send_alert(msg)

    async def send_security_alert(self, finding: str, severity: str) -> None:
        emoji = "🔴" if severity in ("critical", "high") else "🟡"
        msg = f"{emoji} SECURITY: {severity.upper()}\n{finding[:400]}"
        await self.send_alert(msg)

    # ─── Parsing odpowiedzi od właścicieli ───────────────────────────────

    def parse_owner_reply(self, body: str) -> tuple[str, str] | None:
        """
        Parsuje odpowiedź od właściciela.
        Zwraca (action, approval_id) lub None.

        Formaty:
          APPROVE ABC12345
          REJECT  ABC12345
          START
          OLLAMA
          CANCEL
        """
        parts = body.strip().upper().split()
        if not parts:
            return None

        action = parts[0]
        if action in ("APPROVE", "REJECT") and len(parts) >= 2:
            return action, parts[1]
        if action in ("START", "OLLAMA", "CANCEL"):
            return action, ""

        return None

    # ─── Wewnętrzna wysyłka ──────────────────────────────────────────────

    async def _send(self, to: str, body: str) -> None:
        if not self._client:
            return

        try:
            import asyncio
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self._client.messages.create(
                    from_=self.from_number,
                    body=body,
                    to=to,
                ),
            )
        except Exception as e:
            logger.error(f"WhatsApp send failed to {to}: {e}")
