import sys
from types import ModuleType
import os

# WeasyPrint requer bibliotecas nativas GTK/Pango não disponíveis no Windows.
# Substitui o módulo inteiro por um stub antes de qualquer import do app.
def _stub_weasyprint():
    stub = ModuleType("weasyprint")

    class FakeHTML:
        def __init__(self, string="", **kwargs):
            pass

        def write_pdf(self):
            return b"%PDF-1.4 stub"

    stub.HTML = FakeHTML
    sys.modules["weasyprint"] = stub

if "weasyprint" not in sys.modules:
    _stub_weasyprint()

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
