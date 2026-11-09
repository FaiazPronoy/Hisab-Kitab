"""Password hashing and signed session tokens, stdlib only. A token is
base64(json payload) + "." + HMAC-SHA256 of that string."""
import base64
import hashlib
import hmac
import json
import os
import logging
import secrets
import time
from functools import lru_cache

from app.core.config import get_settings

SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    key = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **SCRYPT)
    return f"scrypt${salt.hex()}${key.hex()}"


DUMMY = hash_password("not a real password")


def check_password(password: str, stored: str | None) -> bool:
    """stored None still runs scrypt, so a missing user takes as long as a wrong password."""
    try:
        _, salt, key = (stored or DUMMY).split("$")
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), dklen=32, **SCRYPT)
    except ValueError:
        return False
    return stored is not None and hmac.compare_digest(got.hex(), key)


@lru_cache
def _secret() -> bytes:
    s = get_settings().auth_secret
    if len(s) < 32 or s.startswith("change-me"):
        # a guessable secret would let anyone mint an approver session
        logging.getLogger(__name__).warning("AUTH_SECRET is unset or weak; using a random one, sessions end on restart")
        return secrets.token_bytes(32)
    return s.encode()


def _sign(body: str) -> str:
    return hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()


def make_token(user_id: int, now: float | None = None) -> str:
    exp = int((now or time.time()) + get_settings().token_hours * 3600)
    body = base64.urlsafe_b64encode(json.dumps({"uid": user_id, "exp": exp}).encode()).decode()
    return f"{body}.{_sign(body)}"


def read_token(token: str) -> int | None:
    try:
        body, sig = token.rsplit(".", 1)
    except ValueError:
        return None
    if not hmac.compare_digest(sig, _sign(body)):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(body.encode()))
    except ValueError:
        return None
    if data.get("exp", 0) < time.time():
        return None
    return data.get("uid")
