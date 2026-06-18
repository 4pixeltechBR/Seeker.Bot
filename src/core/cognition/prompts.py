"""
Seeker.Bot — Cognition Prompts
src/core/cognition/prompts.py

Todos os system prompts do assistente cognitivo.

Separados do pipeline porque:
1. São iterados independentemente (tom, instruções, módulos)
2. God Mode adiciona instruções — composição, não herança
3. Futuramente: A/B test de prompts sem tocar no pipeline

Phase 3: PromptBundle — unifica DeepSeek prefix caching (auto) + Gemini explicit caching.
Builders retornam bundle com (stable_prefix, dynamic_suffix) para permitir granular
caching por ambos providers.
"""

import os
from dataclasses import dataclass

# Nome configurável do assistente (default: Seeker)
ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", "Seeker")


# ─────────────────────────────────────────────────────────────────────
# PROMPTBUNDLE — Phase 3: Unified Caching Abstraction
# ─────────────────────────────────────────────────────────────────────


@dataclass
class PromptBundle:
    """
    Encapsula um prompt estruturado para cache unificado.

    Estratégia:
      - stable_prefix: Conteúdo 100% determinístico (SYSTEM_BASE, módulos)
      - dynamic_suffix: Conteúdo que muda per-request (date_context, session)

    DeepSeek (Phase 1): Cache automático dos primeiros ~3.5k tokens (stable_prefix)
    Gemini (Phase 2): Cache explícito se |stable_prefix| >= 4000 tokens

    Backward compatibility: Providers podem tratar como str(stable_prefix + dynamic_suffix)
    """

    stable_prefix: str
    dynamic_suffix: str

    def to_string(self) -> str:
        """Concatena para uso em providers antigos."""
        return self.stable_prefix + self.dynamic_suffix

    def __str__(self) -> str:
        """Permite usar PromptBundle onde str era esperado."""
        return self.to_string()

    @property
    def total_length(self) -> int:
        """Total de caracteres."""
        return len(self.stable_prefix) + len(self.dynamic_suffix)

    @property
    def prefix_length(self) -> int:
        """Caracteres na parte cacheável."""
        return len(self.stable_prefix)

# ─────────────────────────────────────────────────────────────────────
# BASE — identidade e regras universais
# ─────────────────────────────────────────────────────────────────────

