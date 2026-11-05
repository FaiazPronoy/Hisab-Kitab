# AI-assisted development

I used [TOOLS USED] while building this project.

**What the tools helped with:** scaffolding of the repository layout, boilerplate for the FastAPI routes, SQLAlchemy models and Next.js pages, first drafts of test cases and of the documentation, and the synthetic invoice templates.

**What I designed and decided myself:** the architecture (one Python stack, Celery with an atomic page counter, one PostgreSQL store for relational data, full-text and vectors), the grounding rule that removes any value whose evidence is not in the document, the validation rules and every tolerance and threshold in `config/validation.yaml`, the review routing policy, the duplicate tiers, the reconciliation matching cascade, and the evaluation method (frozen test split, planted problems, degradation tiers, metrics through the public API).

**How I checked the generated code:** I read every file before committing it, ran the unit and integration tests against a real PostgreSQL database, and fixed the defects they found (for example, fuzzy quote matching accepted an amount that differed from the printed one by a single digit; numbers now have to appear on the page exactly). Every number in the README and EVALUATION.md comes from `make eval` or `make bigpdf` on my machine.

The runtime prompts the system itself sends to an LLM are listed in `PROMPTS.md`.
