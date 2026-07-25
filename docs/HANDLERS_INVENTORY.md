# Seeker.Bot — Inventário de Handlers (Telegram)

Catálogo completo de todos os handlers/commands implementados, cruzados
com o menu azul do Telegram (`set_my_commands` em `bot.py:setup_commands`).

**Última atualização:** 21/07/2026 (v3.12)

---

## 📊 Resumo Estatístico

| Categoria | Commands | Onde |
|-----------|----------|------|
| Diagnóstico do Sistema | 10 | `system.py` + `dashboard.py` |
| Memória / Sessão | 3 | `system.py` |
| Decaimento / Limpeza | 3 | `system.py` |
| Custos | 3 | `system.py` |
| RL (Aprendizado por Reforço) | 8 | `system.py` + `specialist_skill.py` (swarm) |
| Tarefas Agendadas | 7 | `tasks.py` |
| Knowledge / Obsidian / Pesquisa | 4 | `vault.py` + `research.py` |
| Email | 1 | `system.py` (test_email) |
| specialist_skill (YouTube trending) | 6 | `specialist_skill.py` |
| Radar de Eventos | 1 | `radar.py` |
| Dev / Ferramentas | 5 | `development.py` |
| Pesquisa direta | 2 | `system.py` |
| Sherlock / Knowledge | 2 | `sherlock.py` + `system.py` |
| Visão / Desktop | 3 | `vision.py` |
| Google Drive | 1 | `drive.py` |
| Transcrição | 1 | `transcription` (handler) |
| Instagram | 1 | `instascraper.py` |
| Vendas / CRM | 3 | `sales.py` |
| LLM (controle de modelo) | 2 | `system.py` |
| Terminal / MCP / WhatsApp (v3.9-3.12) | 6 | `terminal.py` + `mcp.py` + `whatsapp*.py` |
| Recuperação / Boot | 2 | `config.py` (restart é no system.py) |
| **TOTAL** | **72** | |

---

## 📋 Catálogo Completo

### 🔧 Recuperação / Boot

| Comando | Função | Arquivo |
|---------|--------|---------|
| `/start` | Menu de ajuda + inventário de comandos | `bot.py:310` |
| `/config` | Painel de configuração (Skills, Providers, Restart) | `commands/config.py:271` |
| `/restart` | Reinicia o bot (admin) | `system.py:914` |

### 📊 Diagnóstico do Sistema

| Comando | Função | Arquivo |
|---------|--------|---------|
| `/status` | Painel de providers, memória e metas | `system.py:29` |
| `/saude` | Dashboard de saúde dos goals (detalhado) | `system.py:87` |
| `/dashboard` | Dashboard completo do sistema (saúde, RL, custos, breakers) | `dashboard.py:21` |
| `/perf` | Dashboard de performance e latência | `system.py:221` |
| `/perf_detailed` | Métricas detalhadas por fase | `system.py:256` |
| `/cascade_status` | Status detalhado da API Cascade (6 tiers) | `system.py:316` |
| `/recovery` | Status de circuit breakers e degradação | `system.py:475` |
| `/rate` | Exibe status dos rate limiters | `system.py:574` |
| `/budget` | Gastos de hoje por provedor | `system.py:655` |
| `/budget_monthly` | Gastos do mês por provedor | `system.py:689` |

### 🧠 Memória / Sessão

| Comando | Função | Arquivo |
|---------|--------|---------|
| `/memory` | Fatos aprendidos na sessão | `system.py:514` |
| `/god` | Arma God Mode para a próxima mensagem | `system.py:566` |
| `/cancelar` | Cancela operação atual (vault, transcrição) | `system.py` (genérico) |

### 🧹 Decaimento / Limpeza

| Comando | Função | Arquivo |
|---------|--------|---------|
| `/decay` | Roda limpeza de confiança manual | `system.py:617` |
| `/data_stats` | Estatísticas do armazém de dados | `system.py:738` |
| `/data_clean` | Executa limpeza de dados antigos | `system.py:790` |

### 📈 Custos

| Comando | Função | Arquivo |
|---------|--------|---------|
| `/forecast` | Previsões de custos para próximos 7 e 30 dias | `system.py:843` |

### 🤖 RL (Aprendizado por Reforço)

