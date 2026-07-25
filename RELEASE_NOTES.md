# Seeker.Bot v3.12 — "WhatsApp → Obsidian Knowledge pipeline" 📱➡️📚

Esta release adiciona suporte a **polling de grupos WhatsApp** via Evolution
API v2.3.7, classificação automática de 9 tipos de mídia (image, PDF, ZIP,
áudio, vídeo, DOCX/XLSX/PPTX, vCard, location, sticker, poll), extração via
tools existentes (`extract_from_*` / `vault.process_*`) e salvamento direto
no Obsidian `Knowledge/`. Tudo configurável via Telegram (`/wa_config`)
com hot-reload — sem restart.

## 🚀 Novidades

### Cliente WhatsApp (`src/channels/whatsapp/client.py`)
- `WhatsAppClient` — async wrapper para Evolution API v2.3.7 (license-free)
- Métodos: `connection_state()`, `find_groups()`, `fetch_messages(group, since_ms, limit)`, `download_media()`, `send_text()`
- Auth via header `apikey` (env `EVOLUTION_API_KEY`)
- `is_configured` property para evitar chamadas sem credencial

### Skill whatsapp_vault (`src/skills/whatsapp_vault/`)
- `WhatsAppVaultGoal` — multi-slot scheduler (Pattern A do `briefing/goal.py`)
- `SeenIdsStore` — FIFO 5000 com persistência JSON e atomic write
- `_load_config()` — hot-reload de `config/whatsapp.yaml` a cada ciclo
- 6 janelas default: 02:00 / 06:00 / 10:00 / 14:00 / 18:00 / 22:00

### Painel `/wa_config` (Telegram InlineKeyboard)
- Sub-telas: main / grupo / janelas / modo / vault / status / testar
- Escrita em `config/whatsapp.yaml` (atomic .tmp + replace)
- Hot-reload automático (próximo ciclo aplica)
- Atalho `/wa` para status rápido, `/wa_resend <id>` para reprocessar

### Tipos de mídia suportados (9 + 3 especiais)
| Tipo | Detector | Processamento |
|------|----------|--------------|
| image | mimetype `image/*` | OCR (Florence-2 + VLM fallback) |
| pdf | `application/pdf` | PyMuPDF (15 pg max) |
| zip | `application/zip` | Recursivo (20 arq max) |
| audio | `audio/*` | Transcrição (Groq → local fallback) |
| video | `video/*` | Áudio transcription + keyframe OCR |
| docx | Office Open XML | python-docx → markdown |
| xlsx | Office Open XML | openpyxl → tables |
| pptx | Office Open XML | python-pptx → slides |
| vcard | `text/vcard` | vCard 3.0/4.0 parser |
| location | `locationMessage` | reverse geocode (Google Maps, 30d cache) |
| sticker | `stickerMessage` | Marker note (ignora conteúdo) |
| poll | `pollCreationMessage` | Markdown table + % |

### Validação
- 6/6 testes whatsapp_router passando
- 8/8 testes knowledge_vault_extractors_docs passando
- 19/19 testes specialist_skill sem regressão
- Boot Seeker limpo (zero erros novos, fix do bug `F.text.regexp().regexp`)

### Configuração
```bash
# Subir Evolution API + Postgres
docker-compose up -d evolution-api evolution-db

# Escaneie QR em http://localhost:8080/manager

# Configurar via Telegram:
/wa_config
```

---

# Seeker.Bot v3.11 — "MCP Server — opencode, Claude Desktop & session-to-session" 🔌🌐

Esta release transforma o Seeker.Bot em um **MCP server HTTP**, permitindo que
clientes externos (opencode, Claude Desktop, futuros clientes MCP) invoquem
tools do Seeker e leiam/gravem sessões via protocolo MCP padrão.

## 🚀 Novidades

