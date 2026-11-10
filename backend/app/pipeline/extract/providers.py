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
    "gemini-3.6-flash": (1.50, 7.50),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3-flash-preview": (0.50, 3.00),
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
        from google.genai import types
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=45000))

    def generate(self, model, system, user, schema, image):
        from google.genai import errors, types
        parts = [user]
        if image is not None:
            parts = [types.Part.from_bytes(data=image, mime_type="image/png"), user]
        cfg = types.GenerateContentConfig(
            system_instruction=system or None, temperature=0,
            response_mime_type="application/json", response_schema=schema,
            max_output_tokens=get_settings().llm_max_output_tokens,
        )
        try:
            r = self.client.models.generate_content(model=model, contents=parts, config=cfg)
        except errors.APIError as e:
            code = getattr(e, "code", 0) or 0
            msg = str(e).lower()
            is_daily = "perday" in msg or "requests per day" in msg
            raise LlmError(f"gemini {code}", transient=(code in (408, 429) or code >= 500) and not is_daily)
        except Exception as e:  # network errors and timeouts
            raise LlmError(type(e).__name__, transient=True)
        u = getattr(r, "usage_metadata", None)
        thoughts = getattr(u, "thoughts_token_count", 0) or 0
        tout = (getattr(u, "candidates_token_count", 0) or 0) + thoughts
        tin = getattr(u, "prompt_token_count", 0) or 0

        def _record_billed_tokens():
            if tin or tout:
                cost = cost_of(model, tin, tout)
                record_spent(None, cost)

        cands = getattr(r, "candidates", None)
        if cands and len(cands) > 0:
            finish = getattr(cands[0], "finish_reason", None)
            finish_str = getattr(finish, "name", str(finish)).upper()
            if finish and finish_str in (
                "SAFETY", "BLOCKED", "PROHIBITED_CONTENT", "SPII",
                "IMAGE_SAFETY", "IMAGE_PROHIBITED_CONTENT", "IMAGE_RECITATION",
                "IMAGE_OTHER", "BLOCKLIST", "LANGUAGE", "RECITATION",
                "MALFORMED_FUNCTION_CALL", "TOO_MANY_TOOL_CALLS", "UNEXPECTED_TOOL_CALL",
            ):
                _record_billed_tokens()
                raise LlmError(f"gemini content blocked or failed: {finish_str}", transient=False)
            if finish and finish_str == "MAX_TOKENS":
                _record_billed_tokens()
                raise LlmError("gemini response truncated: max tokens reached", transient=False)
        text = (r.text or "").strip()
        if not text:
            _record_billed_tokens()
            raise LlmError("gemini returned empty response", transient=True)
        return text, tin, tout


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
_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        try:
            import redis
            _redis_client = redis.Redis.from_url(get_settings().redis_url)
        except Exception:
            _redis_client = False
    return _redis_client if _redis_client is not False else None


SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local clear_before = now - window
redis.call('ZREMRANGEBYSCORE', key, 0, clear_before)
local current = redis.call('ZCARD', key)
if current < limit then
    redis.call('ZADD', key, now, ARGV[4])
    redis.call('EXPIRE', key, window * 2)
    return 1
else
    return 0
