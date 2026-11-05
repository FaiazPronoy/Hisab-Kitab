import json
import logging
import sys
import time

# Only these keys are written. Document text, field values and prompts never are.
SAFE_KEYS = {"document_id", "invoice_id", "page_no", "stage", "status", "duration_ms", "rule_code",
             "error_code", "task", "attempt", "model", "tokens_in", "tokens_out", "cached", "count"}


class JsonFormatter(logging.Formatter):
    def format(self, record):
        out = {"ts": round(time.time(), 3), "level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        for k, v in getattr(record, "ctx", {}).items():
            if k in SAFE_KEYS:
                out[k] = str(v) if not isinstance(v, (int, float, bool)) else v
        return json.dumps(out)


def setup_logging():
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(logging.INFO)


def log(logger: logging.Logger, msg: str, **ctx):
    logger.info(msg, extra={"ctx": ctx})
