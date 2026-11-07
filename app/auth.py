from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
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
        claims = jwt.decode(token, key, algorithms=[get_settings().algorithm], options={"require": ["sub", "exp", "iat"]})
        sub = claims["sub"]
        if not isinstance(sub, str) or not sub.isascii() or not sub.isdecimal() or len(sub) > 19:
            raise ValueError("Invalid subject")
        user_id = int(sub)
        if not 0 < user_id <= 9223372036854775807 or str(user_id) != sub:
            raise ValueError("Invalid subject")
    except (jwt.InvalidTokenError, ValueError, TypeError, OverflowError):
        raise unauthorized() from None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized()
    request.state.authenticated_user_id = user.id
    return user


def peer_ip(request: Request) -> str | None:
    try:
        host = request.client.host if request.client else ""
        if "%" in host:
            return None
        return ip_address(host).compressed
    except ValueError:
        return None


def log_action(db: Session, user_id: int | None, action: str, details: str | None = None,
               ip_address: str | None = None, request_id: str | None = None) -> None:
    # Caller owns the transaction so business changes and audit remain atomic.
    db.add(AuditLog(user_id=user_id, action=action, details=details,
                    ip_address=ip_address, request_id=request_id))


class RoleChecker:
    def __init__(self, roles: list[str]):
        self.roles = frozenset(roles)

    def __call__(self, user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in self.roles:
            raise HTTPException(403, "دسترسی به این گزارش فقط برای مدیر مجاز است.")
        return user
