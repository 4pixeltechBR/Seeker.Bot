"""
Seeker.Bot — ViralClip Curator Prompts
src/skills/viralclip_curator/prompts.py

Configuração de nichos e prompts para curadoria de tendências.
"""

# ── Nichos monitorados ────────────────────────────────────

NICHES = {
    "BIO-ESCALAR": {
        "description": "Biotecnologia, biohacking, longevidade, CRISPR, medicina regenerativa, neurotech",
        "search_queries": [
            "biotecnologia tendência 2026",
            "biohacking novidade",
            "CRISPR descoberta recente",
            "longevidade pesquisa breakthrough",
            "neurotech implante cerebral novidade",
            "medicina regenerativa avanço",
        ],
        "keywords_pt": ["biotecnologia", "biohacking", "CRISPR", "longevidade", "neurotech", "genética"],
        "keywords_en": ["biotech trending", "biohacking news", "CRISPR breakthrough", "longevity research"],
    },
    "FORENSIC TECH": {
        "description": "Tecnologia forense, perícia digital, OSINT, investigação cibernética, análise de evidências",
        "search_queries": [
            "forensic technology new tool",
            "perícia digital técnica nova",
            "OSINT tool trending",
            "cyber forensics case study",
            "digital evidence analysis breakthrough",
            "investigação cibernética ferramenta",
        ],
        "keywords_pt": ["perícia digital", "forense", "OSINT", "investigação", "evidência digital"],
        "keywords_en": ["digital forensics", "OSINT trending", "cyber investigation", "forensic tech"],
    },
    "SÍTIO 404": {
        "description": "Internet profunda, sites abandonados, arqueologia digital, cultura web perdida, urbex digital",
        "search_queries": [
            "lost websites internet archaeology",
            "abandoned internet pages found",
            "deep web curiosidades",
            "internet culture lost media",
            "wayback machine discovery",
            "sites abandonados internet brasileira",
        ],
        "keywords_pt": ["internet antiga", "site abandonado", "deep web", "arqueologia digital", "lost media"],
        "keywords_en": ["internet archaeology", "lost websites", "abandoned web", "digital urbex"],
    },
    "CRIMES DIGITAIS": {
        "description": "Cibercrime, fraudes digitais, vazamentos, engenharia social, golpes, segurança",
        "search_queries": [
            "cibercrime Brasil 2026",
            "golpe digital novo tipo",
            "vazamento dados empresa",
            "ransomware attack recent",
            "engenharia social caso real",
            "fraude digital tendência",
        ],
        "keywords_pt": ["cibercrime", "golpe digital", "vazamento", "ransomware", "engenharia social", "fraude"],
        "keywords_en": ["cybercrime trending", "data breach news", "ransomware attack", "social engineering"],
    },
}

# ── Prompts ───────────────────────────────────────────────

TREND_SCORE_PROMPT = """Você é um curador de conteúdo para canais de vídeo no YouTube/TikTok/Reels.

NICHO: {niche_name} — {niche_description}

RESULTADOS DA BUSCA:
{search_context}

Avalie cada resultado como potencial pauta de vídeo viral. Critérios:
- NOVIDADE: É notícia recente (últimos 7 dias)? Ou requentado?
- VIRAL POTENTIAL: Tem gancho emocional, surpresa, polêmica ou utilidade?
- VISUAL: Dá pra fazer vídeo curto (60-90s) com isso?
- NICHO FIT: Encaixa no perfil do canal?

Responda APENAS JSON:
{{
  "trends": [
    {{
      "title": "<título curto e chamativo pro vídeo>",
      "hook": "<frase de abertura do vídeo, 1 linha, gera curiosidade>",
      "source": "<URL ou nome da fonte>",
      "score": <0-100, potencial viral>,
      "reasoning": "<1 linha: por que esse tema funciona>",
      "format": "<short|longo|thread|comparativo>",
      "rank": <posição 1 a 3>
    }}
  ]
}}

Retorne no MÁXIMO 3 trends por busca. Só inclua score >= 60.
Se nada for bom o suficiente, retorne {{"trends": []}}.
"""

DIGEST_PROMPT = """Compile as melhores pautas do dia num digest executivo para produção de vídeo.
Formate em HTML compatível com Telegram (<b>, <i>, <a>).

PAUTAS DO DIA:
{all_trends}

Crie o output:
<b>🎬 VIRALCLIP CURATOR — DIGEST DIÁRIO</b>
<b>Nichos: {niches_list}</b>

Para cada pauta (máximo 5, extraídas do JSON):

<b>Tema #{rank}: {title}</b> [{niche}]
<b>Score:</b> {score}/100 | <b>Formato:</b> {format}
<b>🎣 Hook:</b> <i>{hook}</i>
<b>💡 Por que funciona:</b> {reasoning}
<b>📎 Fonte:</b> {source}

REGRA: Não adicione colchetes no número da pauta (ex. use "#1", nunca "# [1]"). 
Se a fonte for um link quebrado ou vazio, escreva "Busca Ativa".

Ao final:
<b>📊 RESUMO DO DIA</b>
<Quantas pautas por nicho, qual nicho está mais quente>
"""
