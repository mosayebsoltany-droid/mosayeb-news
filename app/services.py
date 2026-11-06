from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import ForeignKey, String, select, update
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.certificates import certificate_pdf
from app.database import Base, get_db

Service = Literal["claim", "map", "certificate"]
DemoReference = Annotated[str, Field(pattern=r"^DEMO-[A-Z0-9]{1,20}$")]
router = APIRouter(prefix="/api/demo/requests", tags=["demo services"])
Database = Annotated[Session, Depends(get_db)]


class DemoRequest(Base):
    __tablename__ = "demo_requests"

    code: Mapped[str] = mapped_column(String(36), primary_key=True)
    service: Mapped[str] = mapped_column(String(20))
    reference: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(20))
    result: Mapped[str | None] = mapped_column(String(40))


class DemoEvent(Base):
    __tablename__ = "demo_request_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(ForeignKey("demo_requests.code"), index=True)
    action: Mapped[str] = mapped_column(String(30))


class PropertyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service: Literal["claim", "map"]
    reference: DemoReference


class CertificateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service: Literal["certificate"]
    reference: UUID


RequestInput = Annotated[PropertyRequest | CertificateRequest, Field(discriminator="service")]


class RequestOutput(BaseModel):
    code: UUID
    service: Service
    status: Literal["draft", "completed"]
    result: str | None
    events: list[str]


def lookup(db: Session, code: UUID) -> DemoRequest:
    record = db.get(DemoRequest, str(code))
    if record is None:
        raise HTTPException(404, "Demo request not found")
    return record


def response(db: Session, record: DemoRequest) -> RequestOutput:
    events = db.scalars(
        select(DemoEvent.action).where(DemoEvent.code == record.code).order_by(DemoEvent.id)
    )
    return RequestOutput(
        code=record.code, service=record.service, status=record.status,
        result=record.result, events=list(events),
    )


@router.post("", status_code=201)
def create_request(payload: RequestInput, db: Database) -> RequestOutput:
    if isinstance(payload, CertificateRequest):
        claim = lookup(db, payload.reference)
        if claim.service != "claim" or claim.status != "completed":
            raise HTTPException(409, "A completed demo claim is required")
    record = DemoRequest(
        code=str(uuid4()), service=payload.service, reference=str(payload.reference), status="draft"
    )
    db.add(record)
    db.flush()
    db.add(DemoEvent(code=record.code, action="registered"))
    db.commit()
    return response(db, record)


@router.get("/{code}")
def get_request(code: UUID, db: Database) -> RequestOutput:
    return response(db, lookup(db, code))


@router.post("/{code}/submit")
def submit_request(code: UUID, db: Database) -> RequestOutput:
    record = lookup(db, code)
    result = f"SIM-{record.service.upper()}-{record.code[:8].upper()}"
    updated = db.execute(
        update(DemoRequest)
        .where(DemoRequest.code == str(code), DemoRequest.status == "draft")
        .values(status="completed", result=result)
    )
    if updated.rowcount == 1:
        db.add_all([
            DemoEvent(code=str(code), action=action)
            for action in ("submitted", "simulation_response", "result_recorded")
        ])
    db.commit()
    db.refresh(record)
    return response(db, record)


@router.get("/{code}/certificate.pdf", response_class=Response,
            responses={200: {"content": {"application/pdf": {}}}})
def download_demo_certificate(code: UUID, db: Database):
    record = lookup(db, code)
    if record.service != "certificate" or record.status != "completed" or not record.result:
        raise HTTPException(409, "A completed demo certificate is required")
    return certificate_pdf(record.reference, record.result)