### MCP Server (Streamable HTTP + SSE legacy)
- Novo `src/core/execution/mcp_server.py` — handler JSON-RPC 2.0 + MCP protocol
- Co-hospedado no mesmo RPC server (aiohttp na porta 8001, fallback automático)
- Três endpoints:
  - `POST /mcp` — Streamable HTTP (MCP spec 2024-11-05+)
  - `GET /mcp/sse` + `POST /mcp/messages` — legacy SSE transport
- Zero novas deps (usa aiohttp + StreamResponse do aiohttp)
- Server info: `seeker-bot` v3.11.0

### Bearer Auth com loopback bypass
- Novo `src/core/execution/mcp_auth.py` — middleware de autenticação
- Conexões loopback (`127.0.0.1`, `::1`) **NÃO** pedem token (uso local sem fricção)
- Conexões remotas exigem `Authorization: Bearer <SEEKER_MCP_API_KEY>`
- Rate limit: 10 req/s por IP via token bucket em memória
- 401 com header `WWW-Authenticate: Bearer realm="seeker-mcp"`

### 7 Tools + 1 Resource + 2 Prompts
- **Tools** (executáveis):
  - `read_file(path)` — lê arquivo de texto (até 5MB)
  - `write_file(path, content)` — escreve arquivo (com checkpoint)
  - `patch_file(path, target, replacement)` — patch cirúrgico (com checkpoint)
  - `execute_command(command, timeout=45)` — shell no host (Tirith + checkpoint)
  - `execute_code(code, timeout=30)` — Python em Docker sandbox
  - `read_session(session_id, limit=20)` — lê últimos N turnos
  - `record_session_turn(session_id, role, content)` — grava turno novo
- **Resource** (navegável):
  - `session://{session_id}` — últimos 20 turnos (JSON)
- **Prompts** (templates reutilizáveis):
  - `summarize_session(session_id)` — resumo da sessão
  - `compare_sessions(session_ids)` — diff entre N sessões

### Session-to-session communication (⭐ destaque)
- Tools `read_session` + `record_session_turn` permitem que um cliente MCP (ex: opencode)
  leia histórico de uma sessão Telegram, processe o contexto, e grave turnos novos.
- Resource `session://{session_id}` expõe sessões como URIs navegáveis.
- Casos de uso:
  - opencode lê o histórico do chat Telegram → escreve continuação como turno novo
  - Claude Desktop resume uma conversa Seeker → atualiza com novo turno
  - Workflow multi-step entre ferramentas MCP diferentes compartilhando contexto

### Integração com opencode (config exemplo)
```json
// ~/.config/opencode/opencode.json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "seeker": {
      "type": "remote",
      "url": "http://HOST:8001/mcp",
      "headers": {
        "Authorization": "Bearer ${SEEKER_MCP_API_KEY}"
      },
      "oauth": false,
      "enabled": true,
      "timeout": 15000
    }
  },
  "permission": { "seeker_*": "ask" }
}
```
Depois: `opencode mcp list` → mostra `seeker ✓ connected (7 tools, 1 resource)`.

### Validação (12 testes reais)
- ✅ `initialize` → handshake OK com `serverInfo: seeker-bot v3.11.0`
- ✅ `tools/list` → 7 tools expostas
- ✅ `read_file` → lê 1292 chars reais do requirements.txt
- ✅ `write_file` → grava arquivo + retorna "sucesso"
- ✅ `execute_command` → executa shell ("hello from mcp")
- ✅ `resources/list` → 1 resource (`session://{session_id}`)
- ✅ `resources/read` → retorna últimos turnos em JSON
- ✅ `prompts/list` → 2 prompts (summarize_session, compare_sessions)
- ✅ `prompts/get` → retorna mensagem formatada para LLM
- ✅ `record_session_turn` → grava turno + retorna ID
- ✅ `read_session` → lê turno recém-gravado (round-trip OK)
- ✅ `unknown method` → JSON-RPC error -32601 (Method not found)
- ✅ Auth: loopback bypass OK / IP externo sem token → 401 / IP externo token errado → 401 / IP externo token correto → 200

