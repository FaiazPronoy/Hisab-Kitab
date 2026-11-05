import hmac

from fastapi import Header, HTTPException, Query, status

from app.core.config import get_settings


def require_key(x_api_key: str | None = Header(None), api_key: str | None = Query(None, include_in_schema=False)):
    # EventSource cannot send headers, so the SSE route also accepts ?api_key=
    given = x_api_key or api_key or ""
    if not hmac.compare_digest(given, get_settings().api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid API key.")
