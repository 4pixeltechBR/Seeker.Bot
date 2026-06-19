# ShowDeck — Arquitetura de Software e Mapeamento Técnico

O **ShowDeck** é um painel de inteligência de vendas (CRM) estruturado como uma aplicação **Streamlit**, projetado especificamente para o mercado de shows e contratações artísticas públicas (prefeituras) e privadas. Ele funciona de forma integrada e simbiótica com o **Seeker.Bot**, utilizando sua base de dados cognitiva para gerar oportunidades comerciais de conversão acelerada, agrupamentos logísticos regionais e geração automática de pitches.

---

## 1. Visão Geral do Sistema

O ShowDeck serve como o "centro tático de controle" comercial das prospecções geradas pelo Seeker.Bot. A integração baseia-se no compartilhamento da base de dados SQLite do bot, onde o ShowDeck injeta tabelas adicionais específicas do fluxo de vendas (funil, contatos e atividades) ao lado das tabelas nativas de memória e entidades do agente.

```mermaid
graph TD
    subgraph Seeker.Bot Core
        DB[(seeker_memory.db)]
        Extractor[Extractor / Cognição] --> DB
        Cache[Search Cache / Contratos] --> DB
    end

    subgraph ShowDeck Apps (Streamlit)
        App[app.py - Main Dashboard] --> DataAccess[data_access.py]
        Kanban[1_Funil.py - Kanban] --> DataAccess
        Calendar[2_Calendario.py - Logística] --> DataAccess
        Search[3_Buscar.py - Busca Avançada] --> DataAccess
        Insights[4_Insights.py - Oportunidades] --> DataAccess
        LeadView[5_Lead.py - Dossier & Timeline] --> DataAccess
    end

    DataAccess -->|Queries / Escrita| DB
    DB -->|Metadados de Shows / View de Portes| DataAccess
```

---

## 2. Estrutura Física de Diretórios

A ferramenta ShowDeck está localizada sob a pasta de aplicativos do Seeker: `E:\Seeker.Bot\apps\showdeck`. Sua estrutura física é enxuta e segue o padrão recomendado para aplicações Streamlit multi-páginas:

```
E:\Seeker.Bot\apps\showdeck\
│   __init__.py
│   app.py                  # Dashboard macro e entrypoint
│   data_access.py          # Camada de persistência síncrona SQLite e caching
│   run.bat                 # Script de execução rápida
│   ui_components.py        # Design tokens e componentes visuais (Lumen 2.0)
│
└───pages\                  # Subpáginas carregadas dinamicamente
        1_Funil.py          # Painel Kanban (Fases do Pipeline)
        2_Calendario.py      # Heatmaps de sazonalidade e planejamento de rota
        3_Buscar.py         # Filtro avançado e grids de visualização de cards
        4_Insights.py       # Algoritmos de Growth (Circuitos, Pitches e Gaps)
        5_Lead.py           # Gestão individual do lead, timeline e dossiês
```

---

## 3. Modelo de Dados Integrado

O ShowDeck não possui um banco de dados isolado. Ele utiliza o SQLite do Seeker.Bot localizado no caminho absoluto:
`E:\Seeker.Bot\data\seeker_memory.db`

### Tabelas Criadas pelo ShowDeck:
1. **`crm_leads`**: Armazena o perfil dos leads coletados, dados de contatos, estimativas de orçamento e metadados de prioridade BANT.
   * *Campos principais:* `target_key` (PK), `cidade`, `nome_evento`, `status`, `score` (BANT), `priority_score`, `data_evento_mes`, `data_evento_ano`, `orcamento_estimado`, `decisor_nome`, `whatsapp`, `priority_reasons`, `dossier_html`, `pdf_path`.
2. **`crm_activities`**: Armazena a linha do tempo de interações comerciais realizadas com o lead (e-mails, reuniões, ligações, propostas).
   * *Campos principais:* `id` (PK Auto), `lead_target_key`, `timestamp`, `tipo`, `canal`, `resultado`, `descricao`.

### Tabelas e Views do Seeker.Bot Consumidas:
* **`view_porte_eventos_calculado`**: Uma view que analisa dados históricos do Seeker sobre contratações de shows no Eixo BR-153 para categorizar o porte financeiro real de cidades e eventos baseados nas faixas de gasto de contratações anteriores.
* **`grades_eventos` / `contratos_artisticos` / `artistas`**: Tabelas nativas do banco do Seeker populadas via portais de transparência pública, utilizadas para detalhar shows passados, CNPJs dos escritórios dos cantores e valores reais dos cachês.