### Segurança em camadas
1. **Loopback bypass** — uso local sem fricção
2. **Bearer token** — conexões remotas exigem autenticação
3. **Tirith security** — `execute_command` bloqueia comandos perigosos
4. **Checkpoint pré-mutação** — `write_file`/`patch_file`/`execute_command` tiram snapshot antes
5. **Timeout obrigatório** — 45s comandos, 30s code, configurável
6. **Rate limit** — 10 req/s por IP via token bucket

### Arquivos novos/modificados
```
+ src/core/execution/mcp_auth.py     (~110 linhas)
+ src/core/execution/mcp_server.py   (~230 linhas)
+ src/core/execution/mcp_tools.py    (~310 linhas)
M src/core/execution/rpc.py          (registro das rotas MCP)
M config/.env / config/.env.example  (SEEKER_MCP_API_KEY)
M RELEASE_NOTES.md                   (v3.11)
```

---

# Seeker.Bot v3.10 — "Cliente MCP oficial + comando /mcp" 🔌

Esta release substitui o adapter MCP quebrado (que dependia do pacote `seeker_agent`
removido) por um cliente MCP leve usando o **SDK oficial Python (`mcp>=1.0.0`)**.
Adiciona também o comando `/mcp` no Telegram para gerenciar e invocar tools MCP
diretamente, sem precisar do LLM emitir a tag `[MCP_CALL]`.

## 🚀 Novidades

### Cliente MCP oficial (`mcp>=1.0.0`)
- Novo `src/core/execution/mcp_client.py` (~270 linhas) com `MCPClient` singleton
- Suporte a **stdio transport** (subprocesso com JSON-RPC via stdin/stdout)
- Config estilo Claude Desktop em `config/mcp_servers.json`
- Substituição de env `${VAR_NAME}` por valor de `os.environ`
- Auto-conexão em background no boot via `start_mcp()`
- API: `connect_all()`, `disconnect_all()`, `reconnect(name?)`,
  `list_servers()`, `list_tools(server)`, `call_tool(server, tool, args)`
- Timeout configurável (default 120s)

### Comando `/mcp` no Telegram
- Novo `src/channels/telegram/commands/mcp.py` (~340 linhas)
- `/mcp` — lista servidores conectados + contagem de tools
- `/mcp <server>` — lista tools com descrição e schema hints
- `/mcp <server> <tool> <json>` — executa tool com args JSON
- `/mcp reconnect` — reconecta todos os servidores
- Output truncado a 3500 chars
- Erros formatados com contexto (timeout, server offline, tool inexistente)

### Servidores MCP de exemplo (`config/mcp_servers.json`)
- **filesystem**: 14 tools (read_file, write_file, list_directory, etc.) — sandbox em `C:\Users\Victor`
- **github**: 26 tools (search_repositories, get_file_contents, etc.) — usa `${GITHUB_TOKEN}` do `.env`

### Integração com Active Loop
- Adapter `mcp_adapter.py` reescrito — agora usa `MCPClient.get()` em vez do `seeker_agent` removido
- Tag `[MCP_CALL: "server|tool|args_json"]` continua funcionando para o LLM invocar MCP no Active Loop
- Lazy init: conecta automaticamente na primeira chamada

### Validação em produção
```
[boot]
[seeker.execution.adapters] INFO: Adaptador 'mcp' registrado com sucesso sob a tag 'MCP_CALL'
Secure MCP Filesystem Server running on stdio
[seeker.execution.mcp_client] INFO: [mcp] Conectado a 'filesystem' (14 tools)
GitHub MCP Server running on stdio
[seeker.execution.mcp_client] INFO: [mcp] Conectado a 'github' (26 tools)
[seeker.execution.adapters.mcp] INFO: [mcp] 2/2 servidor(es) conectado(s): ['filesystem', 'github']
[seeker.telegram] INFO: [bot] mcp handlers registrados com sucesso
```

