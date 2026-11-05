from app.core.config import validation_config

BLOCKING = {"critical", "error"}


def route(findings: list[dict], meta: dict, pages_failed: int = 0, flags: list[str] | None = None) -> str:
    """needs_review or auto_validated. Kept in one place so the policy is
    easy to read and test."""
    cfg = validation_config()
    flags = flags or []
    if any(f["severity"] in BLOCKING for f in findings):
        return "needs_review"
    if sum(f["severity"] == "warning" for f in findings) > cfg["routing"]["max_warnings"]:
        return "needs_review"
    for k in cfg["key_fields"]:
        m = meta.get(k) or {}
        if m.get("value_norm") in (None, "") and m.get("source") != "user":
            return "needs_review"
    if pages_failed or "suspicious_content" in flags:
        return "needs_review"
    if any(f["rule_code"].startswith("DUP_") for f in findings):
        return "needs_review"
    return "auto_validated"
