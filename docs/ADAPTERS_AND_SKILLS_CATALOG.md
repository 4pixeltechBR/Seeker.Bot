# Seeker.Bot — Catálogo de Adaptadores e Skills (v3.12+)

> Especificação técnica detalhada dos **10 adaptadores de execução** e **42 skills** ativas do Seeker.Bot.

---

## 🔌 Part I: Adaptadores de Execução (`src/core/execution/adapters/`)

Os adaptadores conectam o Seeker.Bot a serviços externos, subsistemas de IA e APIs de automação. Eles são registrados e controlados via `AdapterManager` (`src/core/execution/adapters/manager.py`) e ativados no `config/.env`.

| Adaptador | Tag(s) de Ação | Arquivo | Habilitador `.env` | Funcionalidade & Payload |
|:---|:---|:---|:---|:---|
| **MOA** | `MOA_QUERY` | `moa_adapter.py` | `PORTED_MOA_ENABLED=true` | Mixture of Agents. Executa consulta paralela em múltiplos LLMs e sintetiza uma resposta única refinada. |
| **Browser Camo** | `BROWSER_CAMO`<br>`BROWSER_CAMO_CLICK`<br>`BROWSER_CAMO_TYPE`<br>`BROWSER_CAMO_SNAPSHOT` | `browser_camofox_adapter.py` | `PORTED_BROWSER_CAMO_ENABLED=true` | Automação e extração de páginas dinâmicas com navegador camuflado anti-bot (Camofox/Playwright). |
| **CRM Query** | `CRM_QUERY` | `specialist_skill.py` | `PORTED_CRM_ENABLED=true` | Consultas estruturadas e busca de leads/contratos no banco de dados do ShowDeck CRM. |
| **Cronjob** | `CRON_CREATE`<br>`CRON_LIST`<br>`CRON_REMOVE`<br>`CRON_PAUSE`<br>`CRON_RESUME` | `cronjob_adapter.py` | `PORTED_CRONJOB_ENABLED=true` | Agendamento e gerenciamento dinâmico de cronjobs e rotinas recorrentes. |
| **Firecrawl** | `FIRECRAWL` | `firecrawl_adapter.py` | `PORTED_FIRECRAWL_ENABLED=true` | Deep crawling de websites com renderização JS e extração limpa formatada em Markdown. |
| **Media** | `IMAGE_GEN`<br>`TTS_GEN`<br>`TRANSCRIBE_AUDIO` | `media_adapter.py` | `PORTED_MEDIA_ENABLED=true` | Pipeline unificado para geração de imagens, síntese de voz e transcrição de áudio via ffmpeg. |
| **STT** | `STT` | `stt_adapter.py` | `PORTED_STT_ENABLED=true` | Speech-To-Text acelerado (Groq Whisper com fallback para Whisper local em Python). |
| **TTS** | `TTS` | `tts_adapter.py` | `PORTED_TTS_ENABLED=true` | Text-To-Speech para resposta por voz no Telegram/WhatsApp. |
| **X Search** | `X_SEARCH` | `x_search_adapter.py` | `PORTED_X_SEARCH_ENABLED=true` | Busca e monitoramento de notícias e tendências em tempo real na rede X (Twitter). |
| **MCP** | `MCP_CALL` | `mcp_adapter.py` | `PORTED_MCP_ENABLED=true` | Invocação de ferramentas via Model Context Protocol em servidores MCP remotos ou locais. |

---

## 🧰 Part II: Catálogo de Skills (`src/skills/`)

As 42 skills ativas estão organizadas por categoria operacional em `config/skills.yaml`:

### 🟢 1. Core & Saúde
1. **`health_monitor`** (`src/skills/health_monitor/`): Dashboard de integridade do sistema, portas, memória e serviços.
2. **`self_improvement` (S.A.R.A.)** (`src/skills/self_improvement/`): Sistema de auto-diagnóstico e self-healing executado a cada 6 horas.
3. **`briefing`** (`src/skills/briefing/`): Síntese automatizada do briefing diário enviado no Telegram às 07:00.

### 📱 2. Comunicação & Vault
4. **`whatsapp_vault`** (`src/skills/whatsapp_vault/`): Processamento de mensagens e 9 mídias do WhatsApp via Evolution API v2.3.7 para salvar no Obsidian Vault.
5. **`knowledge_vault`** (`src/skills/knowledge_vault/`): Gestão da base de conhecimento persistente no Obsidian.
6. **`scheduler_conversacional`** (`src/skills/scheduler_conversacional/`): Interface para agendar tarefas via linguagem natural.
7. **`email_monitor`** (`src/skills/email_monitor/`): Leitura e classificação de e-mails via IMAP.
8. **`transcription`** (`src/skills/transcription/`): Transcrição detalhada de reuniões e áudios longos.

