"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LLM
    deepseek_api_key: str = ""
    openai_api_key: str = ""

    # Database (Neon)
    database_url: str = "postgresql+asyncpg://localhost:5432/oneiros"

    # Redis (Upstash)
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""

    # Storage (Cloudflare R2)
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = "oneiros-images"
    r2_public_url: str = ""

    # Image generation
    fal_key: str = ""

    # Symbol context search (Serper — Google SERP API)
    serper_api_key: str = ""

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    # App
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
