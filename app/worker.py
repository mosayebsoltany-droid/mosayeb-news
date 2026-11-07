"""Durable, leased SQL outbox. Run embedded or separately with python -m app.worker."""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from uuid import uuid4

import httpx
from sqlalchemy import and_, or_, select, update

from app.config import get_settings
from app.database import SessionLocal
from app.models import AuditLog, DocumentRequest, NotificationEvent
from app.routers.external_services import gateway, SMSRequest, SMSResult

logger = logging.getLogger("broker.worker")
MAX_ATTEMPTS = 3
LEASE_SECONDS = 30


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def queue_claim_notification(db, claim: DocumentRequest) -> NotificationEvent:
    # Same transaction as the successful claim update, never a fire-and-forget task.
    event = db.scalar(select(NotificationEvent).where(NotificationEvent.document_request_id == claim.id))
    if event is None:
        now = utcnow()
        event = NotificationEvent(id=str(uuid4()), document_request_id=claim.id, user_id=claim.user_id,
                                  status="pending", attempts=0, available_at=now, created_at=now)
        db.add(event)
        db.flush()
    return event


@dataclass(frozen=True)
class WorkItem:
    id: str
    user_id: int
    attempt: int
    lease_token: str
    tracking_code: str


def claim_event(sessions=SessionLocal, now=None):
    now = now or utcnow()
    with sessions() as db:
        # Recover a process killed during its final allowed attempt.
        exhausted = list(db.scalars(select(NotificationEvent).where(
            NotificationEvent.status == "processing", NotificationEvent.lease_until <= now,
            NotificationEvent.attempts >= MAX_ATTEMPTS,
        ).limit(10)))
        for event in exhausted:
            changed = db.execute(update(NotificationEvent).where(
                NotificationEvent.id == event.id, NotificationEvent.status == "processing",
                NotificationEvent.lease_until <= now, NotificationEvent.attempts >= MAX_ATTEMPTS,
            ).values(status="failed", lease_token=None, lease_until=None))
            if changed.rowcount == 1:
                db.add(AuditLog(user_id=event.user_id, action="SIM_NOTIFICATION_FAILED", details=event.id))
        db.commit()
        eligible = and_(NotificationEvent.attempts < MAX_ATTEMPTS, or_(
            and_(NotificationEvent.status == "pending", NotificationEvent.available_at <= now),
            and_(NotificationEvent.status == "processing", NotificationEvent.lease_until <= now),
        ))
        event = db.scalar(select(NotificationEvent).where(eligible).order_by(
            NotificationEvent.created_at, NotificationEvent.id).limit(1))
        if event is None:
            return None
        token = str(uuid4())
        changed = db.execute(update(NotificationEvent).where(
            NotificationEvent.id == event.id, eligible,
        ).values(status="processing", attempts=NotificationEvent.attempts + 1,
                 lease_token=token, lease_until=now + timedelta(seconds=LEASE_SECONDS)))
        if changed.rowcount != 1:
            db.rollback()
            return None
        db.commit()
        db.refresh(event)
        claim = db.get(DocumentRequest, event.document_request_id)
        return WorkItem(event.id, event.user_id, event.attempts, token, claim.tracking_code)


async def send_sms_background(item: WorkItem) -> str:
    payload = SMSRequest(phone_number=f"DEMO-USER-{item.user_id}",
                         message=f"پروندهٔ آزمایشی با کد {item.tracking_code} ثبت شد.", event_id=item.id)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway),
                                 base_url="http://mock-external", trust_env=False) as client:
        reply = await asyncio.wait_for(client.post("/send-sms", json=payload.model_dump(mode="json")), timeout=5)
        reply.raise_for_status()
        result = SMSResult.model_validate(reply.json())
        if (result.status != "simulated" or result.simulation is not True
                or result.receipt != f"SIM-SMS-{item.id}"):
            raise ValueError("Not a simulated delivery")
        return result.receipt


def finish_event(item: WorkItem, receipt: str | None, sessions=SessionLocal, now=None):
    now = now or utcnow()
    done = receipt is not None
    terminal = done or item.attempt >= MAX_ATTEMPTS
    values = {"status": "completed" if done else ("failed" if terminal else "pending"),
              "lease_token": None, "lease_until": None, "receipt": receipt,
              "completed_at": now if done else None,
              "available_at": now + timedelta(seconds=min(30, 2 ** item.attempt))}
    with sessions() as db:
        changed = db.execute(update(NotificationEvent).where(
            NotificationEvent.id == item.id, NotificationEvent.status == "processing",
            NotificationEvent.lease_token == item.lease_token,
        ).values(**values))
        if changed.rowcount == 1 and terminal:
            db.add(AuditLog(user_id=item.user_id,
                           action="SIM_NOTIFICATION_DONE" if done else "SIM_NOTIFICATION_FAILED", details=item.id))
        db.commit()


async def process_one(sessions=SessionLocal):
    item = await asyncio.to_thread(claim_event, sessions)
    if item is None:
        return False
    receipt = None
    try:
        receipt = await send_sms_background(item)
    except (httpx.HTTPError, ValueError, asyncio.TimeoutError) as exc:
        logger.warning("simulated_notification_retry", extra={"error_kind": type(exc).__name__})
    await asyncio.to_thread(finish_event, item, receipt, sessions)
    return True


async def run_worker(sessions=SessionLocal):
    logger.info("simulation_worker_started")
    while True:
        try:
            handled = await process_one(sessions)
            if handled:
                continue
        except Exception as exc:
            # Includes storage outages. Task survives; claims/events remain durable.
            logger.error("simulation_worker_iteration_failed", extra={"error_kind": type(exc).__name__})
        await asyncio.sleep(get_settings().notification_poll_seconds)


if __name__ == "__main__":
    from app.core.logging import configure_logging
    configure_logging()
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass
