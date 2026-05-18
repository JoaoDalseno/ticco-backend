# Ticco — Backend

Backend da plataforma **Ticco**, um assistente de consultoria cafeicultora via WhatsApp + IA.

Agrônomos enviam relatos de visitas técnicas (texto ou áudio) pelo WhatsApp. A plataforma transcreve, estrutura via Claude, gera PDFs de relatório e receituário agronômico, e entrega tudo automaticamente.

---

## Stack

- **Python 3.11** + **FastAPI** + **Uvicorn**
- **PostgreSQL** (Supabase) via SQLAlchemy async + asyncpg
- **Alembic** para migrações
- **Claude** (Anthropic) — estruturação dos relatos
- **Groq Whisper** (primário) + **OpenAI Whisper** (fallback) — transcrição de áudio
- **xhtml2pdf** — geração de PDFs
- **Supabase Storage** — armazenamento dos PDFs
- **Z-API** — integração WhatsApp
- **Stripe** — gestão de assinaturas

---

## Estrutura

```
app/
├── api/
│   ├── health.py          # GET /health
│   ├── deps.py            # Dependências FastAPI
│   └── webhooks/
│       ├── whatsapp.py    # POST /webhooks/whatsapp (Z-API)
│       └── stripe.py      # POST /webhooks/stripe
├── core/                  # Ontologia e prompts
├── models/                # Models SQLAlchemy (Agronomo, Fazenda, Talhao, Visita, Receituario, Mensagem)
├── schemas/               # Schemas Pydantic
├── services/
│   ├── ai_processor.py    # Pipeline Claude (tool_use)
│   ├── pdf_generator.py   # Geração de PDFs com xhtml2pdf
│   ├── storage.py         # Upload Supabase Storage
│   ├── transcription.py   # Groq/OpenAI Whisper
│   └── whatsapp/
│       ├── zapi.py        # Cliente Z-API
│       └── onboarding.py  # Fluxo de cadastro via WhatsApp
├── workers/
│   └── process_message.py # Pipeline completo de processamento
├── config.py              # Settings via pydantic-settings
├── database.py            # Engine e sessão async
└── main.py                # App FastAPI + middlewares
alembic/                   # Migrações de banco
tests/                     # Testes pytest
```

---

## Fluxo principal

```
Agrônomo (WhatsApp)
       │
       ▼
  Z-API Webhook → POST /webhooks/whatsapp
       │
       ├─ Onboarding (número novo)
       │
       └─ Pipeline IA (agrônomo cadastrado)
              │
              ├── 1. Transcrição (Groq → OpenAI fallback)
              ├── 2. Claude estrutura o relato (tool_use)
              ├── 3. Resolve fazenda/talhão (fuzzy match)
              ├── 4. Persiste Visita no banco
              ├── 5. Gera PDF relatório → Supabase Storage
              ├── 6. Gera receituário agronômico (se houver produtos)
              └── 7. Envia PDFs ao agrônomo via WhatsApp
```

---

## Configuração

Copie `.env.example` para `.env` e preencha as variáveis:

```bash
cp .env.example .env
```

| Variável | Descrição |
|---|---|
| `DATABASE_URL` | Connection string PostgreSQL (Supabase) |
| `SUPABASE_URL` | URL do projeto Supabase |
| `SUPABASE_SERVICE_ROLE_KEY` | Chave service role do Supabase |
| `SUPABASE_BUCKET` | Nome do bucket de storage |
| `ANTHROPIC_API_KEY` | Chave da API Anthropic (Claude) |
| `GROQ_API_KEY` | Chave da API Groq (Whisper) |
| `OPENAI_API_KEY` | Chave da API OpenAI (Whisper fallback) |
| `ZAPI_INSTANCE_ID` | ID da instância Z-API |
| `ZAPI_TOKEN` | Token Z-API |
| `ZAPI_SECURITY_TOKEN` | Security token Z-API (opcional) |
| `STRIPE_SECRET_KEY` | Chave secreta Stripe |
| `STRIPE_WEBHOOK_SECRET` | Secret do webhook Stripe |
| `JWT_SECRET` | Segredo para geração de JWT |

---

## Rodando localmente

```bash
# Instalar dependências
pip install -r requirements.txt

# Rodar migrações
alembic upgrade head

# Iniciar servidor
uvicorn app.main:app --reload
```

API disponível em `http://localhost:8000`
Documentação Swagger em `http://localhost:8000/docs` (apenas em `APP_ENV=development`)

---

## Docker

```bash
docker build -t ticco-backend .
docker run --env-file .env -p 8000:8000 ticco-backend
```

Ou com docker-compose:

```bash
docker-compose up
```

---

## Testes

```bash
pytest
```

---

## Deploy (Railway)

O projeto está configurado para deploy automático via `railway.toml`. Basta conectar o repositório no Railway e configurar as variáveis de ambiente no painel.

O healthcheck é feito em `GET /health` — verifica conectividade com o banco de dados.
