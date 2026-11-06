from typing import Annotated
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from sqlalchemy import select
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.auth import Database, get_current_user, log_action
from app.certificates import certificate_pdf
from app.models import DocumentRequest, User
from app.routers.mock_registry import mock_registry
from app.schemas import ClaimCreate, RequestResponse

router = APIRouter(prefix="/services", tags=["سرویس‌های کارگزاری"])
CurrentUser = Annotated[User, Depends(get_current_user)]


def transient(error: BaseException) -> bool:
    return isinstance(error, httpx.RequestError) or (
        isinstance(error, httpx.HTTPStatusError) and error.response.status_code >= 500
    )


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=4),
       retry=retry_if_exception(transient), reraise=True)
async def call_mock_registry(claim: ClaimCreate) -> str:
    # Use the same mock handler in-process, so container ports are irrelevant.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mock_registry), base_url="http://mock-registry"
    ) as client:
        response = await client.post("/submit", json=claim.model_dump())
        response.raise_for_status()
        return response.json()["message"]


def output(record: DocumentRequest) -> RequestResponse:
    return RequestResponse(id=record.id, tracking_code=record.tracking_code,
                           status=record.status, message=record.details or "در حال بررسی")


def create_record(db: Database, user: User, kind: str) -> DocumentRequest:
    record = DocumentRequest(user_id=user.id, request_type=kind,
                             tracking_code=f"{kind.upper()}-{uuid4().hex}", status="pending")
    db.add(record)
    db.flush()
    return record


@router.post("/claims", response_model=RequestResponse, status_code=201)
async def register_claim(claim: ClaimCreate, db: Database, user: CurrentUser, response: Response):
    record = create_record(db, user, "claim")
    db.commit()
    try:
        record.details = await call_mock_registry(claim)
        record.status = "success"
    except (httpx.RequestError, httpx.HTTPStatusError) as error:
        record.status = "failed"
        unavailable = transient(error)
        record.details = ("سامانهٔ شبیه‌سازی در دسترس نیست." if unavailable
                          else "سامانهٔ شبیه‌سازی درخواست را نپذیرفت.")
        response.status_code = 503 if unavailable else 422
    log_action(db, user.id, f"CLAIM_{record.status.upper()}", record.tracking_code)
    db.commit()
    return output(record)


@router.post("/maps", response_model=RequestResponse, status_code=201)
def request_map(file: UploadFile, db: Database, user: CurrentUser):
    if not file.size:
        raise HTTPException(422, "فایل خالی است.")
    if file.size > 5 * 1024 * 1024:
        raise HTTPException(413, "حداکثر اندازهٔ فایل ۵ مگابایت است.")
    record = create_record(db, user, "map")
    record.status = "success"
    record.details = "فایل دریافت شد و درخواست نقشه به‌صورت آزمایشی ثبت شد."
    log_action(db, user.id, "REQUEST_MAP", record.tracking_code)
    db.commit()
    return output(record)


@router.get("/track/{tracking_code}", response_model=RequestResponse)
def track_status(tracking_code: str, db: Database, user: CurrentUser):
    record = db.scalar(select(DocumentRequest).where(
        DocumentRequest.tracking_code == tracking_code, DocumentRequest.user_id == user.id
    ))
    if record is None:
        raise HTTPException(404, "پرونده‌ای با این کد رهگیری یافت نشد.")
    return output(record)


@router.get("/claims/{tracking_code}/certificate.pdf", response_class=Response,
            responses={200: {"content": {"application/pdf": {}}}})
def download_claim_certificate(tracking_code: str, db: Database, user: CurrentUser):
    claim = db.scalar(select(DocumentRequest).where(
        DocumentRequest.tracking_code == tracking_code,
        DocumentRequest.user_id == user.id,
        DocumentRequest.request_type == "claim",
    ))
    if claim is None:
        raise HTTPException(404, "ادعایی با این کد رهگیری یافت نشد.")
    if claim.status != "success":
        raise HTTPException(409, "گواهی فقط برای ادعای موفق قابل دریافت است.")
    pdf = certificate_pdf(claim.tracking_code, "SIMULATION")
    log_action(db, user.id, "DOWNLOAD_CERTIFICATE", claim.tracking_code)
    db.commit()
    return pdf