| Comando | Função | Arquivo |
|---------|--------|---------|
| `/bandit` | LinUCB em shadow mode (progresso de RL) | `system.py:391` |
| `/bandit_stats` | Estatísticas do LinUCB (atalho para /bandit) | `system.py:391` (alias) |
| `/rl_tune` | Tuning de parâmetros do LinUCB | `system.py:1227` |
| `/rl_stats` | Estatísticas do LinUCB (conversão, arm stats) | `system.py:1335` |
| `/rl_activate` | Ativa o aprendizado por reforço (produção) | `system.py:1270` |
| `/rl_deactivate` | Desativa o aprendizado por reforço (shadow) | `system.py:1303` |
| `/habits` | Padrões de decisão aprendidos | `system.py:905` |
| `/audit_sara` | Audit integrado do S.A.R.A | `system.py:210` |

### 📅 Tarefas Agendadas (scheduler_conversacional)

| Comando | Função | Arquivo |
|---------|--------|---------|
| `/agendar` | Agenda nova tarefa (wizard conversacional) | `tasks.py:149` |
| `/listar` | Lista tarefas agendadas do chat | `tasks.py:198` |
| `/detalhe` | Ver detalhes de tarefa (`/detalhe <ID>`) | `tasks.py:220` |
| `/pausar` | Pausa tarefa (`/pausar <ID>`) | `tasks.py:243` |
| `/reativar` | Reativa tarefa (`/reativar <ID>`) | `tasks.py:266` |
| `/remover` | Remove tarefa (`/remover <ID>`) | `tasks.py:289` |
| `/executar` | Executa tarefa agora (`/executar <ID>`) | `tasks.py:312` |

### 📚 Knowledge / Obsidian / Pesquisa

| Comando | Função | Arquivo |
|---------|--------|---------|
| `/obsidian` | Salva conteúdo no cofre do Obsidian | `vault.py:35` |
| `/cofre` | Pesquisa no cofre do Obsidian | `vault.py:82` |
| `/research` | Pesquisa profunda sobre um tópico | `research.py:67` |
| `/research_schedule` | Agenda pesquisa recorrente | `research.py:24` |

### 📧 Email

| Comando | Função | Arquivo |
|---------|--------|---------|
| `/test_email` | Força execução do Email Monitor (diagnóstico) | `system.py` (handler custom) |

### 🔭 ViralX9 (YouTube trending mining)

| Comando | Função | Arquivo |
|---------|--------|---------|
| `/x9` | specialist_skill: ativar/desativar nichos de mineração | `specialist_skill.py:360` |
| `/specialist_skill` | specialist_skill (completo, mesmo que /x9) | `specialist_skill.py:69` |
| `/vx9_pausar` | Pausar nicho do specialist_skill | `specialist_skill.py:179` |
| `/vx9_ativar` | Ativar nicho do specialist_skill | `specialist_skill.py:183` |
| `/vx9_remover` | Remover nicho do specialist_skill | `specialist_skill.py:187` |
| `/swarm_status` | Status do Ruflo Swarm (multi-agente) | `specialist_skill.py:441` |

### 🗺️ Radar de Eventos

| Comando | Função | Arquivo |
|---------|--------|---------|
| `/radar` | Configura e controla o Radar de Eventos | `radar.py:78` |

### 🛠️ Dev / Ferramentas

| Comando | Função | Arquivo |
|---------|--------|---------|
| `/criar_skill` | Cria dinamicamente uma nova skill (Patcher L3) | `development.py:196` |
| `/git_backup` | Faz backup manual do código no GitHub privado | `development.py:13` |
| `/bug` | Analisa bug com contexto e sugestões | `development.py:113` |
| `/bug_approve` | Aprova e aplica correções sugeridas | `development.py:159` |
| `/bug_cancel` | Cancela análise de bug | `development.py:139` |

### 🔍 Pesquisa Direta

| Comando | Função | Arquivo |
|---------|--------|---------|
| `/search` | Busca direta e forçada na web | `system.py` (handler de busca) |
| `/deep` | Pesquisa profunda autônoma (Kimi) | `system.py` (handler deep) |

### 🕵️ Sherlock / Knowledge

