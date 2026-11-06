from datetime import datetime, timedelta, timezone
from os import getenv
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuditLog, User

passwords = PasswordHash.recommended()
oauth = OAuth2PasswordBearer(tokenUrl="/auth/token")
Database = Annotated[Session, Depends(get_db)]


def secret() -> str:
    key = getenv("BROKER_JWT_SECRET", "")
    if len(key.encode()) < 32:
        raise HTTPException(503, "Authentication is not configured")
    return key


def issue_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": str(user.id), "iat": now, "exp": now + timedelta(minutes=30)},
        secret(), algorithm="HS256",
    )


def unauthorized() -> HTTPException:
    return HTTPException(401, "Invalid credentials", headers={"WWW-Authenticate": "Bearer"})


def get_current_user(token: Annotated[str, Depends(oauth)], db: Database) -> User:
    key = secret()
    try:
        claims = jwt.decode(token, key, algorithms=["HS256"], options={"require": ["sub", "exp"]})
        user_id = int(claims["sub"])
    except (jwt.InvalidTokenError, ValueError):
        raise unauthorized() from None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized()
    return user


def log_action(db: Session, user_id: int, action: str, details: str) -> None:
    db.add(AuditLog(user_id=user_id, action=action, details=details))
