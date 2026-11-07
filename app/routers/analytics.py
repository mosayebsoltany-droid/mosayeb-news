from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select

from app.auth import Database, RoleChecker
from app.models import DocumentRequest, User, UserRole
from app.schemas import DashboardStats

router = APIRouter(prefix="/analytics", tags=["داشبورد مدیریتی"])
Admin = Annotated[User, Depends(RoleChecker(["admin"]))]


@router.get("/dashboard", response_model=DashboardStats)
def dashboard(db: Database, admin: Admin,
              start_date: date | None = Query(default=None),
              end_date: date | None = Query(default=None)):
    today = datetime.now(timezone.utc).date()
    end = end_date or today
    if end < date(1900, 1, 1) or (start_date and start_date < date(1900, 1, 1)):
        raise HTTPException(422, "تاریخ باید از سال ۱۹۰۰ به بعد باشد.")
    start = start_date or end - timedelta(days=29)
    if start > end or end - start > timedelta(days=366):
        raise HTTPException(422, "بازهٔ تاریخ نامعتبر است؛ حداکثر یک سال را انتخاب کنید.")
    if end == date.max:
        raise HTTPException(422, "تاریخ پایان نامعتبر است.")
    # Existing timestamps are stored as naive UTC in both supported backends.
    filters = (DocumentRequest.created_at >= datetime.combine(start, time.min),
               DocumentRequest.created_at < datetime.combine(end + timedelta(days=1), time.min))
    totals = db.execute(select(
        func.count(DocumentRequest.id),
        func.coalesce(func.sum(case((DocumentRequest.status == "success", 1), else_=0)), 0),
        func.coalesce(func.sum(case((DocumentRequest.status == "failed", 1), else_=0)), 0),
        func.coalesce(func.sum(case((DocumentRequest.status == "pending", 1), else_=0)), 0),
    ).where(*filters)).one()
    top = db.execute(select(User.username).join(DocumentRequest).where(
        *filters, DocumentRequest.status == "success", User.role == UserRole.broker,
    ).group_by(User.id, User.username).order_by(
        func.count(DocumentRequest.id).desc(), User.username.asc(), User.id.asc(),
    ).limit(1)).scalar_one_or_none()
    return DashboardStats(total_requests=totals[0], successful_requests=totals[1],
                          failed_requests=totals[2], pending_requests=totals[3],
                          top_broker=top or "نامشخص", start_date=start, end_date=end)
