from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import AuditLog, User

passwords = PasswordHash.recommended()
oauth = OAuth2PasswordBearer(tokenUrl="/auth/token")
Database = Annotated[Session, Depends(get_db)]


def secret() -> str:
    key = get_settings().jwt_secret.get_secret_value()
    if len(key.encode()) < 32:
        raise HTTPException(503, "Authentication is not configured")
    return key


def issue_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": str(user.id), "iat": now, "exp": now + timedelta(minutes=get_settings().access_token_expire_minutes)},
        secret(), algorithm=get_settings().algorithm,
    )


def unauthorized() -> HTTPException:
    return HTTPException(401, "Invalid credentials", headers={"WWW-Authenticate": "Bearer"})


def get_current_user(request: Request, token: Annotated[str, Depends(oauth)], db: Database) -> User:
    key = secret()
    try:
        claims = jwt.decode(token, key, algorithms=[get_settings().algorithm], options={"require": ["sub", "exp"]})
        user_id = int(claims["sub"])
    except (jwt.InvalidTokenError, ValueError):
        raise unauthorized() from None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized()
    request.state.authenticated_user_id = user.id
    return user


def log_action(db: Session, user_id: int, action: str, details: str) -> None:
    db.add(AuditLog(user_id=user_id, action=action, details=details))


class RoleChecker:
    def __init__(self, roles: list[str]):
        self.roles = frozenset(roles)

    def __call__(self, user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in self.roles:
            raise HTTPException(403, "دسترسی به این گزارش فقط برای مدیر مجاز است.")
        return user
