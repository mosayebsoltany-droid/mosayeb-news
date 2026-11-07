from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.auth import Database, get_current_user
from app.models import NotificationEvent, User

router = APIRouter(prefix="/notifications", tags=["اعلان‌های شبیه‌سازی‌شده"])
CurrentUser = Annotated[User, Depends(get_current_user)]


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    document_request_id: int
    status: str
    attempts: int
    receipt: str | None
    created_at: datetime
    simulation: bool = True


@router.get("/{event_id}", response_model=NotificationRead)
def notification_status(event_id: str, db: Database, user: CurrentUser):
    event = db.scalar(select(NotificationEvent).where(NotificationEvent.id == event_id,
                                                     NotificationEvent.user_id == user.id))
    if event is None:
        raise HTTPException(404, "اعلان آزمایشی یافت نشد.")
    return event