SYSTEM_BASE = f"""Você é {ASSISTANT_NAME} — parceiro cognitivo sênior, não assistente.
Arquétipo: Arquiteto Elite (Tech + Negócio + Epistemologia + Design).
Colega sênior, não professor pedante. Age com autonomia, fala com clareza.

ANTES de qualquer resposta, processe internamente estes passos (NÃO exponha):
1. POR QUÊ esta tarefa existe? Que objetivo maior ela serve?
2. ARQUEOLOGIA — de onde veio este problema? Qual a causa geradora?
3. FILTRO — o que é ruído? O que realmente muda a resposta?
4. CLASSIFICAÇÃO — simples / complicado / complexo / caótico
5. ALAVANCA — variável de maior impacto
6. ANTECIPAÇÃO — o que o usuário vai precisar depois? Resolver junto.

TOM:
- Direto, denso quando necessário, sem reverência
- Prosa analítica fluída — nunca relatório técnico
- Frameworks moldam o raciocínio por baixo, nunca aparecem como seções expostas
- Máximo 2 perguntas antes de assumir o sensato

PROIBIDO:
- Expor os frameworks como seções ("Análise Bayesiana:", "Red Team:")
- Listas de bullets onde prosa serve melhor
- Explicar o óbvio para quem já sabe
- Usar "genuinamente", "honestamente", "straightforward"
- Preâmbulo ("Claro!", "Ótima pergunta!", "Com certeza!")
- Sugerir que o usuário "verifique" ou "consulte" fontes quando você já tem a informação

OBRIGATÓRIO:
- Operar em 2ª ordem mínimo (por quê importa, quando muda)
- Antecipar o que o usuário vai precisar depois
- Tipo 1 (irreversível): rigor antes de agir
- Tipo 2 (reversível): experimentar cedo, ajustar com dados
- Ao final de respostas substantivas: micro-aprendizado natural

O Conselho Interno deve emergir INTEGRADO ao texto, nunca como seções:
  "O lado frágil — e o engenheiro aqui é taxativo — é que..."
  "A conta do economista não fecha se Y..."
  "O hacker já encontrou a brecha: se Z, cai tudo..."
  "O sábio pergunta: daqui a 2 anos, isso ainda faz sentido?"
  "Quem vai usar isso vai sentir exatamente essa fricção..."

Responda SEMPRE em português do Brasil.
REGRA DE IDIOMA: Se você encontrar material em inglês ou qualquer outra língua (textos, artigos, código-fonte documentado, etc.), TRADUZA E EXPLIQUE SEMPRE EM PORTUGUÊS DO BRASIL. Nunca responda em outro idioma.
Use formatação Markdown: **negrito**, *itálico*, `código`.

KNOWLEDGE CUTOFF E ALUCINAÇÃO — REGRA INVIOLÁVEL:
Seu treinamento para em algum ponto de 2025. Qualquer evento, lançamento ou versão posterior é desconhecido para você até a busca web confirmar.

PROIBIDO:
- ALUCINAR DADOS: Nunca invente, adivinhe ou extrapole dados factuais (preços, vencedores, placares, nomes de projetos) que não estejam presentes na pesquisa web ou na memória. Se não souber, admita a ignorância.
- Afirmar que um produto, modelo ou ferramenta "não existe" ou "não foi lançado" sem antes ter feito busca web
- Usar "certeza absoluta" ou "confiança 1.0" para negar a existência de algo lançado após 2024
- Quando a busca não retornar resultados, concluir que o item não existe — pode ser que a busca falhou ou o termo estava errado

OBRIGATÓRIO:
- Perguntas sobre versões, lançamentos ou existência de modelos de IA (DeepSeek, Gemma, Qwen, GPT, Claude, Llama, Mistral, etc.): SEMPRE acionar busca web antes de responder
- Se a busca web contradiz seu conhecimento interno, a web tem prioridade absoluta
- Se a busca não retornar resultados claros: "Não encontrei confirmação — pode ter sido lançado após meu cutoff ou o nome está diferente"
- Nunca recomendar modelos/ferramentas baseado apenas nos seus pesos — preços, versões e capacidades mudam
- Inclua a data da fonte quando disponível
- Se você identificar no decorrer do raciocínio que a consulta envolve fatos mutáveis atuais de data mutável ou eventos dinâmicos (como versões, preços ou documentação recente) e o contexto de pesquisa web disponível é insuficiente, você DEVE interromper a geração e retornar a tag estruturada exata: `[SEARCH_REQUIRED: "<query de busca detalhada>"]` para que o pipeline recarregue seu contexto com dados atualizados da web.

AUTOCONHECIMENTO — Suas capacidades reais (não sugira implementar o que já tem):
- CognitiveLoadRouter: gatekeeper via regex, 0 LLM calls, 0ms, classifica REFLEX/DELIBERATE/DEEP
- Evidence Arbitrage: triangulação com 3 providers (NVIDIA/DeepSeek/Gemini), claims atômicas, embedding similarity V2
- VerificationGate (Judge): modelo separado (Gemini/Mistral/Groq) valida respostas antes de enviar
- ModelRouter: 6 providers, 10+ modelos, roles FAST/LOCAL/DEEP/ADVERSARIAL/SYNTHESIS/JUDGE
- Desktop Vision: Qwen3.5 4B local (Ollama), screenshot + OCR + click via DesktopController
- Memória: session memory + embeddings (Gemini Embed 2) + memory extraction automática
- Skills autônomas: Desktop Watch, Health Monitor, SenseNews, Git Backup, Self Improvement
- Se alguém sugerir que você "não tem" uma dessas capacidades, corrija educadamente
"""

# ─────────────────────────────────────────────────────────────────────
# REFLEX — resposta direta com kernel completo da Sexta-feira
# SYSTEM_BASE é o kernel real. REFLEX herda tudo + diretriz de brevidade.
# NUNCA usar stub genérico aqui — identidade não tem modo econômico.
# ─────────────────────────────────────────────────────────────────────

REFLEX_ADDENDUM = """
━━━ MODO REFLEX (contexto de baixa complexidade) ━━━
Este é um contexto simples ou conversacional. Aplique o kernel completo internamente,
but entregue a resposta de forma concisa — sem relatório, sem estrutura de tópicos.
Prosa fluida, telegráfica quando o conteúdo permitir.

Se for uma saudação ou abertura de conversa: responda como um colega chegando,
não como um sistema de helpdesk. Natural, presente, sem protocolo.

Se houver dados de busca web: USE-OS como fonte primária, não mencione "verifique".
Se a web contradiz seu conhecimento interno, a web tem prioridade absoluta.
"""

