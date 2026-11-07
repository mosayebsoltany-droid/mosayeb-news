"""Owner-scoped mock gateway. No funds, card information or external bank calls."""
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update

from app.auth import Database, log_action, peer_ip
from app.core.rate_limit import limiter
from app.models import DocumentRequest, PaymentTransaction
from app.routers.services import CurrentUser

router = APIRouter(prefix="/payments", tags=["پرداخت کاملاً شبیه‌سازی‌شده"])
# Server-owned demonstration tariffs, in IRR; never a client-controlled price.
FEES = {"claim": 50_000, "map": 20_000}


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tracking_code: str = Field(min_length=1, max_length=40)
    amount: int | None = Field(default=None, strict=True, gt=0, le=2_000_000_000)


class PaymentVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tracking_code: str = Field(min_length=1, max_length=40)
    authority: str = Field(min_length=16, max_length=48)
    status: Literal["OK", "NOK"] = "OK"


class BankDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority: str = Field(min_length=16, max_length=48)
    outcome: Literal["OK", "NOK"]


def own_document(db, code, user):
    document = db.scalar(select(DocumentRequest).where(
        DocumentRequest.tracking_code == code, DocumentRequest.user_id == user.id))
    if document is None:
        raise HTTPException(404, "پرونده یافت نشد.")
    return document


def own_transaction(db, authority, user):
    transaction = db.scalar(select(PaymentTransaction).where(
        PaymentTransaction.authority == authority, PaymentTransaction.user_id == user.id))
    if transaction is None:
        raise HTTPException(404, "تراکنش یافت نشد.")
    return transaction


def audit(db, user, action, document, request):
    log_action(db, user.id, action, document.tracking_code,
               ip_address=peer_ip(request), request_id=getattr(request.state, "request_id", None))


def transaction_output(transaction, document):
    return {"simulation": True, "currency": "IRR", "amount": transaction.amount,
            "authority": transaction.authority, "status": transaction.status,
            "tracking_code": document.tracking_code, "payment_status": document.payment_status,
            "payment_url": "/payments/mock-bank-page?authority=" + transaction.authority,
            "expires_at": transaction.expires_at.isoformat() + "Z"}


@router.post("/request", summary="ساخت لینک پرداخت آزمایشی با تعرفهٔ سرور")
@limiter.limit("10/minute")
def request_payment(request: Request, payment: PaymentRequest, db: Database, user: CurrentUser, response: Response):
    document = own_document(db, payment.tracking_code, user)
    if document.status != "success":
        raise HTTPException(409, "پرداخت فقط برای پروندهٔ موفق مجاز است.")
    if document.payment_status == "paid":
        raise HTTPException(409, "هزینهٔ این پرونده قبلاً تأیید شده است.")
    fee = FEES.get(document.request_type)
    if fee is None:
        raise HTTPException(409, "تعرفهٔ این خدمت تعریف نشده است.")
    if payment.amount is not None and payment.amount != fee:
        raise HTTPException(400, "مبلغ با تعرفهٔ سرور مطابقت ندارد.")
    transaction = db.scalar(select(PaymentTransaction).where(
        PaymentTransaction.request_id == document.id,
        PaymentTransaction.status == "pending", PaymentTransaction.expires_at > now()
    ).order_by(PaymentTransaction.id))
    if transaction is None:
        stamp = now()
        transaction = PaymentTransaction(request_id=document.id, user_id=user.id, amount=fee,
            authority="SIM-" + token_urlsafe(24), status="pending", bank_status="pending",
            created_at=stamp, expires_at=stamp + timedelta(minutes=20))
        db.add(transaction)
        audit(db, user, "PAYMENT_REQUESTED", document, request)
        db.commit()
    return transaction_output(transaction, document)


@router.get("/mock-bank-page", summary="مشاهدهٔ تراکنش ساختگی؛ نیازمند توکن مالک")
def mock_bank_page(authority: str, db: Database, user: CurrentUser):
    transaction = own_transaction(db, authority, user)
    document = db.get(DocumentRequest, transaction.request_id)
    return {**transaction_output(transaction, document), "bank_status": transaction.bank_status,
            "info": "درگاه ساختگی؛ هیچ پولی جابه‌جا نمی‌شود. نتیجه را با /payments/simulate ثبت کنید؛ سپس /payments/verify را اجرا کنید."}


