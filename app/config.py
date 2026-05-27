from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # App
    app_env: str = "development"
    app_port: int = 8000
    app_base_url: str = "http://localhost:8000"
    log_level: str = "INFO"

    # Database (Supabase — asyncpg)
    database_url: str

    # Supabase Storage
    supabase_url: str
    supabase_service_role_key: str
    supabase_bucket: str = "ticco-files"

    # Anthropic (Claude)
    anthropic_api_key: str

    # Groq (Whisper — primário)
    groq_api_key: str

    # OpenAI (Whisper — fallback)
    openai_api_key: str

    # WhatsApp — Z-API
    zapi_instance_id: str
    zapi_token: str
    zapi_base_url: str = "https://api.z-api.io"
    zapi_security_token: str = ""

    # Frontend (usado em redirects do Stripe Checkout)
    frontend_url: str = "http://localhost:3000"

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    # Price IDs do Stripe Dashboard → Products → Prices
    stripe_price_basico: str = ""
    stripe_price_completo: str = ""

    # JWT
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 10080  # 7 dias

    # Número do fundador para notificações de novos cadastros
    founder_phone: str = ""

    # Emails públicos do produto
    contact_email: str = "ola@useticco.com"
    founder_email: str = "joao@useticco.com"
    noreply_email: str = "noreply@useticco.com"

    # Chave secreta para o dashboard admin (header X-Admin-Key)
    admin_secret_key: str = ""

    # ── ICP-Brasil / ClickSign ────────────────────────────────────────────────
    # Feature flag — False = mock, True = ClickSign real
    icp_brasil_enabled: bool = False
    clicksign_api_key: str = ""
    clicksign_base_url: str = "https://app.clicksign.com/api/v1"
    clicksign_webhook_secret: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

# Limites de fazendas por plano (regra de negócio — não configurável via env)
LIMITE_FAZENDAS: dict[str, int] = {
    "free": 1,
    "basico": 10,
    "completo": 20,
}