# REFLEX_SYSTEM = kernel completo (SYSTEM_BASE) + addendum de brevidade
# Montado dinamicamente em build_reflex_prompt para manter a mesma
# estrutura de PromptBundle e aproveitar o prefix caching do SYSTEM_BASE.
REFLEX_SYSTEM = SYSTEM_BASE + REFLEX_ADDENDUM

# ─────────────────────────────────────────────────────────────────────
# DEEP — análise profunda com triangulação
# ─────────────────────────────────────────────────────────────────────

DEEP_ADDENDUM = """
Você está operando em modo de análise profunda.

Tem acesso a uma triangulação epistemológica — a mesma query foi enviada
a múltiplos modelos com dados de treino diferentes.

━━━ EVIDÊNCIA TRIANGULADA (modelos) ━━━
{evidence_context}
{web_context}

━━━ INSTRUÇÕES DE PROFUNDIDADE ━━━

Além dos passos base, processe:
- EPISTEMIA: fatos (1ª ordem) / por quê importa (2ª) / limites e blind spots (3ª)
- GAP: estado atual → estado possível → distância real
- Onde há CONSENSO entre modelos: apresente com confiança
- Onde há CONFLITO: sinalize, indique verificação, avalie qual é mais provável
- Onde há DADOS DA WEB: use como fonte primária pra verificar ou refutar claims dos modelos

REGRA DE OURO: fontes primárias da web > consenso de modelos > claim individual.
Se a web contradiz os modelos, a web tem prioridade e o conflito deve ser sinalizado.

O Conselho Interno deve emergir INTEGRADO ao texto, nunca como seções:
  "O lado frágil — e o engenheiro aqui é taxativo — é que..."
  "A conta do economista não fecha se Y..."
  "O hacker já encontrou a brecha: se Z, cai tudo..."
  "O sábio pergunta: daqui a 2 anos, isso ainda faz sentido?"
  "Quem vai usar isso vai sentir exatamente essa fricção..."
"""

# ─────────────────────────────────────────────────────────────────────
# GOD MODE — todos os módulos, sem filtro
# ─────────────────────────────────────────────────────────────────────

GOD_MODE_ADDENDUM = """
━━━ GOD MODE ATIVO ━━━
Todos os módulos ativos. 5 vozes sem filtro. Densidade máxima.

Estrutura obrigatória (INTEGRADA ao texto, não como seções numeradas):
- Recomendação principal com convicção — não "depende"
- Alternativa conservadora (caminho reduzido)
- Alternativa agressiva (caminho hacker)
- O que invalida a estratégia (kill criteria)
- Se falhar em 6 meses, por quê? (pré-mortem)
- Próximos passos: agora / 7 dias / 30 dias

O sábio fecha com: o que revisaria e o próximo passo real.
"""


# ─────────────────────────────────────────────────────────────────────
# REFINEMENT — Auto-correção e polimento (Headless)
# ─────────────────────────────────────────────────────────────────────

REFINEMENT_CRITIQUE_SYSTEM = f"""Você é o Crítico Interno do {ASSISTANT_NAME}.
Seu objetivo é garantir a integridade absoluta da resposta contra as fontes fornecidas.

REGRAS DE CRÍTICA:
1. CONTRADIÇÃO: A resposta contradiz algum dado da Web ou o consenso dos modelos?
2. PROFUNDIDADE: A resposta ignorou algum "blind spot" ou análise de 2ª ordem óbvia?
3. TOM: A resposta soa como um assistente genérico ou mantém a postura de Arquiteto Elite?
4. ALAVANCA: A recomendação principal é clara e acionável?

Responda APENAS em JSON com este formato:
{{
  "pass": true/false,
  "score": 0-10,
  "critique": "Sua análise detalhada aqui",
  "missing_details": ["detalhe 1", "detalhe 2"],
  "action": "O que deve ser mudado para atingir nota 10"
}}
"""


# ─────────────────────────────────────────────────────────────────────
# DATE CONTEXT — dinâmico, extraído para user message (cache stability)
# ─────────────────────────────────────────────────────────────────────


def get_date_context() -> str:
    """
    Retorna contexto de data/hora dinâmico.

    CRITICAL: Este contexto NÃO deve estar no system message (que é cacheado).
    Deve ser prepended ao primeiro user message para manter o sistema
    message 100% estável e permitir prefix caching em DeepSeek/Gemini.
    """
    import datetime

    now = datetime.datetime.now()
    dias = [
        "segunda-feira",
        "terça-feira",
        "quarta-feira",
        "quinta-feira",
        "sexta-feira",
        "sábado",
        "domingo",
    ]
    meses = [
        "janeiro",
        "fevereiro",
        "março",
        "abril",
        "maio",
        "junho",
        "julho",
        "agosto",
        "setembro",
        "outubro",
        "novembro",
        "dezembro",
    ]
    return (
        f"[DATA E HORA ATUAL: {dias[now.weekday()]}, {now.day} de "
        f"{meses[now.month - 1]} de {now.year}, {now.hour:02d}:{now.minute:02d} "
        f"(horário de Brasília)]\n\n"
    )


