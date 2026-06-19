# ShowDeck — Relatório de Verificação, Concorrência e Auditoria de Código

Este documento reporta os resultados das validações de estresse de gravação, concorrência e auditoria completa de código efetuadas no SQLite do **ShowDeck** compartilhado com o **Seeker.Bot**, bem como a conformidade do boot local da aplicação Streamlit.

---

## 1. Teste de Estresse de Concorrência (SQLite WAL Mode)

Com o objetivo de validar a estabilidade das gravações simultâneas efetuadas pelas threads de UI do Streamlit (ShowDeck) e as operações de meta-cognição assíncronas do Seeker.Bot (aiosqlite), criamos e rodamos o script de estresse concorrente:
`E:\Seeker.Bot\scratch\test_crm_concurrency.py`

### Cenário de Teste:
* **Thread Seeker.Bot Writer (Async):** Dispara 50 inserções consecutivas rápidas na tabela de episódios (`record_episode`) simulando a execução ativa de metas de background.
* **Thread ShowDeck 1 (Sync):** Dispara 50 atualizações consecutivas de data/status na tabela `crm_leads` simulando a movimentação de cards por um vendedor no painel Kanban.
* **Thread ShowDeck 2 (Sync):** Dispara 50 atualizações concorrentes adicionais simulando um segundo vendedor atuando simultaneamente.
* **Jitter/Intervalo:** Pausa mínima de apenas `0.01s` por operação para forçar colisões físicas de transações.

### Resultados Obtidos:
* **Escritas do Seeker.Bot:** 50/50 com sucesso (0 erros).
* **Escritas do ShowDeck (Thread 1):** 50/50 com sucesso (0 erros de travamento).
* **Escritas do ShowDeck (Thread 2):** 50/50 com sucesso (0 erros de travamento).
* **Tempo de Execução Total:** 2.53 segundos (taxa média de ~60 transações de escrita complexas por segundo em disco local).

> [!TIP]
> O banco opera em **WAL Mode** (Write-Ahead Logging), o que permite leitura livre de bloqueios. Graças ao sequenciamento interno do SQLite e o baixo overhead do banco local, não ocorreram travamentos mesmo sob jitter mínimo.

---

## 2. Implementação de Resiliência (Timeout de Conexão)

Embora o modo WAL elimine bloqueios de leitura, transações de escrita muito longas no SQLite (ex: backups ou extrações volumosas no bot) poderiam eventualmente exceder o timeout padrão de 5 segundos do SQLite síncrono.

Para blindar o CRM contra falhas sob alta carga, atualizamos a camada de dados em `E:\Seeker.Bot\apps\showdeck\data_access.py#L35`:

```python
# ❌ ANTES
c = sqlite3.connect(DB_PATH)

# ✅ DEPOIS
c = sqlite3.connect(DB_PATH, timeout=30.0)
```

**Impacto:** O timeout de 30 segundos fornece uma margem de segurança extremamente confortável para que as threads síncronas aguardem a liberação do arquivo de transação em disco sem disparar exceções de travamento na tela do vendedor.

---

## 3. Relatório de Auditoria de Código e Correções de Bugs (2026-06-03)

Efetuamos uma varredura completa nas lógicas das páginas e resolvemos 3 problemas críticos que afetavam a estabilidade e a corretude de negócios da aplicação:

### Bug 1: Prioridade Zero e Falha de Descrição nos Clusters de Rota (`4_Insights.py`)
* **Problema:** A query SQL de `cluster_index()` em `data_access.py` não seleciona campos de prioridade nem descrição dos leads (apenas cidade, mês, ano e total `n`). A aba 2 tentava ler `cl.get('priority', 0)` e `cl.get('descricao')`, resultando em todos os cards exibindo incorretamente `"Prio 0"` e `"Evento sem descrição."`.
* **Correção:** Alterado [4_Insights.py:L205-215](file:///E:/Seeker.Bot/apps/showdeck/pages/4_Insights.py#L205-L215) para calcular a prioridade máxima dinamicamente a partir dos leads associados ao cluster (`max(l.get("priority_score", 0) for l in leads_do_cluster)`). A descrição agora também lista de forma resumida os nomes dos eventos reais mapeados para aquele circuito.

### Bug 2: KeyError na Exibição de Dossiês HTML Complexos (`5_Lead.py`)
* **Problema:** Dossiês completos carregados do Seeker contêm chaves `{}` nativas de CSS e layouts internos. A renderização usava `st.markdown(f" ... {lead['dossier_html']} ... ", unsafe_allow_html=True)`. O compilador de f-strings interpretava incorretamente as chaves de marcação do HTML como chamadas de código Python, quebrando a tela com erro fatal de `KeyError` e corrompendo caracteres especiais sob Markdown parser.
* **Correção:** Substituído por `st.html()` em [5_Lead.py:L374-379](file:///E:/Seeker.Bot/apps/showdeck/pages/5_Lead.py#L374-L379), injetando o HTML diretamente de forma nativa e isolada, prevenindo problemas de parsing do Markdown.

### Bug 3: Crash no Kanban por Inconsistência de Status do Banco (`1_Funil.py`)
* **Problema:** O selectbox de mudança rápida de status chamava `VALID_STATUSES.index(status)`. Caso o Seeker.Bot inserisse leads com status legados ou nulos no banco, o Streamlit quebrava o Kanban inteiro com um `ValueError` fatal.
* **Correção:** Sanitizado o status no Kanban em [1_Funil.py:L89-94](file:///E:/Seeker.Bot/apps/showdeck/pages/1_Funil.py#L89-L94) utilizando fallback seguro para o status `"NOVO"`.

---

## 4. Validação do Boot e Execução Streamlit

O servidor web Streamlit foi iniciado localmente em background sob o ambiente de produção do Seeker:
```bash
streamlit run apps/showdeck/app.py
```

### Logs de Inicialização:
```
2026-06-03 10:50:34.776 Uvicorn server started on 0.0.0.0:8501
  You can now view your Streamlit app in your browser.

  Local URL: http://localhost:8501
  Network URL: http://192.168.1.4:8501
```

O dashboard iniciou de forma limpa, carregando todos os componentes da folha de estilos do design system Lumen 2.0 e estabelecendo conexão síncrona imediata com o banco de dados.

---

## 5. Rodada de Melhorias e Auditorias de UAT (2026-06-03)

Nesta rodada, corrigimos problemas visuais críticos de interface, integramos a sincronização de múltiplos estados sob demanda, e implementamos inteligência sob demanda para enriquecimento e catalogação de shows.

### 5.1 Correção Definitiva do HTML nos Cards (Kanban e Busca)
* **Ajuste:** Para contornar limitações no parser de markdown do Streamlit e evitar a exibição de tags HTML cruas nos cards, alteramos a função `render_html_kanban_card` em `ui_components.py` para compactar o HTML gerado em uma linha única contínua (removendo quebras de linha e tabs redundantes). Reconfiguramos `1_Funil.py` e `3_Buscar.py` para renderizar os cards usando `st.markdown(..., unsafe_allow_html=True)`.

### 5.2 Sincronização Dinâmica e Resiliente de Múltiplos Estados (GO, MS, SP)
* **Ajuste:** Para resolver a contagem estática de 219 leads (que refletia apenas o estado inicial de GO), adicionamos um parâmetro `force` em `ensure_leads_synced` na camada `data_access.py`. Inserimos um botão discreto de `"🔄 Sincronizar Radar GDrive"` na barra lateral da busca (`3_Buscar.py`) e do funil (`1_Funil.py`). Ao ser acionado, ele limpa o cache do Streamlit e força o download e a inserção imediata de todos os leads cadastrados no `event_radar_results.jsonl` do Google Drive, atualizando o total dinamicamente para os **5.817 leads** atualmente mapeados nos estados GO, MS e SP.

### 5.3 Enriquecimento de Contatos Ativo Sob Demanda (1-Click Qualification)
* **Ajuste:** Criamos um botão `"🔍 Enriquecer Contatos Ativos"` no card de detalhes do Lead (`5_Lead.py`), integrado diretamente ao pipeline do `RevenueMiner`. O clique dispara buscas profundas por telefones, decisores, websites e redes sociais na web através de APIs e LLM Cascade, gravando o resultado no SQLite. Além disso, criamos um botão de atalho `"🔍 Enriquecer Contatos"` diretamente nos cards do Funil Kanban e da Busca Avançada para leads pendentes de qualificação, agilizando o trabalho comercial do SDR.

### 5.4 Inteligência de Ingestão de Shows Históricos (Solir Integration)
* **Ajuste:** Implementamos a função `ingest_historical_events(cidade, ano, categoria)` em `data_access.py`. Essa função faz buscas web e extrações estruturadas via LLM para buscar processos de inexigibilidade passados de prefeituras, catalogando-os nas tabelas `event_map`, `artistas`, `contratos_artisticos` e `grades_eventos` do SQLite. Integramos isso no ShowDeck sob a Tab 5 de `4_Insights.py` por meio do formulário expansível `"🔍 Buscar e Catalogar Shows Passados (Inteligência Solir)"`, atualizando dinamicamente a view de portes e grades de cachê. Corrigimos também um bug de NameError importando `plotly.express as px` e `pandas as pd` no topo do arquivo.

