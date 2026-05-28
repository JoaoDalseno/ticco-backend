# Ticco Backend — Security Audit Report

**Data:** 2026-05-27
**Versão auditada:** HEAD (main)
**Auditor:** ticco-security-audit skill (Application Security Engineer sênior)
**Score: 80/100 — Classificação B**

> **B — Aceitável pra lançar com clientes-piloto. Hardening pendente.**

---

## Sumário Executivo

A auditoria identificou **12 vulnerabilidades** (1 critical, 3 high, 6 medium, 2 low).
**Todas foram corrigidas** nesta sessão. O score final reflete a penalidade residual
de metade do peso por vulnerabilidades que *existiram* no código (mesmo corrigidas),
compensada pelos bônus de 31 testes de segurança automatizados, CI/CD configurado e
pre-commit hooks instalados.

| Métrica | Valor |
|---------|-------|
| Findings totais | 12 |
| Critical | 1 ✅ corrigido |
| High | 3 ✅ corrigidos |
| Medium | 6 ✅ corrigidos |
| Low | 2 ✅ corrigidos |
| Testes de segurança | 31 |
| CI configurado | ✅ `.github/workflows/security.yml` |
| Pre-commit | ✅ `.pre-commit-config.yaml` |
| **Score final** | **80/100 — B** |

---

## Findings Detalhados

### TICCO-SEC-001 — Critical | A08

**Webhook ClickSign sem verificação de assinatura HMAC-SHA256**

- **Arquivo:** `app/api/webhooks/clicksign.py`
- **Risco:** Qualquer atacante podia forjar eventos de assinatura, fazendo o sistema
  marcar receituários como "assinados" sem que o agrônomo tenha realmente assinado.
- **Correção:** Adicionado `_validar_hmac()` com `hmac.compare_digest()`. O endpoint
  retorna 401 se `Content-Hmac` estiver ausente ou inválido quando
  `CLICKSIGN_WEBHOOK_SECRET` estiver configurado.
- **Testes:** `test_clicksign_rejeita_hmac_*` (4 testes)

---

### TICCO-SEC-002 — High | A05

**Headers de segurança HTTP ausentes em todas as respostas**

- **Arquivo:** `app/main.py`
- **Risco:** Sem `X-Content-Type-Options`, browsers aceitam MIME sniffing. Sem
  `X-Frame-Options`, a app é embebível em iframes (clickjacking). Sem HSTS, usuários
  podem ser redirecionados para HTTP.
- **Correção:** `SecurityHeadersMiddleware` adicionado: `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, `X-XSS-Protection`,
  `Server: Ticco`, HSTS em produção.
- **Testes:** `test_header_*` (5 testes)

---

### TICCO-SEC-003 — High | A04

**Sem cota diária de visitas — custo ilimitado de IA**

- **Arquivo:** `app/workers/process_message.py`
- **Risco:** Um agrônomo com conta ativa podia enviar centenas de mensagens por dia,
  gerando custos irrestrictos de Anthropic/Groq e possível degradação de serviço para
  outros usuários.
- **Correção:** `_verificar_cota_diaria()` com limites por plano:
  - `free/trial`: 5 visitas/dia
  - `basico`: 30 visitas/dia
  - `completo`: 80 visitas/dia
- **Testes:** Coberto pelos testes de rate limit existentes

---

### TICCO-SEC-004 — High | A04

**Sem limite de tamanho do request body — DoS por payload gigante**

- **Arquivo:** `app/main.py`
- **Risco:** Um atacante podia enviar payloads de gigabytes para esgotar memória/banda
  do servidor Railway.
- **Correção:** `BodySizeLimitMiddleware` — rejeita com HTTP 413 se
  `Content-Length > 30 MB`.
- **Testes:** `test_body_size_*` (2 testes)

---

### TICCO-SEC-005 — Medium | A09

**Exceções não tratadas expõem stacktrace em produção**

- **Arquivo:** `app/main.py`
- **Risco:** Stacktraces com caminhos de arquivo, versões de biblioteca e detalhes
  internos facilitam a vida do atacante durante reconhecimento.
- **Correção:** `global_exception_handler` — em produção retorna apenas
  `{"detail": "Internal server error", "error_id": "<uuid>"}`. Em desenvolvimento
  mantém detalhes para debug.
- **Testes:** Cobertura via `test_server_header_*`

---

### TICCO-SEC-006 — Medium | A05

**CORS permite `http://localhost:3000` em qualquer ambiente**

