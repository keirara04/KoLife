from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # reads env vars, falling back to the repo-root .env for local dev
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    meta_api_key: str = ""
    meta_base_url: str = "https://api.meta.ai/v1"
    orch_model: str = "muse-wonder-1.0"  # fallback muse-spark-1.3 @ max if Wonder unavailable
    worker_model: str = "muse-spark-1.3"
    baseten_api_key: str = ""
    baseten_model: str = "meta-models/muse-spark-open-1026"
    spend_cap_usd_total: float = 120
    spend_cap_usd_daily: float = 20
    database_url: str = "postgresql+asyncpg://kolife:kolife@localhost:5432/kolife"
    redis_url: str = "redis://localhost:6379/0"


settings = Settings()