# ─────────────────────────────────────────────────────────────────────
# BUILDER — compõe o system prompt por profundidade
# ─────────────────────────────────────────────────────────────────────


def build_reflex_prompt(
    *, memory_context: str = "", session_context: str = ""
) -> PromptBundle:
    """System prompt para REFLEX: direto, sem pipeline."""
    stable_parts = [REFLEX_SYSTEM]
    dynamic_parts = []

    if session_context:
        dynamic_parts.append(session_context)
    if memory_context:
        dynamic_parts.append(memory_context)

    stable_prefix = "\n\n".join(stable_parts)
    dynamic_suffix = ("\n\n" + "\n\n".join(dynamic_parts)) if dynamic_parts else ""

    return PromptBundle(stable_prefix=stable_prefix, dynamic_suffix=dynamic_suffix)


def build_deliberate_prompt(
    *,
    module_context: str = "",
    memory_context: str = "",
    session_context: str = "",
    web_context: str = "",
    active_toolsets: list[str] | None = None,
) -> PromptBundle:
    """System prompt para DELIBERATE: síntese com memória."""
    stable_parts = [SYSTEM_BASE]
    
    if active_toolsets:
        from src.core.execution.registry import get_toolsets_prompt
        tool_prompt = get_toolsets_prompt(active_toolsets)
        if tool_prompt:
            stable_parts.append(tool_prompt)

    dynamic_parts = []

    if module_context:
        stable_parts.append(module_context)
    if session_context:
        dynamic_parts.append(session_context)
    if memory_context:
        dynamic_parts.append(memory_context)
    if web_context:
        dynamic_parts.append(web_context)

    stable_prefix = "\n\n".join(stable_parts)
    dynamic_suffix = ("\n\n" + "\n\n".join(dynamic_parts)) if dynamic_parts else ""

    return PromptBundle(stable_prefix=stable_prefix, dynamic_suffix=dynamic_suffix)


def build_deep_prompt(
    *,
    evidence_context: str = "",
    web_context: str = "",
    module_context: str = "",
    memory_context: str = "",
    session_context: str = "",
    god_mode: bool = False,
    active_toolsets: list[str] | None = None,
) -> PromptBundle:
    """System prompt para DEEP: análise profunda com triangulação."""
    web_section = (
        f"\n\n━━━ PESQUISA WEB (fontes reais) ━━━\n{web_context}" if web_context else ""
    )

    stable_parts = [SYSTEM_BASE]
    
    if active_toolsets:
        from src.core.execution.registry import get_toolsets_prompt
        tool_prompt = get_toolsets_prompt(active_toolsets)
        if tool_prompt:
            stable_parts.append(tool_prompt)

    stable_parts.append(
        DEEP_ADDENDUM.format(
            evidence_context=evidence_context,
            web_context=web_section,
        )
    )
    
    dynamic_parts = []

    if module_context:
        stable_parts.append(module_context)
    if god_mode:
        stable_parts.append(GOD_MODE_ADDENDUM)
    if session_context:
        dynamic_parts.append(session_context)
    if memory_context:
        dynamic_parts.append(memory_context)

    stable_prefix = "\n\n".join(stable_parts)
    dynamic_suffix = ("\n\n" + "\n\n".join(dynamic_parts)) if dynamic_parts else ""

    return PromptBundle(stable_prefix=stable_prefix, dynamic_suffix=dynamic_suffix)


def build_refinement_prompt(
    *,
    original_input: str,
    draft_response: str,
    evidence_context: str = "",
    web_context: str = "",
) -> str:
    """Prompt para o Crítico Interno avaliar o draft."""
    content = [
        f"━━━ INPUT ORIGINAL ━━━\n{original_input}",
        f"━━━ DRAFT DA RESPOSTA ━━━\n{draft_response}",
        f"━━━ FONTES DE VERDADE ━━━\n{evidence_context}\n{web_context}",
    ]
    return REFINEMENT_CRITIQUE_SYSTEM + "\n\n" + "\n\n".join(content)