@router.post("/simulate", summary="انتخاب صریح موفقیت یا لغو در بانک ساختگی؛ پول واقعی ندارد")
@limiter.limit("10/minute")
def simulate_bank(request: Request, decision: BankDecision, db: Database, user: CurrentUser, response: Response):
    transaction = own_transaction(db, decision.authority, user)
    document = db.get(DocumentRequest, transaction.request_id)
    if transaction.expires_at <= now():
        raise HTTPException(409, "تراکنش منقضی شده است؛ درخواست تازه بسازید.")
    desired = "paid" if decision.outcome == "OK" else "cancelled"
    if transaction.bank_status != "pending":
        if transaction.bank_status != desired:
            raise HTTPException(409, "نتیجهٔ بانک قبلاً ثبت شده و تغییرپذیر نیست.")
    else:
        changed = db.execute(update(PaymentTransaction).where(
            PaymentTransaction.id == transaction.id, PaymentTransaction.bank_status == "pending",
            PaymentTransaction.status == "pending"
        ).values(bank_status=desired, receipt="SIM-RECEIPT-"+token_urlsafe(18)))
        if changed.rowcount != 1:
            raise HTTPException(409, "تراکنش هم‌زمان تغییر کرده است؛ وضعیت را بررسی کنید.")
        audit(db, user, "MOCK_BANK_RESULT", document, request)
        db.commit()
    return {"simulation": True, "bank_status": desired, "message": "نتیجهٔ ساختگی ثبت شد؛ تأیید سرور هنوز لازم است."}


@router.post("/verify", summary="تأیید بر اساس نتیجهٔ ذخیره‌شدهٔ بانک ساختگی؛ OK به‌تنهایی معتبر نیست")
@limiter.limit("20/minute")
def verify_payment(request: Request, payload: PaymentVerifyRequest, db: Database, user: CurrentUser, response: Response):
    transaction = own_transaction(db, payload.authority, user)
    document = own_document(db, payload.tracking_code, user)
    if transaction.request_id != document.id:
        raise HTTPException(404, "تراکنش این پرونده یافت نشد.")
    if transaction.status == "success":
        return transaction_output(transaction, document)
    if transaction.status == "failed":
        raise HTTPException(409, "تراکنش ناموفق است؛ درخواست تازه بسازید.")
    if transaction.expires_at <= now():
        raise HTTPException(409, "تراکنش منقضی شده است؛ درخواست تازه بسازید.")
    if transaction.bank_status == "pending" or not transaction.receipt:
        raise HTTPException(409, "بانک ساختگی هنوز نتیجه‌ای ثبت نکرده است.")
    if transaction.bank_status == "cancelled":
        changed = db.execute(update(PaymentTransaction).where(
            PaymentTransaction.id == transaction.id, PaymentTransaction.status == "pending"
        ).values(status="failed"))
        if changed.rowcount == 1:
            audit(db, user, "PAYMENT_FAILED", document, request)
        db.commit()
        raise HTTPException(400, "پرداخت آزمایشی لغو شده است.")
    if payload.status != "OK":
        raise HTTPException(409, "وضعیت callback با نتیجهٔ بانک ساختگی سازگار نیست.")
    if document.status != "success":
        raise HTTPException(409, "پرونده آمادهٔ پرداخت نیست.")
    # Compare-and-set on the document serializes competing authorities on both DBs.
    changed = db.execute(update(DocumentRequest).where(
        DocumentRequest.id == document.id, DocumentRequest.payment_status == "unpaid"
    ).values(payment_status="paid"))
    if changed.rowcount != 1:
        db.refresh(transaction)
        if transaction.status == "success":
            db.refresh(document)
            return transaction_output(transaction, document)
        raise HTTPException(409, "پرداخت دیگری قبلاً برای این پرونده تأیید شده است.")
    transaction.status = "success"
    transaction.verified_at = now()
    audit(db, user, "PAYMENT_SUCCESS", document, request)
    db.commit()
    db.refresh(document)
    return transaction_output(transaction, document)