| Comando | Função | Arquivo |
|---------|--------|---------|
| `/sherlock` | SherlockNews: Painel Interativo de Monitoramento IA | `sherlock.py:62` |
| `/configure_news` | Personaliza nichos do SenseNews | `system.py` (handler news) |

### 👁️ Visão / Desktop

| Comando | Função | Arquivo |
|---------|--------|---------|
| `/print` | Screenshot rápido da tela sem análise | `vision.py:11` |
| `/watch` | Ativa vigilância de tela (modo AFK) | `vision.py:31` |
| `/watchoff` | Desativa vigilância de tela | `vision.py:51` |

### 📁 Google Drive

| Comando | Função | Arquivo |
|---------|--------|---------|
| `/drive` | Google Drive: listar, criar, enviar e baixar arquivos | `drive.py:74` |

### 🎙️ Transcrição

| Comando | Função | Arquivo |
|---------|--------|---------|
| `/transcrever` | Transcreve o próximo áudio enviado | `transcription/` (handler) |

### 📥 Instagram

| Comando | Função | Arquivo |
|---------|--------|---------|
| `/instascraper` | InstaScraper: Baixa vídeo do Instagram para o chat | `instascraper.py:37` |

### 💼 Vendas / CRM

| Comando | Função | Arquivo |
|---------|--------|---------|
| `/crm` | Lista histórico de leads qualificados | `sales.py:11` |
| `/scout` | Dispara campanha B2B Scout (leads qualificados) | `sales.py:148` |
| `/scout_config` | Configura parâmetros do Scout | `sales.py` (handler) |

### 🔄 LLM (controle de modelo)

| Comando | Função | Arquivo |
|---------|--------|---------|
| `/switch` | Alterna entre modelos LLM (opinião, performance) | `system.py:1081` |
| `/feedback` | Envia feedback/problema sobre o bot | `system.py:1145` |

### 📱 Terminal / MCP / WhatsApp (v3.9-3.12)

| Comando | Função | Arquivo |
|---------|--------|---------|
| `/terminal` | Executa comando shell no host (estilo Hermes) | `terminal.py:64` |
| `/mcp` | MCP: lista/invoca tools de servidores MCP | `mcp.py:46` |
| `/wa` | Status rápido do WhatsApp Vault | `whatsapp.py:19` |
| `/wa_config` | Painel de configuração do WhatsApp (hot-reload YAML) | `whatsapp_config.py:200` |
| `/wa_resend` | Re-processa uma mensagem WhatsApp específica | `whatsapp.py:62` |

---

## 🔄 Conciliação (Handlers × Menu azul)

**Status:** ✅ **Tudo conciliado (72 handlers, 72 menu items, 0 duplicatas, 0 faltantes).**

**Verificação automatizada:**
```bash
python -c "from aiogram.types import BotCommand; ..."
# ou via `tests/_check_cmds.py` (script de validação)
```

O menu azul (definido em `bot.py:setup_commands` linhas 60-205) é gerado
por `bot.set_my_commands(commands)` e aparece quando o usuário digita `/`
no chat Telegram. Ele reflete 100% dos handlers implementados.

---

## 🛠️ Como manter atualizado

Quando criar um novo handler em `src/channels/telegram/commands/<arquivo>.py`:

1. **Adicione o handler** com decorator `@dp.message(F.text.startswith("/novo_cmd"))` ou similar
2. **Adicione o BotCommand** correspondente em `bot.py:setup_commands()` com emoji + descrição curta
3. **Documente aqui** (HANDLERS_INVENTORY.md) na categoria apropriada

Quando remover um handler:

1. **Delete o handler** em `<arquivo>.py`
2. **Delete o BotCommand** correspondente em `bot.py:setup_commands()`
3. **Delete a entrada** aqui (HANDLERS_INVENTORY.md)

---

## 🔍 Cross-references

- **Handler registration** está em `bot.py:setup_handlers` (linhas 220-307)
- **BotCommand list** está em `bot.py:setup_commands` (linhas 60-205)
- **Catch-all message handler** (último) está em `bot.py:307` — tudo que chega aqui sem handler específico vai para a pipeline de mensagem livre

**Regra importante:** handlers específicos (`F.text.startswith("/x")`) devem ser
registrados **ANTES** do catch-all de mensagem livre, senão o catch-all engole.
Ver `bot.py:262-263` para o comentário.