### Servidores MCP populares compatíveis
Você pode adicionar qualquer um destes em `config/mcp_servers.json`:
- `@modelcontextprotocol/server-filesystem` — ler/escrever arquivos
- `@modelcontextprotocol/server-github` — issues, PRs, repos
- `@modelcontextprotocol/server-gitlab` — GitLab
- `@modelcontextprotocol/server-slack` — Slack
- `@modelcontextprotocol/server-postgres` — PostgreSQL
- `mcp-server-fetch` (via uvx) — fetch web pages

---

# Seeker.Bot v3.9 — "Comando /terminal estilo Hermes" 🖥️

Esta release adiciona execução direta de comandos shell do host via Telegram,
estilo Hermes. O Seeker já tinha `execute_terminal_command` no Active Loop
(via tag `[TERMINAL_EXECUTE]`) mas só o LLM podia disparar; agora o usuário
também pode via `/terminal <comando>`.

## 🚀 Novidades

### Comando `/terminal <cmd>` (estilo Hermes)
- Novo handler em `src/channels/telegram/commands/terminal.py`
- Bypassa o Active Loop — execução direta via `execute_terminal_command`
- Proteções em camadas:
  1. **Tirith Security** audita cada comando antes de executar (fail-open se indisponível)
  2. **Checkpoint automático** antes de qualquer execução destrutiva
  3. **Detector de comandos perigosos** (regex) — `rm`, `del`, `format`, `sudo`,
     `shutdown`, `Remove-Item`, `diskpart`, `reg delete` etc. exigem confirmação
     inline via botão "⚠️ Confirmar execução" antes de rodar
  4. **Timeout** configurável: default 45s, máx 300s via `/terminal timeout 120 cmd`
  5. **Limite de output** 4000 chars (truncado com aviso)
  6. **Limite de comando** 4000 chars

### Uso
- `/terminal` ou `/terminal help` — mostra help
- `/terminal ls -la` — executa
- `/terminal dir` — atalhos Windows também funcionam
- `/terminal ping 8.8.8.8 -n 4` — comandos de rede permitidos
- `/terminal timeout 120 npm test` — customiza timeout
- Comandos perigosos → botão inline para confirmar

### Integração
- `BotCommand("/terminal")` adicionado ao menu do Telegram
- `pipeline._terminal_pending` para guardar comandos perigosos aguardando confirmação
- Setup registrado em `bot.py` com try/except + log

### Validação
- 13/13 testes do `DANGEROUS_PATTERN` passam (rm, del, format, sudo, etc.)
- Smoke test: `execute_terminal_command("echo hello from /terminal")` → `"hello from /terminal"`
- Boot Seeker: `[bot] terminal handlers registrados com sucesso`
- 19/19 testes specialist_skill ainda passando

---

# Seeker.Bot v3.8 — "ViralX9 V2: Preditivo, Multi-Fonte & Pipeline Robusto" 🧠📈

Esta release completa a maturação da skill ViralX9 com arquitetura de detecção de tendências multi-camadas, predição de velocidade, análise de thumbnails via CV, filtros anti-falso-positivo, circuit breakers granulares e health check preditivo. Inclui também a migração para Python 3.12.

## 🚀 Novidades

### V2-A: YouTube Data API v3 (substitui yt-dlp)
- Novo módulo `youtube_api.py` com wrapper oficial da YouTube Data API v3
- `fetch_channel_uploads()` via `playlistItems.list` e `fetch_video_details()` batch (50 vídeos/chamada)
- Quota tracking (10K units/dia), retry exponencial, cache 6h
- Suporte a `/channel/UC...`, `/@handle`, `/c/customname` URLs

