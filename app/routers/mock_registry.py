from os import getenv
from random import random

from fastapi import FastAPI, HTTPException

from app.schemas import ClaimCreate

mock_registry = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@mock_registry.post("/submit")
def submit(claim: ClaimCreate):
    if random() < float(getenv("BROKER_MOCK_FAILURE_RATE", "0.2")):
        raise HTTPException(503, "Simulated registry outage")
    return {"message": "ادعا در سامانهٔ شبیه‌سازی پذیرفته شد."}
