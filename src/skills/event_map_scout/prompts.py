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

# Categorias de Busca Exaustivas — TODO evento que precise de som, luz, palco, banda ou estrutura
EVENT_CATEGORIES = {
    "AGROPECUARIO": [
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "rodeio" OR "festa do peão" OR "expo agropecuária"',
        f'"{last_year}" OR "{last_last_year}" "sindicato rural" "{{cidade}}" exposição OR feira',
        f'site:instagram.com OR site:tiktok.com "@" "{{cidade}}" "rodeio" OR "peão"'
    ],
    "AGRO_PREMIUM": [
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "vaquejada" OR "cavalgada" OR "comitiva" shows',
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "leilão" OR "leilão de gado" "show" OR "festa" OR "jantar"'
    ],
    "RELIGIOSO": [
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "festa do divino" OR "romaria" OR "festa do padroeiro"',
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "paróquia" programação festa shows',
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "cantata" OR "natal" OR "semana santa" programação'
    ],
    "MUNICIPAL": [
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "aniversário da cidade" programação shows',
        f'site:instagram.com OR site:tiktok.com "prefeitura de {{cidade}}" "aniversário" shows palco',
        f'"{{cidade}}" "agenda cultural" OR "programação cultural" {last_year} OR {current_year}'
    ],
    "JUNINO": [
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "festa junina" OR "arraial" OR "são joão" atrações',
        f'site:instagram.com "{{cidade}}" "arraial" shows'
    ],
    "SHOW_FESTIVAL": [
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "festival" OR "sertanejo" OR "pagode" atrações line-up',
        f'site:baladaapp.com.br OR site:ingressonacional.com.br OR site:bilheteriadigital.com OR site:sympla.com.br "{{cidade}}"'
    ],
    "GOVERNAMENTAL": [
        f'DIÁRIO OFICIAL "{{cidade}}" "contratação artística" OR "inexigibilidade" {last_year} OR {current_year}',
        f'licitação "{{cidade}}" "sistema de som" OR "estrutura de palco" OR "locação de palco" {current_year}',
        f'"{last_year}" OR "{current_year}" transferegov "{{cidade}}" evento OR cultura'
    ],
    "CORPORATIVO": [
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "congresso" OR "feira de negócios" OR "conferência" eventos',
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "convenção" OR "encontro de vendas" OR "confraternização" shows',
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "aniversário" "empresa" OR "loja" "inauguração" show OR banda'
    ],
    "FESTAS_PARTICULARES": [
        f'site:instagram.com OR site:tiktok.com "{{cidade}}" "sunset" OR "festa exclusiva" OR "baile" "atrações"',
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "formatura" OR "casamento" "banda" OR "palco" OR "estrutura"',
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "debutante" OR "15 anos" OR "bodas" "banda" OR "DJ"'
    ],
    "FESTAS_SAZONAIS": [
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "réveillon" OR "ano novo" OR "virada" show OR palco',
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "pool party" OR "open bar" OR "festa na piscina" DJ OR show',
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "micareta" OR "carnaval fora de época" OR "trio elétrico" OR "bloco"'
    ],
    "CULTURAL": [
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "carnaval" OR "folclore" programação shows',
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "festival gastronômico" OR "festival de cerveja" OR "festival do peixe" OR "food truck"'
    ],
    "ESPORTIVO": [
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "maratona" OR "torneio" OR "campeonato" encerramento show palco',
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "encontro de motos" OR "motoclube" OR "encontro de jipes" OR "carros antigos" show'
    ],
    "TURISMO_E_PRIVADO": [
        f'site:instagram.com OR site:tiktok.com "{{cidade}}" "clube" OR "parque" OR "resort" "shows" OR "atrações"',
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "clube" OR "parque aquático" "ingressos" "show"',
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "hotel" OR "pousada" OR "resort" "música ao vivo" OR "show" OR "animação"'
    ],
    "BARES_E_VIDA_NOTURNA": [
        f'site:instagram.com "{{cidade}}" "música ao vivo" OR "voz e violão" OR "sertanejo ao vivo" OR "pagode ao vivo"',
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "bar" OR "pub" OR "casa noturna" OR "boate" "banda" OR "show" OR "DJ"'
    ],
    "DATAS_COMEMORATIVAS": [
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "dia das mães" OR "dia dos namorados" OR "dia dos pais" show OR música',
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "páscoa" OR "dia das crianças" evento OR show OR programação'
    ],
    "EDUCACIONAL": [
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "colação de grau" OR "formatura" OR "semana universitária" show OR banda',
        f'"{last_year}" OR "{last_last_year}" "{{cidade}}" "escola" OR "colégio" "festa" OR "encerramento" "som" OR "palco"'
    ],
    "META_INTELIGENCIA": [
        f'"produtora de eventos" OR "empresa de eventos" "{{cidade}}" {last_year} OR {current_year}',
        f'"contratação de artista" OR "contratação de banda" "{{cidade}}" {last_year} OR {current_year}',
        f'site:instagram.com "{{cidade}}" "contrate" OR "orçamento" "som" OR "iluminação" OR "palco" OR "DJ"'
    ],
    "REDES_SOCIAIS_BROAD": [
        f'site:instagram.com "{{cidade}}" "ingressos" "line-up" OR "atração principal"',
        f'site:tiktok.com "{{cidade}}" "camarote" OR "área vip" OR "pista" ingressos shows',
        f'site:instagram.com "{{cidade}}" "agenda" OR "programação" "show" OR "música ao vivo" OR "sertanejo"'
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
