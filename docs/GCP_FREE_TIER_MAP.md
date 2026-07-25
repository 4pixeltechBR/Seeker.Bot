# Google Cloud Platform — Mapeamento de Free Tier

**Chave:** `<redacted: ver config/.env>`
**Env var:** `GOOGLE_CLOUD_API_KEY` (também exposta como `YOUTUBE_API_KEY` para compat)

Data de referência: jul/2026

---

## Tabela de free tier por serviço

| Serviço | Free Tier | Custo após | Onde usar no Seeker | Prioridade |
|---------|-----------|-----------|---------------------|------------|
| **YouTube Data API v3** | **10.000 units/dia** | Free (sem cobrança) | `specialist_skill/youtube_api.py` (substitui yt-dlp) | ✅ **Crítico** |
| **Cloud Vision API** | **1.000 units/mês** | $1.50/1K units | `specialist_skill/thumbnail_analyzer.py` (fallback CV) | ✅ **Alta** |
| **Cloud Text-to-Speech** | **1M chars/mês** (Standard) | $4.00/1M chars | `skills/tts/` (fallback ElevenLabs) | ✅ **Alta** |
| **Maps Static API** | **10.000 events/mês** | $2.00/1K events | `briefing/`, `specialist_skill/` (mapas estáticos) | 🟡 Média |
| **Maps Grounding Lite** | **10.000 events/mês** | $7.00/1K events | `trend_v2` (fatos geoespaciais) | 🟡 Média |
| **Places API (New)** | **10.000 events/mês** por SKU | $2.83-$5.00/1K | `briefing/` (lugares em notícias) | 🟡 Média |
| **Cloud Trace API** | Incluído no Cloud Observability | $0.20/M spans | `specialist_skill/health.py` (latência) | 🟢 Baixa |
| **Custom Search API** | **100 queries/dia** | $5.00/1K queries | ❌ **Descontinuado para Web Search em jun/2026** | ❌ Desativado |

---

## Recomendações de uso

### 🔴 Crítico (já em produção)

**YouTube Data API v3** — `specialist_skill/youtube_api.py`
- Substitui yt-dlp para stats de canal
- 10.000 units/dia = ~165 operações/dia para ViralX9
- Status: ✅ funcionando (validado com canal real Diolinux)
- Wrapper oficial: `googleapiclient.discovery.build("youtube", "v3", ...)`

### 🟡 Alta prioridade (integrar a seguir)

**Cloud Vision API** — `specialist_skill/thumbnail_analyzer.py`
- Complementa MediaPipe (face detection mais preciso, OCR nativo)
- 1.000 units/mês = ~30 thumbnails/dia
- Use cases:
  - `LABEL_DETECTION` → score semântico da thumbnail
  - `TEXT_DETECTION` → OCR de texto na thumbnail (mais confiável que MSER)
  - `FACE_DETECTION` → fallback do MediaPipe
  - `SAFE_SEARCH_DETECTION` → filtro de conteúdo NSFW (V2-E)

**Cloud Text-to-Speech** — `skills/tts/`
- 1M chars/mês = ~5.000 áudios de 200 chars
- Use case: fallback de alta qualidade quando ElevenLabs falha
- Vozes: `pt-BR-Wavenet-A/B/C` (Standard free), Neural2 (pago)
- Endpoint: `https://texttospeech.googleapis.com/v1/text:synthesize`

### 🟢 Média prioridade (nice-to-have)

**Maps Grounding Lite API** — `trend_v2.py`
- 10.000 events/mês = ~330/dia
- Substituto do Gemini Grounding para fatos geoespaciais
- Use case: "Onde aconteceu o último terremoto?" → retorna mapa + lugares

**Places API (New)** — `briefing/`
- 10.000 events/mês por SKU
- Use case: extrair lugares mencionados em notícias/eventos
- Ex: "CPI em Brasília" → retorna metadata do Congresso Nacional

**Maps Static API** — `briefing/`, `specialist_skill/`
- 10.000 events/mês
- Use case: gerar imagem estática de mapa para Telegram

### 🔴 Baixa prioridade

**Cloud Trace API** — `specialist_skill/health.py`
- Incluído no Cloud Observability free tier (50 GiB logs/mês)
- Use case: tracing distribuído do pipeline ViralX9

---

## Limites operacionais

**Free trials do GCP** geralmente dão $300 de crédito por 90 dias para projetos novos.
Após isso, ou se você tiver uma conta de billing paga, o free tier continua funcionando
até os limites listados.

**YouTube Data API v3** não está no GCP Free Tier — tem quota diária própria
(10K units/dia) que NÃO consome crédito. A cota reseta à meia-noite PST.

---

## Monitoramento

Use `specialist_skill/health.py` (V2-I) para acompanhar:
- Quota do YouTube API (`yt_api.quota_info()`)
- Failure rate por componente
- Latência p99

Quando `usage_pct` ≥ 0.80 (80%), o health monitor emite alerta preditivo.

---

## Descontinuados

- **Google Custom Search API** (Web Search) — descontinuado em jun/2026.
  - O recurso "Pesquisar em toda a Web" no CSE foi removido.
  - O backend CSE retorna 403 para buscas globais.
  - Mantido no código como fallback apenas se o Google restaurar.
  - **Recomendação:** NÃO usar — usar Tavily/Brave/Serper como substituto.