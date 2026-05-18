# Cerebras Cloud — Signup & Setup

**Status:** adapter implementado em `src/providers/base.py` (`CerebrasProvider`).
Falta apenas a API key — passos abaixo.

## Por que Cerebras

| | DeepSeek V4 Pro (atual) | **Cerebras Llama 3.3 70B** |
|---|---|---|
| Custo | $0.87 / 1M input | **$0 (free tier)** |
| Quota | Pago, sem limite | 1M tokens/dia, 30 RPM |
| Velocidade | ~50-80 tok/s | **~700 tok/s** (10× mais rápido) |
| Context window | 1M | 8K (limitação do free tier) |
| Modelo | DeepSeek V4 Pro | Llama 3.3 70B / Qwen 3 32B |

**1M tokens/dia** ≈ 250 conversas DEEP por dia. Cobre quase tudo que hoje vai pro DeepSeek pago. Trade-off: contexto curto — mantém Gemini 2.5 Flash para long-context.

## Signup (3 minutos)

1. **Acesse:** https://cloud.cerebras.ai/
2. **Sign up** com Google, GitHub, ou email (qualquer um — não pede cartão)
3. Confirme o email (se for email signup)
4. Login → menu lateral → **API Keys**
5. Click **Create API Key** → dê um nome (ex: `seeker-bot-local`)
6. **Copie a key** (formato: `csk-...`) — só aparece uma vez

## Configuração no Seeker.Bot

Edite `config/.env`:

```bash
CEREBRAS_API_KEY=csk-cole-sua-key-aqui
```

Reinicie o bot:

```powershell
taskkill /F /PID 17920    # ou o PID atual
python -m src
```

Verificar que carregou:

```
grep "cerebras" logs/manual_restart.log  # deve aparecer no init
```

## Modelos disponíveis (free tier, mai/2026)

| Tag | Params | Use case |
|---|---|---|
| `llama-3.3-70b` | 70B | Generalista (DEEP role no router) |
| `llama-3.1-8b` | 8B | Latência mínima, ~1500 tok/s |
| `qwen-3-32b` | 32B | SYNTHESIS, code, multilíngue |
| `qwen-3-coder-32b` | 32B | Especialista em código |

Já cadastrados no Seeker:
- `CEREBRAS_LLAMA_70B` → `CognitiveRole.DEEP` (primário)
- `CEREBRAS_QWEN_32B` → `CognitiveRole.SYNTHESIS`

## Monitoramento de quota

A Cerebras tem dashboard em https://cloud.cerebras.ai/ → **Usage**.
1M tokens/dia reseta às 00:00 UTC.

Se hit 429 (rate limit ou daily cap), o cascade já cai automaticamente para o próximo tier (NVIDIA DeepSeek V3.2 → Gemini → DeepSeek paid) via circuit breaker por modelo (T-03 fix).

## Rollback

Se Cerebras der problema, basta apagar a linha `CEREBRAS_API_KEY=` ou comentar com `#`. Como o adapter está em primeira posição no array `CognitiveRole.DEEP`, sem key ele falha imediatamente e o cascade passa pro próximo.

Para remover do código permanentemente: remover `CEREBRAS_LLAMA_70B` e `CEREBRAS_QWEN_32B` dos arrays em `config/models.py` linhas ~393 e ~407.
