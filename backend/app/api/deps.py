import hmac

from fastapi import Header, HTTPException, Query, status

from app.core.config import get_settings


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