### V2-B: Trend Detection Multi-Camadas
- Novo módulo `trend_v2.py` com 9 fontes determinísticas gratuitas:
  - **Leading:** Reddit /rising, HN Algolia, arXiv, CISA KEV, ransomware.live
  - **Mid:** Google News RSS, GDELT DOC 2.0
  - **Lagging/Confirmation:** Google Trends RSS, Wikipedia Pageviews
- Fallback LLM (Gemini 2.5 Flash Grounding) se todas as fontes falharem
- Score composto via média geométrica dos top 3 sinais, lift cap 3.0x

### V2-C: Velocity-Aware Prediction
- Novo módulo `velocity_tracker.py` com histórico de views/hora por vídeo
- Regressão linear sobre snapshots para predizer views/hora futuras
- Métricas: current_vph, tendência (aceleração/desaceleração), confiança
- Snapshots podados após 72h, máximo 12 por vídeo

### V2-D: Thumbnail Analysis via Computer Vision
- Novo módulo `thumbnail_analyzer.py` com análise de thumbnails via OpenCV + MediaPipe
- **Face detection:** MediaPipe Face Detection (rostos aumentam score)
- **Color analysis:** brilho, saturação (HSV), contraste (Lab std dev)
- **Text detection:** MSER regions como proxy de texto
- Score composto: 0.4×face + 0.3×color + 0.3×text
- Cache em memória (24h TTL), download via aiohttp

### V2-E: False-Positive Filters
- Novo módulo `filters.py` com 4 filtros:
  - **Shorts:** duração < 60s → penalidade 0.3x
  - **Live:** live/streaming/estreia no título → penalidade 0.2x
  - **News-peg:** LLM classifica se o conteúdo depende de notícia recente → penalidade 0.4x
  - **Duplicata:** similaridade Jaccard > 80% com temas já vistos → penalidade 0.5x

### V2-F: Viral Score Reformulado
- `viral_score()` atualizado para incorporar todos os fatores V2
- Fórmula: outlier^1.0 × trend^1.5 × frescor × vel_bonus × pred_bonus × thumb_bonus × filter_penalty
- Faixa típica: [0..12] vs antigo [0..10]
- Novos pesos: SCORE_PREDICTED_VELOCITY_WEIGHT=0.10, SCORE_THUMBNAIL_WEIGHT=0.20

### V2-G: Pipeline Paralelo (Circuit Breakers)
- Novo módulo `circuit_breaker.py` com estados CLOSED / OPEN / HALF_OPEN
- Circuit breakers granulares por fonte (youtube_api, reddit, hn, arxiv, ...)
- Config: 5 falhas → OPEN, 60s recovery → HALF_OPEN, 3 sucessos → CLOSED
- Singleton via `CircuitBreaker.get(name)`

### V2-H: Health Check & Alertas Preditivos
- Novo módulo `health.py` com HealthMonitor singleton
- Métricas: taxa de falha por componente, latência média/P99, ciclos sem candidatos
- Alertas preditivos: queda em candidatos/ciclo, latência alta, quota YouTube próxima do limite
- Cooldown de 1h entre alertas do mesmo tipo

### F-08: Migração Python 3.12
- Python 3.12.10 instalado localmente, venv `.venv312` criado
- Todas as dependências reinstaladas e verificadas
- 45 testes passando nativamente sem FutureWarning
- Startup echo: `Python 3.12.x — Seeker.Bot v3.4.0`

### Repositório
- Limpeza de arquivos órfãos: watchdog.py, .gitkeep, auto_retry/goal.py removidos do tracking
- .gitignore atualizado com `.venv*/` para múltiplos venvs

---

# Seeker.Bot v3.6 — "Painel /config Interativo & Ativação de Skills Specialist" 🚀⚙️

## 🚀 Novidades