---

## 4. Camada de Aplicação e Lógicas de Negócio

### 4.1 Caching e Concorrência (`data_access.py`)
Streamlit executa todo o script a cada interação de UI. Para evitar sobrecarga no banco SQLite e garantir tempos de resposta de sub-milissegundos, o ShowDeck implementa um sistema de cache síncrono por meio do decorator `@st.cache_data(ttl=30)`.
* **Escritas com Invalidação de Cache:** Sempre que um status é atualizado, uma nota é gravada ou uma atividade é inserida, a função chama explicitamente `st.cache_data.clear()`, forçando a atualização imediata dos dados na próxima renderização de UI.
* **Resiliência (Seeder Embutido):** Caso o banco de dados esteja vazio ou as tabelas do CRM não existam, o método `seed_demo_leads_if_empty()` é disparado no boot da aplicação, populando o CRM com leads reais simulados (Ex: Peão de Barretos, São João de Caruaru e Campina Grande) para manter o sistema funcional.

### 4.2 Motor de Priorização (`opportunity_engine.py`)
O score de prioridade diária exibido nos cards é gerado sob demanda combinando o BANT base (50% do peso) com heurísticas de mercado calculadas na classe `src/skills/seeker_sales/opportunity_engine.py`:
$$\text{Score Prioridade} = \text{BANT} \times 0.5 + \min(\text{Bônus Acumulado}, 60)$$

Os bônus são atribuídos a partir de 5 fatores principais:
1. **Aniversário de Cidade Redondo (Round Anniversary):** Múltiplos de 25 anos somam $+20$ pontos; múltiplos de 10 anos somam $+10$ pontos (indicadores de verbas excepcionais de comemorações públicas).
2. **Edições Consolidadas:** Nomes de eventos contendo "Xª edição" somam até $+12$ pontos para eventos maduros (orçamentos recorrentes e estáveis).
3. **Agrupamento Regional (Clusters):** Cidades com $\ge 3$ eventos ativos mapeados no mesmo mês somam $+12$ pontos (ou $+18$ pontos se $\ge 5$).
4. **Janela de Oportunidade Comercial:** Eventos planejados de 5 a 6 meses à frente recebem $+10$ pontos (sweet spot de decisão de line-up). Eventos muito próximos (menos de 4 meses) sofrem penalidade de $-5$ pontos devido à indisponibilidade de casting.
5. **Porte Populacional:** Bônus de $+15$ para cidades com $\ge 100k$ habitantes.

---

## 5. Mapeamento Visual e Design System (Lumen 2.0)

A interface do ShowDeck segue estritamente as diretrizes visuais do **Lumen 2.0** (`ui_components.py`):
* **Tipografia:** Uso da fonte *Outfit* importada via Google Fonts para substituir a fonte padrão do sistema.
* **Paleta Dark-Neon:** Fundo escuro profundo (Slate 950 - `#020617`), cards navy escuros (`#0B1329`), e acentos vibrantes em neon (Azul `#3B82F6` para geral, Violeta para contatos, Rosa para propostas, e Verde `#10B981` para negócios fechados).
* **Fricção Invisível e Quick Actions:** Cards no Kanban exibem badges de status e barras de BANT/Prioridade em HTML estilizado. As ações de alteração de status são discretas, integradas diretamente abaixo de cada card com `selectbox` compactos, e link para envio direto de mensagens customizadas via WhatsApp Web (`wa.me`) usando ganchos de BANT extraídos pelo Seeker.
* **Mapeamento de Rotas Logísticas:** A aba de insights calcula o frete compartilhado e sugere a contratação casada de palcos regionais no mesmo mês (gerando pitches em formato texto prontos para cópia e envio).

---

## 6. Comandos e Scripts de Execução

* **Inicialização Local do ShowDeck:**
  Para subir o servidor de desenvolvimento local, execute a partir do diretório raiz `E:\Seeker.Bot`:
  ```bash
  streamlit run apps/showdeck/app.py
  ```
  *(Ou chame o utilitário rápido `apps\showdeck\run.bat`)*

* **Consulta Rápida via Terminal:**
  Caso precise verificar a fila de prioridades diretamente do console sem subir o painel web:
  ```bash
  python -m src.skills.seeker_sales --window 6 --top 5
  ```
