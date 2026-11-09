from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text

from app.api.deps import require_key
from app.api.routers import auth as auth_router
from app.api.routers import documents, invoices, metrics, payments, reconcile, search
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.core.ratelimit import limiter
from app.db.session import engine

setup_logging()
s = get_settings()

app = FastAPI(title="Document Intelligence System", version="1.0.0", docs_url="/docs")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=s.cors_list, allow_methods=["*"], allow_headers=["*"])


auth = [Depends(require_key)]
for r in (auth_router.router, invoices.router, search.router, reconcile.router, metrics.router, payments.router):
    app.include_router(r, prefix="/api/v1", dependencies=auth)
app.include_router(documents.router, prefix="/api/v1")


@app.get("/api/v1/health")
def health():
    with engine.connect() as c:
        c.execute(text("SELECT 1"))
    return {"status": "ok"}