### 1. Painel Interativo de Configuração (`/config`)
- **Gestão de Skills Dinâmica:** Interface baseada em botões (`InlineKeyboardMarkup`) que permite ativar ou desativar qualquer skill em tempo de execução por categorias (Core, Recommended, Specialist) com salvamento automático direto no arquivo `skills.yaml`. As skills do Core permanecem protegidas de modificação acidental.
- **Saúde dos Providers:** Visualização instantânea dos modelos ativos associados a cada papel cognitivo do Seeker (Fast, Deep, Judge, Adversarial) e status da arbitragem.
- **Budget Rápido:** Consulta simplificada dos gastos acumulados hoje por provedor.
- **Reinicialização Assistida (Restart):** Botão com tela de confirmação para forçar o restart ordenado do processo, fazendo com que o Watchdog recarregue o Seeker com as novas configurações ativas.

### 2. Ativação de Skills Specialist
- **`desktop_watch`:** Monitoramento ativo do status da tela/AFK (exige VLM).
- **`email_monitor`:** Monitoramento automatizado de novas mensagens da caixa de entrada (exige IMAP).
- **`remote_executor`:** Habilidade especialista de execução de planos remotos em background.

---

# Seeker.Bot v3.5 — "NLP Reminders, Zip/MHT Vaulting & InstaScraper Video Delivery" 🚀🎥

## 🚀 Novidades

### 1. Cancelamento de Lembretes via NLP e UUID Curto
- **IDs Simplificados:** Ao agendar um lembrete, o sistema agora exibe um ID amigável de 8 caracteres (baseado no UUID) em vez do UUID longo tradicional, melhorando a legibilidade.
- **Cancelamento Inteligente (NLP):** O Seeker agora entende intenções de cancelamento de lembretes em linguagem natural (ex: "cancela o lembrete c78f102b" ou "remova a tarefa d92a10fe"). O interceptador processa a solicitação e executa a remoção dinamicamente no banco de dados.

### 2. Leitura de ZIP no Knowledge Vault
- **Consolidação em Nota Única:** O cofre do Obsidian agora aceita arquivos compactados `.zip`. Ao enviar um ZIP contendo múltiplas notas de texto ou Markdown, o Seeker extrai e compila o conteúdo inteiro em um único documento Markdown consolidado, preservando links e a estrutura dos arquivos originais.

### 3. Extração Estruturada de Arquivos MHT (.mht)
- **Sanitização de Documentos:** Implementado o extrator para arquivos `.mht` (Web Archives). O Seeker remove metadados brutos e cabeçalhos MIME proprietários, convertendo a página web arquivada em um Markdown limpo, legível e pronto para ser integrado ao Obsidian.

### 4. InstaScraper via Chat (Video Delivery Bruto)
- **Foco na Mídia:** Ao detectar links do Instagram no chat do Telegram, o bot agora baixa a mídia de forma assíncrona (com delays anti-ban) e envia de volta **apenas o vídeo bruto**, sem descrições longas ou metadados desnecessários, otimizando o consumo de dados do usuário e a fluidez do chat.

### 5. Prevenção de Loops no Skill Creator (Eureka Loop)
- **Bloqueio de Duplicações:** O gerador de skills (`/criar_skill`) agora faz uma varredura das skills instaladas antes de propor código. Isso impede propostas redundantes, repetitivas ou contraditórias do agente, garantindo um loop de melhoria contínua limpo.

## 🔧 Correções e Melhorias

- **ShowDeck Geolocation Hardening:** Ajustes no prompt e remoção do estado padrão na tabela de CRM. Cidades de outros estados agora resolvem a UF correspondente corretamente, eliminando ruído geográfico.
- **Video Miner Cookies Fallback:** Implementação de fallback no minerador de vídeos para usar `docs/all_cookies.txt` caso os cookies específicos do navegador falhem.
- **Menu e Lista de Comandos Atualizados:** Sincronização e validação completa dos comandos do bot do Telegram, com remoção automática de funcionalidades e utilitários comerciais na build pública.

