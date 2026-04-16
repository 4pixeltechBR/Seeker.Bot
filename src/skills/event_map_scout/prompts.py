"""
Seeker.Bot — Event Map Scout Prompts
src/skills/event_map_scout/prompts.py

Define templates de busca e prompts para extração de Eventos.
O diferencial aqui é focar no HISTÓRICO (2024/2025) para prever 2026/2027.
"""

from datetime import datetime

current_year = datetime.now().year
last_year = current_year - 1
last_last_year = current_year - 2

# 10 Categorias Otimizadas (Incluindo Governamental e Tiktok)
EVENT_CATEGORIES = {
    "AGROPECUARIO": [
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "rodeio" OR "festa do peão" OR "expo agropecuária"',
        f'"{last_year}" OR "{last_last_year}" "sindicato rural" "{{cidade}}" exposição OR feira',
        f'site:instagram.com OR site:tiktok.com "@" "{{cidade}}" "rodeio" OR "peão"'
    ],
    "RELIGIOSO": [
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "festa do divino" OR "romaria" OR "festa do padroeiro"',
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "paróquia" programação festa shows'
    ],
    "MUNICIPAL": [
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "aniversário da cidade" programação shows',
        f'site:instagram.com OR site:tiktok.com "prefeitura de {{cidade}}" "aniversário" shows palco'
    ],
    "JUNINO": [
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "festa junina" OR "arraial" OR "são joão" atrações',
        f'site:instagram.com "{{cidade}}" "arraial" shows'
    ],
    "SHOW_FESTIVAL": [
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "festival de música" OR "sertanejo" atrações line-up',
        f'site:sympla.com.br OR site:eventbrite.com.br "{{cidade}}"'
    ],
    "GOVERNAMENTAL": [
        f'site:transparencia.{{cidade_slug}}.*.gov.br "contratação" "show" OR "palco"',
        f'DIÁRIO OFICIAL "{{cidade}}" "contratação artística" OR "inexigibilidade" {last_year} OR {current_year}',
        f'licitação "{{cidade}}" "sistema de som" OR "estrutura de palco" {current_year}',
        f'"{last_year}" OR "{current_year}" transferegov "{{cidade}}" evento OR cultura'
    ],
    "CORPORATIVO": [
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "congresso" OR "feira de negócios" OR "conferência" eventos',
    ],
    "CULTURAL": [
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "carnaval" OR "folclore" programação shows',
    ],
    "ESPORTIVO": [
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "maratona" OR "torneio" encerramento show palco',
    ]
}

EXTRACTION_PROMPT = """Você é um analista de inteligência de mercado B2B focado
em mapear eventos recorrentes e licitações para empresas de estrutura (palco, som, luz) e shows.

Sua tarefa exclusiva: Analisar os resultados de busca sobre a cidade de '{cidade}'
na categoria '{categoria}'. A busca intencionalmente trouxe eventos de {last_last_year} e {last_year}.

**O OBJETIVO E PREVER O FUTURO PELO PASSADO.**
Se um evento (ex: "32ª Expo") aconteceu em Julho de {last_year}, assumiremos que a 
33ª edição acontecerá em Julho de {current_year} (ou do próximo ano relevante).

Resultados da busca:
{search_context}

Extraia todos os eventos distintos e retorne APENAS um JSON válido no formato abaixo.
Se não houver eventos que necessitem de palco/show, retorne "eventos": []

Formato JSON Esperado:
{{
  "eventos": [
    {{
      "nome_evento": "<Nome oficial. Ex: 33ª ExpoAgro>",
      "cidade": "{cidade}",
      "categoria": "{categoria}",
      "periodo": "<Mês ou janela onde historicamente acontece. Ex: 1ª Quinzena de Julho>",
      "periodo_mes_num": <Mes em numero de 1 a 12. Ex: 7>,
      "historico_anos": "<Quais anos foram mencionados? Ex: [2024, 2025]>",
      "status_previsao": "<'recorrente_previsto', 'licitacao_aberta', 'passou'>",
      "porte_estimado": "<pequeno, médio ou grande. Pense no publico e atraçoes>",
      "valor_contrato_publico": "<Se a fonte for gov/transparencia e citar valores, ponha aqui. Ex: R$120.000, senao null>",
      "decisor_nome": "<Se a fonte citar presidente, organizador ou secretário. Senao null>",
      "decisor_cargo": "<Cargo do decisor, senao null>",
      "telefone": "<Telefone divulgado, senao null>",
      "instagram": "<@ se encontrado, senao null>",
      "fontes_urls": ["<urls das fontes de onde tirou os dados>"],
      "sinais_contratacao": "<Breve nota sobre qual é a chance real disso precisar de estrutura/show>",
      "score_oportunidade": <De 0 a 10. Levar em conta: historico, contato de decisor, porte>
    }}
  ]
}}

Responda APENAS o JSON e nada mais.
"""


SYNTHESIS_PROMPT = """Você é a IA do 'Event Map Scout', gerando um relatório comercial focado e direto
para um gerente de Vendas. O relatório é sobre a cidade de: {cidade} - {estado}.

Estes são os eventos PREDITIVOS consolidados e deduplicados pela engine, que deverão 
ocorrer em {current_year}/{next_year}:
{events_json}

INSTRUÇÕES DE FORMATAÇÃO DO RELATÓRIO MARDKOWN:
1. Comece com "## Mapa Estratégico: {cidade} - {estado}"
2. Abaixo um breve sumário (Ex: Encontrados X eventos com score > 7).
3. Faça uma sessão "🔥 Top Oportunidades Próximas" focada nos eventos de maior score que ainda vão acontecer nos próximos 3-4 meses (considerando que estamos no mes {current_month}).
4. Após isso, liste os eventos categorizados pelos seus respectivos portes ou nichos, exibindo os dados críticos:
   - Mês e Nome, Telefone, Contato de Decisão, Investimentos Históricos, Redes Sociais.
5. Se não houver eventos, avise que a cidade parece não ter mercado mapeável na web.
6. A formatação deve ser limpa. Use Emojis com parcimônia, negrito para destacar valores ou contatos e evite encher linguica.

REGRAS:
- Apenas retorne o markdown final.
- Nenhuma tag de abertura (como ```markdown)
"""
