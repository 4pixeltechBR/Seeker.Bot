"""
Seeker.Bot — SenseNews Prompts
src/skills/sense_news/prompts.py
"""

NICHES = {
    "BIO-ESCALAR": {
        "emoji": "🧬",
        "description": "Biotecnologia, biohacking, longevidade (CRISPR), medicina regenerativa e neurotech (implantes cerebrais)",
        "objective": "Explorar a fronteira da evolução humana e biológica",
        "search_queries": [
            "CRISPR breakthrough discovery",
            "biohacking longevity news",
            "neurotech brain implant update",
            "medicina regenerativa avanço",
            "biotecnologia tendência",
            "longevidade pesquisa resultado",
            "gene editing clinical trial results",
        ],
    },
    "FORENSIC TECH": {
        "emoji": "🔍",
        "description": "Tecnologia forense, perícia digital, OSINT, investigação cibernética e análise de evidências digitais",
        "objective": "Mostrar os bastidores técnicos de investigações modernas e ferramentas de detetive digital",
        "search_queries": [
            "digital forensics new tool",
            "OSINT investigation technique",
            "perícia digital caso real",
            "cyber forensics breakthrough",
            "análise evidência digital",
            "open source intelligence trending",
            "forensic technology law enforcement",
        ],
    },
    "SÍTIO 404": {
        "emoji": "🕳️",
        "description": "Arqueologia digital, internet profunda, sites abandonados, cultura web perdida e o lado obscuro da memória da rede",
        "objective": "Capturar o fascínio pela nostalgia e pelo mistério de espaços digitais esquecidos",
        "search_queries": [
            "lost websites internet archaeology",
            "abandoned web pages discovered",
            "deep web curiosidades",
            "internet culture lost media found",
            "wayback machine discovery",
            "forgotten websites rediscovered",
            "digital archaeology internet history",
        ],
    },
    "CRIMES DIGITAIS": {
        "emoji": "🚨",
        "description": "Cibercrime, engenharia social, grandes vazamentos de dados, ransomware e novos tipos de golpes digitais",
        "objective": "Alerta e curiosidade sobre as táticas de ataque e defesa na segurança da informação atual",
        "search_queries": [
            "cibercrime novo golpe",
            "ransomware attack recent",
            "data breach major",
            "engenharia social caso real",
            "vazamento dados empresa",
            "cybercrime arrest prosecution",
            "new phishing technique discovered",
        ],
    },
}

ANALYSIS_PROMPT = """Você é um analista de inteligência especializado no nicho "{niche_name}".

DESCRIÇÃO DO NICHO: {niche_description}
OBJETIVO: {niche_objective}
ANO ATUAL: {year}

RESULTADOS DA BUSCA:
{search_context}

Analise os resultados e extraia os temas mais relevantes e RECENTES.
Para cada tema, produza uma análise profunda — não apenas resumo, mas CONTEXTO e IMPACTO.

REGRAS:
- Mínimo 2 temas, máximo 4
- Apenas temas de {year} ou muito recentes
- Ignore notícias requentadas ou genéricas
- Cada análise deve ter substância (não apenas "X aconteceu")

Responda APENAS JSON:
{{
  "analyses": [
    {{
      "title": "<título descritivo do tema>",
      "analysis": "<análise de 2-3 frases: o que aconteceu, por que importa, contexto>",
      "impact": "<1 frase: impacto prático ou consequência>",
      "source": "<URL ou nome da fonte principal>",
      "relevance": <1-10, quão relevante pro nicho>
    }}
  ]
}}
"""

REPORT_PROMPT = """Compile estas análises num relatório de inteligência coeso em Markdown.

DATA: {date}
TOTAL DE TEMAS: {total}

ANÁLISES:
{analyses_text}

Gere um relatório profissional com esta estrutura:

# 📰 SenseNews — Relatório de Inteligência ({date})

## Resumo Executivo
(3-4 linhas: panorama geral do dia, o que se destaca, tendências cruzadas)

## 🧬 BIO-ESCALAR
(Temas do nicho com análise)

## 🔍 FORENSIC TECH
(Temas do nicho com análise)

## 🕳️ SÍTIO 404
(Temas do nicho com análise)

## 🚨 CRIMES DIGITAIS
(Temas do nicho com análise)

## Conexões e Padrões
(Se houver conexões entre nichos diferentes, destaque. Senão, omita esta seção.)

REGRAS:
- Markdown puro (será convertido em PDF)
- Prosa analítica, não lista de bullets
- Tom: analista de inteligência escrevendo pra decisor
- Cada seção de nicho: só inclua se houver temas. Omita nichos sem dados.
"""