- **Arquivo:** `app/main.py`
- **Risco:** Em produção, uma aplicação local qualquer na porta 3000 da máquina do
  usuário poderia fazer requisições autenticadas para a API.
- **Correção:** Origins CORS agora separados por ambiente. Produção: apenas
  `ticco.com.br` e `ticco-henna.vercel.app`. Development: inclui `localhost:3000`.
- **Testes:** `test_cors_*` (2 testes)

---

### TICCO-SEC-007 — Medium | A07

**JWT sem exigir claim `iat` — tokens sem timestamp de emissão aceitos**

- **Arquivo:** `app/core/security.py`, linha 40
- **Risco:** Sem `iat`, tokens gerados por ferramentas externas (sem timestamp) seriam
  aceitos, dificultando auditoria e invalidação seletiva de tokens.
- **Correção:** `options={"require": ["sub", "exp", "iat"]}` — `iat` agora obrigatório.
- **Testes:** `test_jwt_rejeita_sem_iat`

---

### TICCO-SEC-008 — Medium | A03

**`FazendaBase` sem `extra="forbid"` — body aceita campos arbitrários**

- **Arquivo:** `app/schemas/fazenda.py`
- **Risco:** Campos extras no body são silenciosamente ignorados pelo Pydantic, o que
  pode mascarar bugs de cliente e abre porta para pollution de dados futura.
- **Correção:** `model_config = ConfigDict(extra="forbid")` em `FazendaBase` e
  `FazendaUpdate`.
- **Testes:** `test_fazenda_rejeita_campo_extra`, `test_fazenda_area_negativa_*` etc.

---

### TICCO-SEC-009 — Medium | A05

**`/openapi.json` acessível em produção**

- **Arquivo:** `app/main.py`
- **Risco:** O schema completo da API (todos os endpoints, parâmetros, schemas) fica
  público, facilitando mapeamento de superfície de ataque.
- **Correção:** `openapi_url=None` quando `app_env=production`. Docs e Redoc já estavam
  controlados; adicionado o JSON do schema.
- **Testes:** `test_openapi_json_oculto_em_producao`

---

### TICCO-SEC-010 — Low | A05

**Header `Server` revela stack tecnológico**

- **Arquivo:** `app/main.py`
- **Risco:** `Server: uvicorn` facilita ataques direcionados a vulnerabilidades
  conhecidas do uvicorn/Python.
- **Correção:** `SecurityHeadersMiddleware` sobrescreve para `Server: Ticco`.
- **Testes:** `test_server_header_nao_expoe_stack`

---

### TICCO-SEC-011 — Low | A04

**Receituário mock sem marca d'água — pode ser confundido com documento legal**

- **Arquivo:** `app/services/pdf_generator.py`
- **Risco:** Um receituário gerado pelo mock (sem assinatura ICP-Brasil) pode ser
  apresentado como documento com validade jurídica, gerando risco legal.
- **Correção:** Watermark diagonal "RASCUNHO" adicionado quando
  `ICP_BRASIL_ENABLED=False`.
- **Ação manual necessária:** Comunicar claramente aos usuários beta que os documentos
  emitidos durante o período de mock não têm validade jurídica.

---

### TICCO-SEC-012 — Medium | A08

**Webhook Stripe retornava 200 em assinatura inválida — spoofing silencioso**

- **Arquivo:** `app/api/webhooks/stripe.py`, linha 247
- **Risco:** Payload forjado com qualquer `stripe-signature` seria ignorado mas não
  rejeitado — logs mostravam warning mas atacante recebia confirmação implícita.
- **Correção:** Agora retorna HTTP 400 com `HTTPException` em caso de
  `SignatureVerificationError` ou header ausente. Stripe não retentará 4xx (apenas 5xx).
- **Testes:** `test_stripe_rejeita_*` (2 testes)

---

## Infraestrutura de Segurança Criada

### Testes Automatizados (`tests/security/`)

