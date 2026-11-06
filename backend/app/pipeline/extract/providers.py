"""LLM access. Every call goes through call_structured(), which caches by
(prompt version, model, input), enforces a spend cap, rate-limits and logs
tokens and cost. Only IDs and counts are logged, never document text."""
import hashlib
import json
import logging
import threading
import time

from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.core.logging import log as jlog

logger = logging.getLogger(__name__)

# USD per 1M tokens (input, output), checked against the Gemini pricing page on 2026-11-06
PRICES = {
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "mock": (0.0, 0.0),
}


class LlmError(Exception):
    def __init__(self, message: str, transient: bool):
        super().__init__(message)
        self.transient = transient


class BudgetExceeded(LlmError):
    def __init__(self):
        super().__init__("LLM budget reached", transient=False)


class TokenBucket:
    def __init__(self, per_minute: int):
        self.rate = per_minute / 60.0
        self.capacity = max(per_minute, 1)
        self.tokens = float(self.capacity)
        self.last = time.monotonic()
        self.lock = threading.Lock()

    def take(self):
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
                self.last = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
            time.sleep(0.2)


class Provider:
    name = "base"

    def generate(self, model: str, system: str, user: str, schema: type[BaseModel], image: bytes | None) -> tuple[str, int, int]:
        """Returns (json text, input tokens, output tokens)."""
        raise NotImplementedError


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(self, api_key: str):
        from google import genai
        self.client = genai.Client(api_key=api_key)

    def generate(self, model, system, user, schema, image):
        from google.genai import errors, types
        parts = [user]
        if image is not None:
            parts = [types.Part.from_bytes(data=image, mime_type="image/png"), user]
        cfg = types.GenerateContentConfig(
            system_instruction=system or None, temperature=0,
            response_mime_type="application/json", response_schema=schema,
        )
        try:
            r = self.client.models.generate_content(model=model, contents=parts, config=cfg)
        except errors.APIError as e:
            code = getattr(e, "code", 0) or 0
            raise LlmError(f"gemini {code}", transient=code in (408, 429) or code >= 500)
        except Exception as e:  # network errors and timeouts
            raise LlmError(type(e).__name__, transient=True)
        u = r.usage_metadata
        return r.text or "{}", getattr(u, "prompt_token_count", 0) or 0, getattr(u, "candidates_token_count", 0) or 0


class MockProvider(Provider):
    """Offline provider for tests and runs without a key. Recorded answers
    can be registered by input hash; otherwise it falls back to a simple
    label parser (app.pipeline.extract.mock_parser)."""
    name = "mock"
    recorded: dict[str, str] = {}

    def generate(self, model, system, user, schema, image):
        key = hashlib.sha256(user.encode()).hexdigest()
        if key in self.recorded:
            out = self.recorded[key]
            if isinstance(out, Exception):
                raise out
            return out, len(user) // 4, len(out) // 4
        from app.pipeline.extract import mock_parser
        out = mock_parser.answer(schema, user)
        return out, len(user) // 4, len(out) // 4


_lock = threading.Lock()
_state = {"spent": 0.0}
_bucket: TokenBucket | None = None
_sem: threading.Semaphore | None = None


def get_provider() -> Provider:
    s = get_settings()
    if s.llm_provider == "gemini" and s.gemini_api_key:
        return GeminiProvider(s.gemini_api_key)
    return MockProvider()


def _limits():
    global _bucket, _sem
    if _bucket is None:
        s = get_settings()
        _bucket = TokenBucket(s.llm_rate_per_minute)
        _sem = threading.Semaphore(s.llm_max_concurrency)
    return _bucket, _sem


def cost_of(model: str, tin: int, tout: int) -> float:
    pin, pout = PRICES.get(model, (0.0, 0.0))
    return (tin * pin + tout * pout) / 1_000_000


def call_structured(db, *, purpose: str, version: str, schema: type[BaseModel], user: str,
                    system: str = "", image: bytes | None = None, vision: bool = False) -> BaseModel | None:
    """Returns a validated schema instance, or None after one retry on bad JSON."""
    from app.db.models import LlmCall

    s = get_settings()
    provider = get_provider()
    model = "mock" if provider.name == "mock" else (s.llm_vision_model if vision else s.llm_model)
    h = hashlib.sha256()
    for part in (version, model, system, user):
        h.update(part.encode())
    if image:
        h.update(image)
    key = h.hexdigest()

    hit = db.query(LlmCall).filter_by(input_hash=key, cached=False).first() if db is not None else None
    if hit and hit.response is not None:
        try:
            out = schema.model_validate(hit.response)
            db.add(LlmCall(prompt_version=version, model=model, purpose=purpose, input_hash=key, cached=True))
            return out
        except ValidationError:
            pass

    bucket, sem = _limits()
    for attempt in (1, 2, 3):
        with _lock:
            if _state["spent"] >= s.llm_budget_usd:
                raise BudgetExceeded()
        bucket.take()
        t0 = time.monotonic()
        try:
            with sem:
                text, tin, tout = provider.generate(model, system, user, schema, image)
        except LlmError as e:
            if not e.transient or attempt == 3:
                raise
            time.sleep(2.0 * attempt)
            continue
        ms = int((time.monotonic() - t0) * 1000)
        cost = cost_of(model, tin, tout)
        with _lock:
            _state["spent"] += cost
        try:
            out = schema.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValidationError):
            out = None
        if db is not None:
            db.add(LlmCall(prompt_version=version, model=model, purpose=purpose, input_hash=key,
                           response=out.model_dump() if out else None,
                           tokens_in=tin, tokens_out=tout, cost=cost, latency_ms=ms, cached=False))
        jlog(logger, "llm call", stage=purpose, model=model, tokens_in=tin, tokens_out=tout, attempt=attempt,
             duration_ms=ms, cached=False)
        if out is not None:
            return out
    return None
