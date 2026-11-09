"""Adds or updates a reviewer.

    docker compose run --rm api python -m scripts.create_user nadia "Nadia Rahman" clerk <password>
"""
import sys

from sqlalchemy import select

from app.core.auth import hash_password
from app.db.models import User
from app.db.session import SessionLocal


def ensure_user(username: str, name: str, role: str, password: str) -> None:
    if role not in ("clerk", "approver"):
        raise SystemExit("role must be clerk or approver")
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.username == username.lower()))
        if u is None:
            u = User(username=username.lower())
            db.add(u)
        u.name, u.role, u.password_hash = name, role, hash_password(password)
        db.commit()


if __name__ == "__main__":
    if len(sys.argv) != 5:
        raise SystemExit(__doc__)
    ensure_user(*sys.argv[1:])
    print(f"saved {sys.argv[1]}")
