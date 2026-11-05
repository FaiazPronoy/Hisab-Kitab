"""Regenerates PROMPTS.md from the prompt constants so the two never drift.

python -m scripts.gen_prompts_md > PROMPTS.md"""
import json

from app.pipeline.extract import prompts
from app.pipeline.extract.schema import InvoiceOut

SECTIONS = [
    ("Extraction", "EXTRACT_VERSION", ["EXTRACT_SYSTEM", "EXTRACT_USER"]),
    ("Second pass for one missing field", "MISSING_VERSION", ["MISSING_USER"]),
    ("Invoice boundary", "BOUNDARY_VERSION", ["BOUNDARY_USER"]),
    ("Spreadsheet columns", "COLUMNS_VERSION", ["COLUMNS_USER"]),
    ("Vision fallback", "VISION_VERSION", ["VISION_USER"]),
]


def main():
    out = ["# Runtime prompts", "",
           "Every prompt the system sends to the LLM, generated from `backend/app/pipeline/extract/prompts.py`.",
           "The version string is part of the cache key and is logged with each call. Values in braces are filled in at runtime.", ""]
    for title, ver, keys in SECTIONS:
        out += [f"## {title} (`{getattr(prompts, ver)}`)", ""]
        for k in keys:
            out += [f"`{k}`", "", "```text", getattr(prompts, k).strip(), "```", ""]
    out += ["## Response schema (extraction)", "", "Sent as the structured-output schema. Every scalar field has the same shape.", "",
            "```json", json.dumps(InvoiceOut.model_json_schema(), indent=2), "```", ""]
    print("\n".join(out))


if __name__ == "__main__":
    main()
