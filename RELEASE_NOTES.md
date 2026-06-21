# Seeker.Bot v3.7 — "Instagram SaveAsBot & Chain-of-Thought Relevance Filtering" 🚀🎥

Esta release traz a reformulação completa do mecanismo de download de Reels do Instagram no Telegram (SaveAsBot) e um avanço na precisão da curadoria de conteúdo com o filtro de relevância baseado em Chain-of-Thought (CoT).

## 🚀 Novidades

### 1. InstaScraper como SaveAsBot (Download Direto)
- **Fricção Zero:** O comando `/instascraper` foi reformulado no Telegram. Em vez de abrir menus interativos ou requerer comandos complexos, agora basta enviar a URL de um post diretamente no chat para que o download seja disparado imediatamente.
- **Entrega Inteligente:** Envia a mídia baixada nativamente no formato de vídeo do Telegram (`send_video` para arquivos ≤ 50MB) ou como arquivo binário (`send_document` para arquivos maiores que 50MB, preservando a qualidade original e evitando o teto de compressão do Telegram).
- **Limpeza de Espaço:** Limpeza automática do arquivo temporário no disco local imediatamente após a conclusão do envio no Telegram.

### 2. Filtro de Relevância com Chain-of-Thought (CoT) para Vídeos
- **Metadados Ricos:** A etapa de minerador de canais agora coleta informações contextuais completas do vídeo candidatas a outliers (descrição até 700 caracteres, tags e categorias) usando o yt-dlp.
- **Raciocínio Estruturado (CoT):** O prompt do modelo de linguagem em nível `FAST` exige que ele faça um raciocínio interno avaliando se o conteúdo e o título clickbait de fato se alinham com os tópicos permitidos no nicho (`NICHE_TOPICS`). A IA devolve uma explicação passo a passo (`raciocinio_relevancia`) e a decisão estruturada em JSON, eliminando vídeos off-topic indesejados.
- **Testes Unitários:** Adicionado suporte a testes automatizados validando a classificação semântica com dados reais de clickbaits e conteúdos limítrofes.

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

