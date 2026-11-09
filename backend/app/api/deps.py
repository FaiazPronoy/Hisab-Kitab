import hmac

from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import read_token
from app.core.config import get_settings
from app.db.models import User
from app.db.session import get_db


def require_key(x_api_key: str | None = Header(None)) -> str:
    if not x_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid API key.")
    try:
        given_bytes = x_api_key.encode("ascii")
        expected_bytes = get_settings().api_key.encode("ascii")
    except (UnicodeEncodeError, UnicodeDecodeError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid API key.")
    if not hmac.compare_digest(given_bytes, expected_bytes):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid API key.")
    return x_api_key


def require_browser_key(x_api_key: str | None = Header(None), api_key: str | None = Query(None, include_in_schema=False)) -> str:
    raw = x_api_key or api_key
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid API key.")
    try:
        given_bytes = raw.encode("ascii")
        expected_bytes = get_settings().api_key.encode("ascii")
    except (UnicodeEncodeError, UnicodeDecodeError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid API key.")
    if not hmac.compare_digest(given_bytes, expected_bytes):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid API key.")
    return raw


class Actor:
    def __init__(self, name: str, role: str, user_id: int | None = None):
        self.name, self.role, self.user_id = name, role, user_id


def get_actor(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> Actor:
    """The signed-in reviewer. With REQUIRE_LOGIN=false (eval runs, scripts)
    a request without a token acts as the API itself."""
    if authorization and authorization.lower().startswith("bearer "):
        uid = read_token(authorization[7:].strip())
        u = db.get(User, uid) if uid is not None else None
        if u:
            return Actor(u.name, u.role, u.id)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has expired. Sign in again.")
    if not get_settings().require_login:
        return Actor("api", "approver")
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to change or approve invoices.")
