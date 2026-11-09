from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Actor, get_actor
from app.core.auth import check_password, make_token
from app.core.config import get_settings
from app.db.models import User
from app.db.session import get_db

router = APIRouter(tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.username == body.username.strip().lower()))
    if not check_password(body.password, u.password_hash if u else None) or not u:
        raise HTTPException(401, "Wrong username or password.")
    return {"token": make_token(u.id), "user": {"username": u.username, "name": u.name, "role": u.role},
            "approval_limit": get_settings().approval_limit}


@router.get("/auth/me")
def me(actor: Actor = Depends(get_actor)):
    return {"name": actor.name, "role": actor.role, "approval_limit": get_settings().approval_limit}
