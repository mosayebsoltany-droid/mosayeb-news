"""Mock-only integrations: no network, SMS delivery, civil-registry or signature provider."""
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, FastAPI
from pydantic import BaseModel, ConfigDict, Field

from app.auth import RoleChecker, get_current_user
from app.models import User

router = APIRouter(prefix="/external", tags=["سرویس‌های جانبی شبیه‌سازی"])
gateway = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
CurrentUser = Annotated[User, Depends(get_current_user)]
Admin = Annotated[User, Depends(RoleChecker(["admin"]))]


class NationalIDRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    national_id: str = Field(pattern=r"^[0-9]{10}$")


class SMSRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone_number: str = Field(pattern=r"^(?:09[0-9]{9}|DEMO-USER-[1-9][0-9]*)$")
    message: str = Field(min_length=1, max_length=500)
    event_id: UUID = Field(default_factory=uuid4)


class SMSResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["simulated"]
    simulation: Literal[True]
    receipt: str = Field(pattern=r"^SIM-SMS-[a-f0-9-]{36}$")


def simulate_sms(payload: SMSRequest) -> SMSResult:
    # Deterministic receipt for retries. Never print/persist the phone or message body.
    return SMSResult(status="simulated", simulation=True, receipt=f"SIM-SMS-{payload.event_id}")


@gateway.post("/send-sms", response_model=SMSResult)
def gateway_sms(payload: SMSRequest):
    return simulate_sms(payload)


@router.post("/verify-national-id", summary="قاعدهٔ تست پیشوند ۰۰؛ استعلام واقعی نیست")
def verify_national_id(payload: NationalIDRequest, user: CurrentUser):
    return {"simulation": True, "is_valid": payload.national_id.startswith("00"),
            "message": "نتیجه فقط بر اساس قاعدهٔ ساختگی پیشوند ۰۰ محاسبه شد."}


@router.post("/send-sms", response_model=SMSResult, summary="پیش‌نمایش درگاه ساختگی؛ پیامکی ارسال نمی‌شود")
def send_sms(payload: SMSRequest, admin: Admin):
    return simulate_sms(payload)
