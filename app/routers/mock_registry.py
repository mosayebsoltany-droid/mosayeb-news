from random import random
import re

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from app.core.errors import validation_exception_handler, global_exception_handler

from app.config import get_settings
from app.schemas import ClaimCreate

mock_registry = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


mock_registry.add_exception_handler(RequestValidationError, validation_exception_handler)
mock_registry.add_exception_handler(Exception, global_exception_handler)


@mock_registry.post("/submit")
def submit(claim: ClaimCreate):
    if random() < get_settings().mock_failure_rate:
        raise HTTPException(503, "Simulated registry outage")
    return {"message": "ادعا در سامانهٔ شبیه‌سازی پذیرفته شد."}


@mock_registry.get("/identity-check/{national_id}", summary="استعلام ساختگی هویت؛ فاقد اعتبار واقعی")
def identity_check(national_id: str):
    if not re.fullmatch(r"[0-9]{10}", national_id):
        raise HTTPException(400, "کد ملی نامعتبر است")
    # A test fixture rule only: the prefix does not represent anyone's real vital status.
    alive = not national_id.startswith("9")
    return {"national_id": national_id, "is_alive": alive, "simulation": True,
            "status": "simulated_alive" if alive else "simulated_deceased"}
