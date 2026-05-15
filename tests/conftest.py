import os

# Define vars de ambiente de teste ANTES de qualquer import do app,
# pois settings é instanciado no nível do módulo.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("ZAPI_INSTANCE_ID", "test-instance")
os.environ.setdefault("ZAPI_TOKEN", "test-token")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-with-enough-length-for-hs256")

pytest_plugins = ("pytest_asyncio",)
