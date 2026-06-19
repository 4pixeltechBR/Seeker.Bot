# PROJECT_STATE — Seeker.Bot

> Fonte única de verdade. A IA lê este arquivo no início de toda sessão e o
> atualiza ao final de todo bloco de trabalho. Conversa contradiz arquivo →
> arquivo vence.

## Identidade
- **Projeto:** Seeker.Bot
- **Problema que resolve (1 frase):** Automação e execução de tarefas complexas, buscas na web e curadoria de dados a partir do Telegram de forma resiliente e autônoma.
- **Para quem (1 frase):** Victor (uso pessoal/produtividade) para gerenciar rotinas de desenvolvimento, monitoramento de desktop e assistência cognitiva em tempo real.
- **Critério de sucesso da validação:** Execução estável do loop de mensagens do Telegram, ativação íntegra das ferramentas Hermes adaptadas e funcionamento resiliente dos guardrails de ação.
- **Kill criteria (mata o projeto se):** Custos de APIs ultrapassarem limites planejados, loops de rede/rate-limits gerarem instabilidade crônica persistente ou quebra permanente da integração do Telegram.
- **Restrições:** Execução local em ambiente Windows do Victor, chaves de API armazenadas em .env local, processamento síncrono/assíncrono controlado via adapters.
- **Modo de calibração:** senior
- **Criado em:** 2026-06-11

## Mapa de fases
- [X] FASE 1 — Validação
- [X] FASE 2 — Especificação
- [X] FASE 3 — Arquitetura
- [X] FASE 4 — Segurança & Dados
- [X] FASE 5 — Versionamento & Estrutura
- [X] FASE 6 — Construção c/ Observabilidade
- [➔] FASE 7 — Homologação & Lançamento
- [ ] FASE 8 — Operação

(Marcação: `[➔]` fase atual · `[X]` concluída · `[ ]` futura)

## Fase atual / Sub-tarefa ativa
- **Fase:** FASE 7 — Homologação & Lançamento
- **Sub-tarefa ativa:** 7.1 — Auditoria de Segurança, Release v3.5 e Sincronização do Repositório Público
- **Está pronto quando:** Nenhuma credencial ou código comercial foi vazado para o repositório público, os READMEs e notas de release foram atualizados e o push foi completado com sucesso no GitHub.
- **Próximo passo explícito:** Obter feedback final do Victor sobre o status estável da release e iniciar o monitoramento operacional na fase 8.

## Decision Log (append-only — nunca editar entradas antigas)
| Data | Tipo | Decisão | Racional | Red Team (se T1) |
|------|------|---------|----------|------------------|
| 2026-06-11 | Tipo 2 | Inicialização da Governança | Criação do arquivo de estado persistente do projeto no diretório raiz do Seeker.Bot. | |
| 2026-06-11 | Tipo 2 | Fix: fallback needs_web=True → False no router | Quando a triagem semântica falhava (rate-limit/timeout), o router forçava needs_web=True, causando busca web desnecessária + queries duplicadas + guardrail disparando para intenções locais como lembretes. Fallback mudado para False. | |
| 2026-06-11 | Tipo 2 | Add LOCAL_ACTION_TRIGGERS regex | Lembretes, agendamentos e timers detectados antes de WEB_TRIGGERS para evitar falso-positivo de palavras como "agora" em frases como "me lembre agora". | |
| 2026-06-17 | Tipo 2 | Otimização do minerador do ViralX9 (caching + throttle) | O minerador disparava lookups para todos os 10 vídeos de cada canal na seed em toda execução, gerando mais de 1500 requisições e causando rate limit (429) e bloqueio do IP. Implementamos cache de mediana no estado persistente, pré-filtragem de vídeos vistos, e limitador de no máximo 2 tentativas de recálculo por ciclo. | |
| 2026-06-17 | Tipo 2 | Suporte a cookies.txt local para yt-dlp | Adicionado carregamento automático do arquivo `config/cookies.txt` (se existir) no `ydl_opts` do yt-dlp, permitindo que a autenticação do usuário seja enviada e previna a tela de confirmação de bot do YouTube. | |
| 2026-06-17 | Tipo 2 | Timeout e retentativas configurados no yt-dlp | Configurado `socket_timeout: 8` e `retries: 0` para evitar travamento de corotinas do scheduler quando a conexão do YouTube é interrompida ou rate-limitada. | |
| 2026-06-19 | Tipo 2 | Release v3.5-stable e Auditoria de Segurança | Sincronização e publicação da Sprint 12.1 no GitHub com exclusão absoluta de ferramentas e chaves proprietárias comerciais, validada por script de scanner de segredos. | |

## Backlog (ideias fora de escopo — não viram código sem decisão)
- Substituir `duckduckgo_search` por `ddgs` na ferramenta de busca.

## Stack travada (muda só via Pivot estrutural — decisão Tipo 1)
- Linguagem/runtime: Python 3.10+
- Banco: SQLite / Arquivos locais
- Auth: Tokens de API (Telegram, Gemini, etc.) via `.env`
- Deploy: Execução local / Servidor Windows
- Libs centrais: python-telegram-bot, google-generativeai
- **Custo mensal estimado de operação:** Baixo (apenas consumo de APIs se aplicável)

## Assumption Registry (crença sem evidência = risco, não fato)
| Acreditamos que | Evidência | Status |
|---|---|---|
| O guardrail com TTL resolve os falsos positivos sem quebrar a segurança | Testes manuais após alteração | Validado |

## Métricas do framework
- retrabalho: 0
- decisoes_revertidas: 0
- drift_detectado: 0
- gates_reprovados: 0
- paradas_de_seguranca: 0
- overrides: 0

## Post-mortems de fase
<!-- 3 linhas por fase encerrada: funcionou / revisaria / monitorar -->