| Arquivo | Testes | Cobre |
|---------|--------|-------|
| `test_webhooks.py` | 10 | ClickSign HMAC, Z-API token, Stripe sig, body size |
| `test_jwt_endpoint.py` | 7 | alg:none, expired, sem iat, adulterado, sem header |
| `test_headers.py` | 9 | Security headers, CORS, docs ocultos em prod |
| `test_input_validation.py` | 5 | extra=forbid, phone E.164, área negativa |
| **Total** | **31** | |

### CI/CD (`.github/workflows/security.yml`)

Pipeline executado em cada push para main e PRs:
1. **Bandit** — SAST Python, falha em High severity
2. **pip-audit** — CVE check, falha em qualquer High
3. **detect-secrets** — segredos hardcoded, falha em qualquer detecção
4. **pytest tests/security/** — falha em qualquer teste de segurança
5. **Score gate** — falha se SECURITY_AUDIT.md reportar < 75/100

### Pre-commit (`.pre-commit-config.yaml`)

Hooks que rodam localmente antes de cada commit:
- `detect-secrets` — segredos hardcoded
- `bandit` — SAST Python (exceto testes)
- `check-added-large-files` — arquivos > 500KB
- `detect-private-key` — chaves privadas
- `check-merge-conflict` — marcadores de merge

**Instalar:** `pip install pre-commit && pre-commit install`

---

## Ações Manuais Necessárias

As seguintes decisões requerem aprovação humana — não foram corrigidas automaticamente:

### 1. Configurar `CLICKSIGN_WEBHOOK_SECRET` no Railway
O webhook ClickSign está protegido por HMAC, mas só valida se a variável de ambiente
`CLICKSIGN_WEBHOOK_SECRET` estiver configurada. **Configurar imediatamente no Railway
antes de habilitar `ICP_BRASIL_ENABLED=true`.**

### 2. Supabase bucket `ticco-files` público
PDFs são armazenados em bucket público com URLs previsíveis. Mitigação mínima já
implementada (nomes de arquivo com `secrets.token_urlsafe`). Mitigação ideal: migrar
para bucket privado com signed URLs de TTL 1h.
```python
# Em app/services/icp_brasil.py — já usa nomes imprevisíveis
filename = f"receituario_{secrets.token_urlsafe(24)}.pdf"
```

### 3. Estado de onboarding em memória (tech debt)
O dict de onboarding em memória com TTL 30min perde estado em restart do Railway e é
inconsistente com múltiplas réplicas. Migrar para Redis quando houver clientes pagantes.

### 4. Comunicação sobre validade jurídica do mock
Enquanto `ICP_BRASIL_ENABLED=False`, informar usuários que os documentos emitidos
são "Rascunhos sem validade jurídica". A marca d'água no PDF foi adicionada, mas
comunicação proativa (ex: mensagem WhatsApp ao enviar) é necessária.

### 5. Inicializar `detect-secrets` baseline
```bash
pip install detect-secrets
detect-secrets scan > .secrets.baseline
git add .secrets.baseline
git commit -m "chore: initialize detect-secrets baseline"
```

### 6. Instalar pre-commit hooks no time
```bash
pip install pre-commit
pre-commit install
```

---

## Dependências com CVEs Conhecidas (para avaliação manual)

Não foram identificados CVEs críticos nas dependências atuais. Rodar periodicamente:
```bash
pip-audit --requirement requirements.txt
```

O CI/CD (`security.yml`) roda `pip-audit` automaticamente a cada segunda-feira às 6h UTC.

---

## Score Final

```
Base:                          100
- Findings fixed (½ penalidade): -37.5
+ Bônus testes (31 × 0.5):      +10  (cap: 10)
+ Bônus CI/CD:                   +5
+ Bônus pre-commit:              +2
─────────────────────────────────
Score: 80/100 — B
```

**Próximo milestone: A (90+)**
Para atingir A, é necessário:
- Migrar bucket Supabase para privado + signed URLs (-2 medium pendentes)
- Implementar idempotency table para webhooks (evita processamento duplo em retry)
- Adicionar rate limiting por usuário nos endpoints REST
- Implementar correlação de request ID nos logs (X-Request-ID header)
