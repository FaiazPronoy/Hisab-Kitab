from functools import lru_cache
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_key: str = "local-dev-key"
    cors_origins: str = "http://localhost:3000"

    database_url: str = "postgresql+psycopg://docintel:docintel@localhost:5432/docintel"
    redis_url: str = "redis://localhost:6379/0"
    storage_dir: str = "./data/storage"

    llm_provider: str = "mock"
    llm_model: str = "gemini-3.5-flash-lite"
    llm_vision_model: str = "gemini-3.5-flash"
    gemini_api_key: str = ""
    llm_budget_usd: float = 2.0
    llm_max_concurrency: int = 4
    llm_rate_per_minute: int = 15
    # a 30-line invoice with a quote per value needs more than 4096 tokens of JSON
    llm_max_output_tokens: int = 16384

    max_upload_mb: int = 60
    upload_rate_limit: str = "30/minute"
    max_files_per_request: int = 50
    max_pages: int = 1500
    max_sheet_rows: int = 200_000
    max_image_pixels: int = 60_000_000
    render_dpi: int = 220
    page_batch_size: int = 20
    page_time_limit_s: int = 60

    # reviewers sign in; corrections and approvals carry their name
    require_login: bool = True
    auth_secret: str = "change-me-local-dev-secret"
    token_hours: int = 12
    # invoices at or above this total (in their own currency) need an approver
    approval_limit: float = 10000
    supplier_memory: bool = True
    # the paying company, written into pain.001 payment files
    payer_name: str = "Demo Trading Ltd"
    payer_iban: str = "GB33BUKB20201555555555"
    payer_bic: str = "BUKBGB22"

    # Celery runs tasks inline when true (tests and the eval runner).
    celery_eager: bool = False

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def validation_config() -> dict:
    with open(CONFIG_DIR / "validation.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)