end
"""


def _record_llm_call(**kw):
    try:
        from app.db.models import LlmCall
        from app.db.session import SessionLocal
        with SessionLocal() as s:
            s.add(LlmCall(**kw))
            s.commit()
    except Exception:
        pass


def get_total_spent(db) -> float:
    rc = _get_redis()
    if rc:
        try:
            v = rc.get("docintel:llm:spent")
            if v is not None:
                return float(v)
            if db is not None:
                from sqlalchemy import func, select
                from app.db.models import LlmCall
                val = db.scalar(select(func.coalesce(func.sum(LlmCall.cost), 0.0)))
                spent = float(val or 0.0)
                rc.set("docintel:llm:spent", spent)
                return spent
        except Exception:
            pass
    if db is not None:
        try:
            from sqlalchemy import func, select
            from app.db.models import LlmCall
            val = db.scalar(select(func.coalesce(func.sum(LlmCall.cost), 0.0)))
            if val is not None:
                return float(val)
        except Exception:
            pass
    with _lock:
        return _state["spent"]


def reset_budget_counter():
    with _lock:
        _state["spent"] = 0.0
    rc = _get_redis()
    if rc:
        try:
            rc.delete("docintel:llm:spent")
        except Exception:
            pass


def record_spent(db, cost: float):
    with _lock:
        _state["spent"] += cost
    rc = _get_redis()
    if rc:
        try:
            if not rc.exists("docintel:llm:spent"):
                get_total_spent(db)
            rc.incrbyfloat("docintel:llm:spent", cost)
        except Exception:
            pass


def _take_token():
    s = get_settings()
    rc = _get_redis()
    if rc:
        try:
            for _ in range(60):
                now = time.time()
                member = f"{now}:{time.monotonic()}"
                allowed = rc.eval(SLIDING_WINDOW_LUA, 1, "docintel:llm:ratelimit", str(now), 60, s.llm_rate_per_minute, member)
                if allowed == 1:
                    return
                time.sleep(1.0)
            raise LlmError("LLM rate limit wait timed out (sliding window full)", transient=True)
        except LlmError:
            raise
        except Exception:
            pass
    bucket, _ = _limits()
    bucket.take()


_provider_cache: dict[str, Provider] = {}


def get_provider() -> Provider:
    s = get_settings()
    if s.llm_provider == "gemini":
        if not s.gemini_api_key:
            raise ValueError("LLM_PROVIDER=gemini requires GEMINI_API_KEY")
        if s.llm_model not in PRICES:
            raise ValueError(f"Unknown or unconfigured model '{s.llm_model}' in PRICES table")
        if s.llm_vision_model not in PRICES:
            raise ValueError(f"Unknown or unconfigured vision model '{s.llm_vision_model}' in PRICES table")
        if "gemini" not in _provider_cache:
            _provider_cache["gemini"] = GeminiProvider(s.gemini_api_key)
        return _provider_cache["gemini"]
    elif s.llm_provider == "mock":
        if "mock" not in _provider_cache:
            _provider_cache["mock"] = MockProvider()
        return _provider_cache["mock"]
    else:
        raise ValueError(f"Unknown LLM provider '{s.llm_provider}'")


def _limits():
    global _bucket, _sem
    if _bucket is None:
        s = get_settings()
        _bucket = TokenBucket(s.llm_rate_per_minute)
        _sem = threading.Semaphore(s.llm_max_concurrency)
    return _bucket, _sem


def cost_of(model: str, tin: int, tout: int) -> float:
    if model not in PRICES:
        raise ValueError(f"Unknown pricing for model '{model}'")
    pin, pout = PRICES[model]
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

    hit = None
    try:
        if db is not None:
            hit = db.query(LlmCall).filter(
                LlmCall.input_hash == key,
                LlmCall.cached.is_(False),
                LlmCall.response.is_not(None)
            ).order_by(LlmCall.id.desc()).first()
        else:
            from app.db.session import SessionLocal
            with SessionLocal() as s_db:
                hit = s_db.query(LlmCall).filter(
                    LlmCall.input_hash == key,
                    LlmCall.cached.is_(False),
                    LlmCall.response.is_not(None)
                ).order_by(LlmCall.id.desc()).first()
    except Exception:
        pass
    if hit and hit.response is not None:
        try:
            out = schema.model_validate(hit.response)
            _record_llm_call(prompt_version=version, model=model, purpose=purpose, input_hash=key, cached=True)
            return out
        except ValidationError:
            pass

    curr_user = user
    bad_json_retries = 0
    _, sem = _limits()
    for attempt in (1, 2, 3, 4):
        if provider.name != "mock":
            if get_total_spent(db) >= s.llm_budget_usd:
                raise BudgetExceeded()
            _take_token()
        t0 = time.monotonic()
        try:
            with sem:
                text, tin, tout = provider.generate(model, system, curr_user, schema, image)
        except LlmError as e:
            if not e.transient or attempt == 4:
                raise
            time.sleep(5.0 * (2 ** (attempt - 1)))
            continue
        ms = int((time.monotonic() - t0) * 1000)
        cost = cost_of(model, tin, tout)
        record_spent(db, cost)
        try:
            out = schema.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValidationError):
            out = None
        _record_llm_call(prompt_version=version, model=model, purpose=purpose, input_hash=key,
                         response=out.model_dump() if out else None,
                         tokens_in=tin, tokens_out=tout, cost=cost, latency_ms=ms, cached=False)
        jlog(logger, "llm call", stage=purpose, model=model, tokens_in=tin, tokens_out=tout, attempt=attempt,
             duration_ms=ms, cached=False)
        if out is not None:
            return out
        # Spec: one retry on bad JSON
        if bad_json_retries == 0:
            bad_json_retries += 1
            curr_user = user + "\n\nCRITICAL: Respond ONLY with valid JSON conforming strictly to the requested schema."
            continue
        break
    return None