### 💼 3. Vendas, CRM & Prospecção
9. **`specialist_skill`** (`src/skills/specialist_skill/`): Inteligência comercial B2B e acompanhamento de prefeituras/eventos.
10. **`specialist_skill`** (`src/skills/specialist_skill/`): Consolidação semanal de métricas do funil de vendas.
11. **`specialist_skill`** (`src/skills/specialist_skill/`): Relatório diário dos leads do ShowDeck CRM enviado às 08:00 no Telegram.
12. **`specialist_skill`** (`src/skills/specialist_skill/`): Mineração de diários oficiais e eventos municipais.
13. **`specialist_skill`** (`src/skills/specialist_skill/`): Enriquecimento de contatos de decisores municipais.
14. **`specialist_skill`** (`src/skills/specialist_skill/`): Automação de sequências de prospecção.
15. **`specialist_skill`** (`src/skills/specialist_skill/`): Mapeamento de feiras e festivais regionais.
16. **`fuzzy_match`** (`src/skills/fuzzy_match/`): Correspondência inteligente de nomes de clientes e cidades.

### 📊 4. Mineração & Notícias
17. **`specialist_skill`** (`src/skills/specialist_skill/`): Mineração de vídeos virais e classificação de relevância por nicho com CoT LLM.
18. **`sense_news`** (`src/skills/sense_news/`): Curadoria e filtragem de notícias de inteligência artificial.
19. **`sherlock_news`** (`src/skills/sherlock_news/`): Monitoramento de atualizações em repositórios e ecossistema tech.
20. **`tech_scout`** (`src/skills/tech_scout/`): Monitoramento de novos lançamentos de LLMs e modelos multimodal.

### 🖥️ 5. Automação de Desktop & SO
21. **`agent_browser`** (`src/skills/agent_browser/`): Automação de tarefas web via navegador.
22. **`os_control`** (`src/skills/os_control/`): Comandos de controle do Windows (processos, volumes, telas).
23. **`desktop_watch`** (`src/skills/desktop_watch/`): Monitoramento da tela quando o usuário está ausente.
24. **`remote_executor`** (`src/skills/remote_executor/`): Executor de tarefas remotas isoladas.
25. **`vision`** (`src/skills/vision/`): Análise computacional de imagens e screenshots via VLM.
26. **`promptograph`** (`src/skills/promptograph/`): Busca e gestão da base de 5.317 prompts curados.

### 🧬 6. Evolução & Enxames
27. **`darwinian_evolver`** (`src/skills/darwinian_evolver/`): Evolução de prompts via algoritmos genéticos/RL.
28. **`skill_creator`** (`src/skills/skill_creator/`): Gerador dinâmico de novas skills.
29. **`ruflo_swarm`** (`src/skills/ruflo_swarm/`): Enxame de subagentes paralelos com Multi-Armed Bandits.
30. **`subagent_dispatcher`** (`src/skills/subagent_dispatcher/`): Gerenciador e despachante de subagentes.

### 🛠️ 7. Utilitários & Outros
31. **`bug_analyzer`** (`src/skills/bug_analyzer/`): Diagnóstico automatizado de tracebacks.
32. **`git_automation`** (`src/skills/git_automation/`): Automação de commits e sincronização com GitHub.
33. **`drive_manager`** (`src/skills/drive_manager/`): Sincronização e controle de arquivos no Google Drive.
34. **`instascraper`** (`src/skills/instascraper/`): Extração de mídias do Instagram.
35. **`kanban`** (`src/skills/kanban/`): Quadro Kanban de tarefas via Telegram.
36. **`microsoft_graph`** (`src/skills/microsoft_graph/`): Conector para serviços Microsoft 365.
37. **`osv_check`** (`src/skills/osv_check/`): Auditoria de segurança de dependências (Open Source Vulnerabilities).
38. **`research_machine`** (`src/skills/research_machine/`): Pipeline autônomo YouTube → NotebookLM → Obsidian.
39. **`tts`** (`src/skills/tts/`): Módulo de geração de voz.
40. **`stt_groq`** (`src/skills/stt_groq.py`): Módulo acelerado STT via Groq API.
41. **`stt_local`** (`src/skills/stt_local.py`): Módulo STT de contingência local.
42. **`x_search`** (`src/skills/x_search/`): Ferramenta dedicada de inteligência no X/Twitter.
