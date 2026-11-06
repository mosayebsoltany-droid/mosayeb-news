from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.auth import Database, issue_token, log_action, passwords, unauthorized
from app.models import User

router = APIRouter(prefix="/auth", tags=["Authentication"])
DUMMY_HASH = passwords.hash("dummy password for absent accounts")


@router.post("/token")
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: Database):
    user = db.scalar(select(User).where(User.username == form.username))
    verified = passwords.verify(form.password, user.hashed_password if user else DUMMY_HASH)
    if not verified or user is None or not user.is_active:
        raise unauthorized()
    token = issue_token(user)
    log_action(db, user.id, "LOGIN", "Token issued")
    db.commit()
    return {"access_token": token, "token_type": "bearer"}
