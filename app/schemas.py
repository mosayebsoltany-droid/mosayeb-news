from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import UserRole


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=100, pattern=r"^\S+$")
    password: str = Field(min_length=12, max_length=128)
    # Public registration must never accept an admin role from the caller.
    model_config = ConfigDict(extra="forbid")


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    role: UserRole
    is_active: bool


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    action: str
    timestamp: datetime
    details: str | None


class HealthResponse(BaseModel):
    status: str
    mode: str


class ClaimCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    national_id: str = Field(pattern=r"^[0-9]{10}$")
    claim_type: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)


class RequestResponse(BaseModel):
    id: int
    tracking_code: str
    status: str
    message: str


class DashboardStats(BaseModel):
    total_requests: int
    successful_requests: int
    failed_requests: int
    pending_requests: int
    top_broker: str
    start_date: date
    end_date: date
