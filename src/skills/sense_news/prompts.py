"""
Seeker.Bot — SenseNews Prompts
src/skills/sense_news/prompts.py
"""

import json
import logging

log = logging.getLogger("seeker.sensenews")

NICHES = {
    "MODELOS & OPEN-WEIGHT": {
        "emoji": "🧠",
        "description": "Novos LLMs, VLMs, modelos de fundação, benchmarks e releases open-source",
        "objective": "Acompanhar o estado da arte e alternativas viáveis para execução local",
        "search_queries": [
            "new open weight LLM release",
            "best local models for ollama",
            "AI benchmark results today",
            "novos modelos de linguagem open source",
            "VLM vision language model latest",
        ],
    },
    "INFRA & OTIMIZAÇÃO": {
        "emoji": "⚡",
        "description": "Quantização, KV cache, inferência rápida, otimizações de runtime (vLLM, LM Studio)",
        "objective": "Sinalizar formas de rodar modelos maiores em hardware modesto (RTX 3060 12GB)",
        "search_queries": [
            "LLM KV cache optimization",
            "model quantization breakthrough",
            "run large LLMs on 12GB VRAM",
            "inferência LLM baixa memória",
            "new techniques to speed up LLM locally",
        ],
    },
    "AGENTES & AUTOMAÇÃO": {
        "emoji": "🤖",
        "description": "Tool-use, memória persistente, autonomous agents, computer/browser understanding",
        "objective": "Acompanhar a evolução de sistemas agentic para integrar no Seeker.Bot",
        "search_queries": [
            "AI agent tool use breakthrough",
            "autonomous agents computer use",
            "long term memory for AI agents",
            "automação de marketing usando IA",
            "novo framework agentic open source",
        ],
    },
    "CRIAÇÃO & CONTEÚDO": {
        "emoji": "🎬",
        "description": "TTS naturais, difusão de imagem, geração de vídeo, processamento de áudio",
        "objective": "Acompanhar as melhores ferramentas e APIs para criação e automação de conteúdo",
        "search_queries": [
            "AI video generation temporal consistency",
            "new TTS model open source natural",
            "text to video AI open source",
            "IA para anúncios e tráfego pago",
            "automating short form video AI",
        ],
    },
}

ANALYSIS_PROMPT = """Você é um analista experiente preparando dados para o "SenseNews — Sexta-feira 2.0+".

NICHO DE BUSCA: {niche_name}
OBJETIVO DESTE NICHO: {niche_objective}

RESULTADOS DA BUSCA BRUTOS:
{search_context}

Extraia as notícias, ferramentas, updates e movimentações mais importantes (últimas 24-72h).
Filtre ruído. Busque sinais que impactem projetos desenvolvidos localmente (RTX 3060) ou via cloud focados em automação, vídeo e marketing.

Responda APENAS neste JSON válido:
{{
  "analyses": [
    {{
      "title": "<título do trend>",
      "analysis": "<resumo factual do que rolou>",
      "impact": "<impacto real p/ autonomia, custo ou geração de conteúdo>",
      "source": "<Link original, se disponível>"
    }}
  ]
}}
"""

REPORT_PROMPT = """Você é o “SenseNews — Sexta-feira 2.0+”, meu analista diário do ecossistema de IA.

OBJETIVO
Fazer uma única pesquisa diária e entregar um único relatório, curto e útil, cobrindo:
- notícias e movimentos importantes do ecossistema de IA
- novos modelos, updates de modelos e quantizações
- otimizações para LLMs, runtimes e autonomia
- impacto em projetos de automação e inteligência artificial
- ideias adaptáveis
- riscos técnicos, operacionais, legais e de segurança

FOCO PRINCIPAL: SEEKER.BOT
Seeker.Bot é um agente autônomo para automação, percepção, memória e execução. Pode rodar localmente (RTX 3060 12GB) ou em cloud.

[PRIORIDADES]:
Monitorar melhores modelos locais/online, APIs baratas, tool-use, memória, multimodalidade, OCR, UI understanding e autonomia/segurança.

DADOS RECOLETADOS HOJE:
{analyses_text}

DATA: {date}
TEMAS COLETADOS: {total}

RÉGUAS DE DECISÃO
Só recomende troca de engine/stack se houver ganho de VRAM >= 15%, tempo >= 10% ou grande estabilidade/custo.
Diferencie "medido em GPU X" de "estimado".

ESTILO
Direto, técnico sem pedantismo, resumido, didático e sem repetição.

==== OUTPUT OBRIGATÓRIO EM MARKDOWN ====

# 📰 SenseNews — {date}
**Janela analisada:** Últimas 72h (prioridade) + complementos de até 30 dias.
**Estado do ecossistema hoje:** [1 frase sobre a vibe do ecossistema hoje]

## 2) NOTÍCIAS DO ECOSSISTEMA
[Agrupe em: Modelos, Infra, Vídeo/Áudio, Agentes, e Mercado/Segurança. Para cada:]
**[Título Curto]**
*Resumo:* [1 a 3 linhas]
*Por que importa:* [1 linha]
*Tags:* [Ex: [LLM] [VLM] [APLICÁVEL AGORA]]
*Fontes:* [URLs]

## 3) RADAR DO SEEKER.BOT
*   **Aplicável agora:** [Modelos locais/online, tool-use, memória, automação desktop]
*   **Ideia adaptável:** [Sugestão de workflow autônomo]
*   **Risco/Limitação:** [Segurança, telemetria, limitação de tokens API]

## 4) TOP 3 — IMPACTO DIRETO
[Para cada 1 dos 3 maiores impactos nos projetos:]
**[1. Nome do Item]**
*O que é:* [...]
*Por que importa:* [...]
*Fit no setup (RTX 3060/APIs):* [...]
*Custo uso/integração:* [...]
*Teste sugerido hoje:* [...]

## 5) TOP 3 — IDEIAS ADAPTÁVEIS
**[1. Notícia/Feature]**
*Ideia Central:* [...]
*Aplicação no Seeker.Bot:* [...]

## 6) TEMA DO DIA: [Nome do Tema]
*O que é / Por que existe:* [...]
*Como funciona:* [Até 5 bullets]
*Onde falha:* [...]
*Aplicação nos projetos:* [...]
*Links para Estudo:* [...]

## 7) RADAR DE RISCOS
*   **[Item]:** [Risco] → [Impacto] → [Fonte]

## 8) TOP 5 LINKS EXTRAS
1. [Link] — [Razão por que vale abrir]

## 9) NÃO PERCA ISSO
*   🎯 **1 coisa para testar:** [...]
*   💡 **1 ideia para anotar:** [...]
*   ⚠️ **1 risco para monitorar:** [...]
"""


def get_niches_for_user(user_niches: list[str] | None) -> dict:
    """
    Retorna um dicionário filtrado de NICHES baseado nas preferências do usuário.
    Se user_niches é None (primeira vez), retorna todos os NICHES padrão.
    Se user_niches é uma lista vazia, retorna um dicionário vazio.
    """
    if user_niches is None:
        # Primeira vez: usa defaults
        return NICHES

    if not user_niches or len(user_niches) == 0:
        # Usuário escolheu 0 nichos (improvável, mas tratamos)
        return {}

    # Filtra NICHES por nomes escolhidos
    filtered = {}
    for niche_name in user_niches:
        if niche_name in NICHES:
            filtered[niche_name] = NICHES[niche_name]
        else:
            log.warning(f"[sensenews] Nicho desconhecido: {niche_name}")

    return filtered if filtered else NICHES  # Fallback se nenhum niche for reconhecido