---

# Seeker.Bot v3.4 — "Google Search Grounding & Quota Safety" 🔍🛡️

Esta release traz a integração nativa do buscador do Google (Google Custom Search API) com otimizações severas de custo e segurança, além de novos mecanismos de contenção de custos e proteção contra loops infinitos de agentes autônomos.

## 🚀 Novidades

### 1. Google Custom Search Engine Integration
- **Buscador Nativo:** Adicionado o backend do Google Custom Search como alternativa confiável e veloz de pesquisa web global.
- **Limpeza de Contexto (Token Saving):** Os resultados são limpos em nível de JSON, extraindo-se apenas `title`, `url` (link) e `snippet` antes de alimentar o contexto da IA. Isso reduz significativamente a quantidade de tokens consumidos por busca.

### 2. Cache Local Persistente (SQLite Cache)
- **Memoization Local:** Toda busca realizada é armazenada localmente com um TTL (Time-To-Live) rígido de 24 horas (`data/search_cache.db`).
- **Custo Zero em Repetições:** Buscas idênticas acionam o cache local instantaneamente, retornando `Cache HIT` e consumindo 0 créditos de API externa.

### 3. Gestão Inteligente de Cotas (Safety Throttle)
- **Bloqueio de Gastos:** Implementada uma trava dinâmica no `QuotaManager`. Para a API do Google Custom Search, a cota diária limite foi fixada em **90 buscas/dia** (margem de segurança sobre a cota grátis de 100/dia).
- **Fallback Transparente:** Ao atingir o limite, o motor migra automaticamente de forma transparente para provedores alternativos (Tavily/Brave) ou processa a consulta via raciocínio puramente em contexto.

### 4. Válvula de Segurança Anti-Loop
- **Janela de Sessão Deslizante:** Para evitar que o agente entre em loops de raciocínio lógico e esvazie toda a cota de buscas em poucos minutos, limitamos as buscas consecutivas na mesma sessão a um teto dinâmico (padrão: 4 buscas).
- **Auto-Reset:** Um período de inatividade de 30 segundos reseta o contador de sessão, garantindo usabilidade em execuções normais e proteção absoluta contra bugs de looping.

## 🔧 Correções e Melhorias

- **Configurações Seguras (.env.example):** Adicionadas as variáveis de ambiente `GOOGLE_SEARCH_API_KEY` e `GOOGLE_SEARCH_CX` documentadas para facilitar a configuração segura por parte do usuário.

---
# Seeker.Bot v3.3 — "Python 3.12 & Auth Patch" 🚀

Esta release traz a atualização do core para Python 3.12, garantindo maior performance assíncrona, além de correções críticas na autenticação do Telegram e nova padronização de branding (Logo).

## 🚀 Novidades

### 1. Upgrade de Motor (Python 3.12)
- O ambiente de execução do Seeker.Bot foi oficialmente migrado para o Python 3.12.7.
- **Ganhos:** Aproveitamento nativo dos TaskGroups e melhorias profundas de performance no syncio, resultando em um polling mais eficiente e menor latência na arbitragem.

### 2. Branding
- Adição do diretório de assets (Logo/) para padronização visual da interface e repositório.

## 🔧 Correções e Melhorias

### 1. Robustez na Autenticação (Telegram)
- **Correção no AuthMiddleware:** Refatorada a checagem de usuário para usar hasattr(event, "from_user"), prevenindo quedas silenciosas caso o objeto de evento não possua as propriedades esperadas, garantindo que atualizações inválidas sejam ignoradas com segurança.

---
# Seeker.Bot v3.2 — "Resilience & Export" 🛠️

Esta release foca na recuperação de desastres (database repair), expansão da infraestrutura de exportação e estabilização de fases críticas de raciocínio.

## 🚀 Novidades

