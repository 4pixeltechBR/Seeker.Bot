"""
Prompts e Configurações de Inteligência para o Revenue Hunter v3.

v3 — Enriquecimento em 2 fases:
- BANT Scoring com schema rico (BANT sub-scores + porte + histórico)
- Enrichment Search por lead específico (busca 2ª fonte de contato real)
"""

# ── Escopo Primário: Estado de Goiás ──
TARGET_REGIONS = [
    "Goiás",
]

# Expansão futura
TARGET_STATES_SECONDARY = [
    "Minas Gerais",
    "Mato Grosso",
    "Tocantins",
    "Distrito Federal",
]

TARGET_EVENTS = [
    "festa de peão",
    "expo agropecuária",
    "rodeio",
    "aniversário da cidade",
    "festival cultural",
    "festa religiosa",
    "divino pai eterno eventos",
    "casamentos cerimonialistas",
    "festas de 15 anos",
    "festa junina",
    "vaquejada",
    "show sertanejo",
]

TRIGGER_KEYWORDS = [
    "sindicatos rurais segundo semestre 2026",
    "prefeituras interior eventos",
    "nova secretaria cultura",
    "contratação shows estrutura",
    "organizadores de eventos",
    "licitação palco som iluminação",
    "produtor de eventos goiás",
    "empresa de eventos goiás",
]

# ── FASE 1: Discovery + BANT Scoring ──────────────────────────────────────────

BANT_SCORE_PROMPT = """Você é um especialista em Prospecção B2B (SDR) para empresas de estrutura e shows.
Seu objetivo: garimpar nos resultados de busca abaixo oportunidades reais de eventos em Goiás.

ATENÇÃO:
- Ano atual: {current_year}. Priorize eventos futuros ou do segundo semestre. Penalize eventos já realizados (score < 40).
- Foco: eventos de pequeno e médio porte com acesso direto ao decisor.
- Seja conservador: score >= 70 só para oportunidades com datas futuras confirmadas e histórico.

Query pesquisada: '{query}'
{search_context}

Extraia TODOS os leads viáveis com o JSON abaixo. Se não encontrar nada real, retorne "leads": [].

{{
  "leads": [
    {{
      "nome_evento": "<Nome do Evento>",
      "cidade": "<Cidade - GO>",
      "tipo_contratante": "<Prefeitura / Igreja / Sindicato / Cerimonialista / Espaço Privado>",
      "periodo": "<Data, mês ou trimestre previsto>",
      "score": <0 a 100>,
      "score_budget": <0 a 25 — indícios de orçamento disponível>,
      "score_authority": <0 a 25 — acesso ao decisor identificado>,
      "score_need": <0 a 25 — necessidade clara de estrutura/shows>,
      "score_timing": <0 a 25 — timing favorável, evento futuro>,
      "porte_estimado": "<pequeno / médio / grande>",
      "edicoes_anteriores": "<quantas edições identificadas, ou 'primeira edição' se novo>",
      "artistas_anteriores": "<nomes de artistas ou bandas que já se apresentaram, ou null>",
      "orcamento_estimado": "<faixa em R$ estimada ex: R$50k-R$150k, ou null se sem indício>",
      "decisor_provavel": "<Nome ou Cargo do decisor real>",
      "instagram": "<@ se encontrado nos resultados, senão null>",
      "telefone": "<número real encontrado nos resultados, senão null>",
      "whatsapp": "<número com DDD se encontrado, senão null>",
      "website": "<URL se encontrada, senão null>",
      "sinais_contratacao": "<Evidências concretas de contratação: edições passadas, chamadas públicas, porte>",
      "justificativa": "<Por que é uma boa oportunidade agora e qual o ângulo de abordagem>"
    }}
  ]
}}

Responda APENAS o JSON. Sem texto antes ou depois.
"""

# ── FASE 2: Enriquecimento por lead específico ─────────────────────────────────

ENRICH_PROMPT = """Você é um especialista em inteligência comercial. Analise os resultados de busca abaixo
sobre o evento '{nome_evento}' em '{cidade}' e extraia/complemente os dados de contato e histórico.

É MANDATÓRIO extrair telefones reais de contato:
- Se for PREFEITURA ou EVENTO PÚBLICO: encontre o telefone do gabinete, da Secretaria de Cultura/Turismo ou celular de licitação.
- Se for PRIVADO: encontre WhatsApp ou telefone direto do organizador.

DADOS JÁ COLETADOS:
{lead_atual}

RESULTADOS DA BUSCA DE ENRIQUECIMENTO:
{enrich_context}

Retorne JSON com os campos abaixo. Se um campo já está correto nos dados atuais, mantenha. Se encontrou algo melhor, atualize.
Se não encontrou informação nova, mantenha null.

{{
  "instagram": "<@ atualizado ou null>",
  "telefone": "<telefone real encontrado ou null>",
  "whatsapp": "<whatsapp com DDD ou null>",
  "website": "<URL real encontrada ou null>",
  "facebook": "<URL do Facebook se encontrado ou null>",
  "decisor_nome": "<Nome real do decisor se encontrado, ou null>",
  "decisor_cargo": "<Cargo do decisor, ex: Secretário de Cultura, Presidente do Sindicato>",
  "artistas_anteriores": "<Lista de artistas/bandas já confirmados ou que já se apresentaram>",
  "edicoes_anteriores": "<número de edições ou descrição do histórico>",
  "orcamento_estimado": "<faixa em R$ se encontrou evidência concreta, senão null>",
  "observacoes": "<qualquer informação relevante não coberta pelos campos acima>"
}}

Responda APENAS o JSON.
"""

# ── FASE 3: Dossiê Final ───────────────────────────────────────────────────────

DOSSIER_PROMPT = """Você é o Seeker SDR — especialista em abordagem comercial para empresas de estrutura e shows em Goiás.
Com base nos dados do lead, crie um dossiê completo, com hierarquia visual e leitura agradável.

LEAD ENRIQUECIDO:
{lead_json_string}

INSTRUÇÕES DE FORMATAÇÃO (CRÍTICO - MODO LUMEN 👁️):
1. MANTENHA OBRIGATORIAMENTE TODAS AS QUEBRAS DE LINHA E ESPAÇAMENTOS (RESPIROS VERTICAIS) do modelo abaixo!
2. NUNCA gere o texto espremido em um único bloco. Cada tópico deve iniciar em uma nova linha.
3. Formate em HTML válido para o Telegram (apenas <b>, <i>, <code>).
4. O resultado final DEVE ter esta exata estrutura hierárquica e visual:

<b>🎯 {nome_evento} — {cidade}</b>

<b>📊 SCORE BANT: {score}/100</b>
<code>{score_bar}</code> {score_label}

<b>📋 PERFIL E HISTÓRICO</b>
• <b>Contratante:</b> {tipo_contratante}
• <b>Período:</b> {periodo}
• <b>Porte:</b> {porte_estimado}
• <b>Histórico:</b> {edicoes_anteriores}
• <b>Artistas:</b> {artistas_anteriores}
• <b>Investimento:</b> {orcamento_estimado}

<b>📞 CONTATOS & LINKS</b>
• <b>Decisor:</b> {decisor_nome} ({decisor_cargo})
• <b>Canais:</b> {link_card}

<b>🕵️ SINAIS DE CONTRATAÇÃO</b>
<i>{sinais_contratacao}</i>
"""
