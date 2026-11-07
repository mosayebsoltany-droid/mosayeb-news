from random import random

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