### 1. Sistema de Reparo de Memória (MemRepair)
Implementação de um motor de recuperação para o banco de dados SQLite (`seeker_memory.db`). 
- **Recuperação de Corrupção:** Script especializado capaz de iterar sobre tabelas e recuperar dados de arquivos "malformed" sem perda total de histórico.
- **Integrity Check:** Validação formal via `PRAGMA integrity_check` integrada ao pipeline de inicialização.

### 2. Google Drive Exporter ☁️
Integração nativa do `GoogleDriveExporter` no `SeekerPipeline`.
- **Sincronização de Relatórios:** O Radar de Eventos e os Dossiês agora são automaticamente exportados para o Google Drive (Service Account).
- **NotebookLM Ready:** Garante que as fontes de dados estejam sempre acessíveis para análise externa via LLMs multimodais.

## 🔧 Correções e Melhorias

### 1. Estabilização da Fase Deep (DeepPhase)
- **Aumento de Timeout:** O Verification Gate teve seu timeout estendido de **20s para 40s**, mitigando falhas prematuras em consultas complexas que exigem múltiplos loops de arbitragem.

### 2. Correção de Injeção de Dependência (Event Radar)
- Resolvido o erro `AttributeError: 'SeekerPipeline' object has no attribute 'drive_exporter'` que impedia a exportação de relatórios PDF.

### 3. Alinhamento de Papéis Cognitivos (SAI Patch)
- Reconfiguração do papel `FAST` no `config/models.py` para garantir que o **Gemini 3.1 Flash Lite** atue como motor principal de extração e propostas de skills, prevenindo falhas de geração.

---
# Seeker.Bot v3.1 — "Cognitive Integrity" 🛡️

Esta release foca na robustez operacional, integridade cognitiva e observabilidade avançada do pipeline.

## 🚀 Novidades

### 1. Monitor de Integridade (IntegrityMonitor)
Implementação de um sistema de rastreamento de "saúde cognitiva" que mede:
- **Índice de Alucinação:** Proporção de conflitos detectados pela arbitragem vs. total de execuções.
- **Reliability Score:** Pontuação de confiabilidade baseada na consistência entre modelos.
- **Eficiência S.A.R.A:** Taxa de sucesso das operações de auto-cura do sistema.
- **Integridade Financeira:** Monitoramento em tempo real do orçamento (budget) vs. gasto.

### 2. Comando `/audit_sara`
Novo comando no Telegram para visualizar o Dashboard de Integridade em tempo real.

### 3. Integração S.A.R.A (Self-healing)
O motor S.A.R.A agora reporta sucessos e falhas diretamente ao Monitor de Integridade, permitindo loops de feedback para melhoria de prompts.

## 🔧 Correções e Melhorias

- **Refatoração Global (Lumen Standard):** Aplicação de ruff fix em todo o projeto, removendo redundâncias, corrigindo importações circulares e padronizando o código.
- **Hardening de Segurança:** Higienização de credenciais e atualização de `.gitignore` para prevenir vazamentos acidentais.
- **Estabilização do Bot:** Correção de bugs em comandos críticos (`/status`, `/vault`, `/development`) que causavam falhas silenciosas.
- **Otimização de Memória:** Melhoria no processamento de fatos semânticos e recuperação de contexto via Obsidian Vault.

## 🚑 Hotfix (Pós-v3.1)
- **Restauração de Core:** Recuperados módulos críticos (`src/core/data` e `src/skills/drive_manager`) deletados acidentalmente durante a refatoração global.
- **Pipeline de Integração:** Corrigida instabilidade na autenticação de exportação (suporte aprimorado para credenciais OAuth) e renomeada a classe base do motor de criação de skills (`CodeGenerator`) para alinhar com o design arquitetural.
- **Prevenção de Conflitos:** Resolvidos problemas de instâncias zumbis travando o polling do Telegram (`TelegramConflictError`).

---
*Seeker.Bot — Always Observing, Always Orienting.*

