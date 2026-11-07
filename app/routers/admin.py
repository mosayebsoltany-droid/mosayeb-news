from datetime import datetime, time, timedelta, timezone
from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.auth import Database
from app.models import DocumentRequest, AuditLog
from app.schemas import AuditLogRead
from app.routers.analytics import Admin

router = APIRouter(prefix="/admin", tags=["نمودار مدیریتی"])


@router.get("/analytics/chart-data", summary="نمودار هفت روز اخیر، تاریخ UTC")
def chart_data(db: Database, admin: Admin):
    today = datetime.now(timezone.utc).date()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    day = func.date(DocumentRequest.created_at)
    rows = db.execute(select(day, DocumentRequest.status, func.count()).where(
        DocumentRequest.created_at >= datetime.combine(days[0], time.min),
        DocumentRequest.created_at < datetime.combine(today + timedelta(days=1), time.min),
        DocumentRequest.status.in_(["success", "failed"]),
    ).group_by(day, DocumentRequest.status)).all()
    counts = {(str(date), status): count for date, status, count in rows}
    return {"labels": [date.isoformat() for date in days], "datasets": [
        {"label": "پرونده‌های موفق", "data": [counts.get((str(date), "success"), 0) for date in days],
         "backgroundColor": "#198754"},
        {"label": "پرونده‌های ناموفق", "data": [counts.get((str(date), "failed"), 0) for date in days],
         "backgroundColor": "#dc3545"},
    ]}


@router.get("/audit-logs", response_model=list[AuditLogRead], summary="ممیزی محدود به مدیر")
def audit_logs(db: Database, admin: Admin, limit: int = Query(default=50, ge=1, le=200),
               offset: int = Query(default=0, ge=0, le=10000)):
    return list(db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit).offset(offset)))
