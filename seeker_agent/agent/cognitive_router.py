"""
Seeker Agent — Cognitive Router & Intelligence Layers
seeker_agent/agent/cognitive_router.py

Contém:
1. CognitiveDepth & ExecutionMode (Enums)
2. SeekerState & StateEncoder (Codificação de 26 features para RL)
3. CognitiveLoadRouter (Regex & Heurísticas de Complexidade)
4. CascadeBandit (LinUCB Disjoint Cascade Bandit para RL)
5. EvidenceArbitrage (Triangulação de claims multimodelo em paralelo)
6. ProviderCircuitBreaker (Disjuntores de API para fallbacks resilientes)
"""

import os
import re
import time
import math
import json
import uuid
import logging
import asyncio
import numpy as np
from enum import Enum
from typing import List, Dict, Any, Optional, Tuple, Callable
from dataclasses import dataclass, field, asdict

logger = logging.getLogger("seeker_agent.cognitive_router")

# ─────────────────────────────────────────────────────────────────────────────
# 1. ENUMS E CONFIGURAÇÕES
# ─────────────────────────────────────────────────────────────────────────────

class CognitiveDepth(str, Enum):
    REFLEX = "reflex"
    DELIBERATE = "deliberate"
    DEEP = "deep"

class ExecutionMode(str, Enum):
    INTERACTIVE = "interactive"
    HEADLESS = "headless"

@dataclass(frozen=True)
class RoutingDecision:
    depth: CognitiveDepth
    reason: str
    execution_mode: ExecutionMode = ExecutionMode.INTERACTIVE
    god_mode: bool = False
    forced_module: Optional[str] = None
    needs_web: bool = False
    needs_vault: bool = False
    active_toolsets: Optional[List[str]] = None

# Padrões Regex portados do Seeker.Bot
GOD_MODE_PATTERNS = re.compile(
    r"god\s*mode|potência\s*máxima|modo\s*deus|godmode|"
    r"aprofunda|investiga|análise\s*completa|"
    r"ative?\s*o\s*godmode|ative?\s*godmode",
    re.IGNORECASE,
)

REFLEX_PATTERNS = re.compile(
    r"^(ok|sim|não|beleza|valeu|obrigado|thanks|yes|no|"
    r"blz|vlw|top|show|tmj|bom dia|boa tarde|boa noite|"
    r"oi|olá|hello|hi|hey|e aí|fala|salve|"
    r"entendi|perfeito|combinado|fechado|pode ser|bora|"
    r"que dia é hoje|que horas são|qual a data|qual é a data|hoje é que dia|"
    r"status|continua|avança|próximo|next|go)[\s!?.]*$",
    re.IGNORECASE,
)

SYSTEM_ANSWERABLE = re.compile(
    r"que\s+(dia|horas?|data)\s+(é|são)\s*(hoje|agora)?|"
    r"qual\s+(a\s+)?(data|hora)\s*(de\s+hoje|atual|agora)?|"
    r"hoje\s+é\s+que\s+dia|"
    r"que\s+dia\s+da\s+semana",
    re.IGNORECASE,
)

DEEP_TRIGGERS = re.compile(
    r"vale\s*a\s*pena|trade.?off|compara|versus|vs\.?|"
    r"migrar|arquitetura|escalar|decisão|estratégia|"
    r"pré.?mortem|post.?mortem|red\s*team|"
    r"irreversível|consequência|longo\s*prazo|"
    r"como\s*funciona\s*realmente|descobre?\s*a\s*verdade|"
    r"analisa\s*com\s*tudo|qual\s*o\s*risco|"
    r"evidência|confiança|triangul|arbitrage|"
    r"complexo|sistêm|emergent|"
    r"investimento|roi\s|custo.?benefício",
    re.IGNORECASE,
)

WEB_TRIGGERS = re.compile(
    r"atual|atualmente|hoje|agora\b|recente|último|última|"
    r"2024|2025|2026|2027|"
    r"quem\s+é\s+o|quem\s+é\s+a|quem\s+ganhou|quem\s+venceu|"
    r"qual\s+o\s+preço|qual\s+o\s+valor|quanto\s+custa|"
    r"paper|artigo|publicou|publicação|published|"
    r"lançou|lançamento|lanc(ou|amento|ado)|release|versão\s+\d|v\d+\b|"
    r"foi\s+lançad|foi\s+lancad|"
    r"estado\s+atual|status\s+de|novidades|"
    r"existe\b|ainda\s+existe|já\s+saiu|"
    r"verifi[cq]|de\s+novo|novamente|outra\s+vez|confirma|confere|checa|checagem|valida|"
    r"tem\s+certeza|realmente\s+(existe|foi|tem)|verdade\s+que|fato\s+novo|rumor|boato|dizem\s+que|"
    r"morreu|faleceu|eleito|nomeado|demitido|"
    r"placar|resultado\s+do\s+jogo|score|"
    r"clima|tempo\s*lá\s*fora|cotação|preço|valor\s*da\s*ação|"
    r"notícia|aconteceu|google\s|pesquisa|busca\s|"
    r"deepseek|gemma\s*\d|qwen\s*\d|llama\s*\d|gpt-\d|claude\s*\d|"
    r"mistral|gemini\s*\d|grok\s*\d|phi-\d|command\s*r|"
    r"modelo.*lançad|lançad.*modelo|novo\s+modelo|"
    r"benchmark|mmlu|humaneval|swe-bench|lmarena",
    re.IGNORECASE,
)

VAULT_TRIGGERS = re.compile(
    r"no cofre|no obsidian|nas notas|minhas anotações|meu segundo cérebro|"
    r"o que eu anotei|pesquisa nas notas|busca no obsidian",
    re.IGNORECASE,
)

# ─────────────────────────────────────────────────────────────────────────────
# 2. ESTADO E CODIFICAÇÃO DE FEATURES (STATE ENCODER)
# ─────────────────────────────────────────────────────────────────────────────

STATE_DIM = 26

_RE_CODE = re.compile(r"```|^\s*(def |class |import |from )", re.MULTILINE)
_RE_URL = re.compile(r"https?://|www\.")
_RE_CMD = re.compile(r"^/\w+")
_RE_POSIT = re.compile(
    r"perfeito|ótimo|excelente|show|top|bora|blz|valeu|obrigado",
    re.IGNORECASE,
)

@dataclass
class SeekerState:
    query: str = ""
    timestamp: float = field(default_factory=time.time)
    budget_daily_used_usd: float = 0.0
    budget_daily_limit_usd: float = 10.0
    budget_monthly_used_usd: float = 0.0
    budget_monthly_limit_usd: float = 200.0
    recent_costs_usd: List[float] = field(default_factory=list)
    provider_tier1_healthy: bool = True
    provider_tier2_healthy: bool = True
    recent_failures: int = 0
    avg_latency_ms: float = 500.0
    session_turns: int = 0
    recent_depths: List[str] = field(default_factory=list)
    last_reward: float = 0.0
    last_call_timestamp: Optional[float] = None

class StateEncoder:
    def encode(self, state: SeekerState) -> List[float]:
        v = [0.0] * STATE_DIM
        
        # Query (0-5)
        if state.query:
            words = len(state.query.split())
            v[0] = min(1.0, words / 100.0)
            v[1] = 1.0 if "?" in state.query else 0.0
            v[2] = 1.0 if _RE_CODE.search(state.query) else 0.0
            v[3] = 1.0 if _RE_URL.search(state.query) else 0.0
            v[4] = 1.0 if _RE_CMD.match(state.query.strip()) else 0.0
            v[5] = 1.0 if _RE_POSIT.search(state.query) else 0.0

        # Tempo (6-9)
        dt = time.localtime(state.timestamp)
        hour = dt.tm_hour
        weekday = dt.tm_wday

        v[6] = (math.sin(2 * math.pi * hour / 24) + 1) / 2
        v[7] = (math.cos(2 * math.pi * hour / 24) + 1) / 2
        v[8] = (math.sin(2 * math.pi * weekday / 7) + 1) / 2
        v[9] = (math.cos(2 * math.pi * weekday / 7) + 1) / 2

        # Budget (10-13)
        if state.budget_daily_limit_usd > 0:
            v[10] = min(1.0, state.budget_daily_used_usd / state.budget_daily_limit_usd)
        if state.budget_monthly_limit_usd > 0:
            v[11] = min(1.0, state.budget_monthly_used_usd / state.budget_monthly_limit_usd)
        if state.recent_costs_usd:
            avg_cost = sum(state.recent_costs_usd) / len(state.recent_costs_usd)
            v[12] = min(1.0, avg_cost / 0.05)
        v[13] = 1.0 if v[10] >= 0.8 else 0.0

        # Providers (14-17)
        v[14] = 1.0 if state.provider_tier1_healthy else 0.0
        v[15] = 1.0 if state.provider_tier2_healthy else 0.0
        v[16] = min(1.0, state.recent_failures / 10.0)
        v[17] = min(1.0, state.avg_latency_ms / 2000.0)

        # Sessão (18-21)
        v[18] = min(1.0, state.session_turns / 20.0)
        if state.recent_depths:
            deep_count = sum(1 for d in state.recent_depths if d == "deep")
            v[19] = deep_count / len(state.recent_depths)
        v[20] = (state.last_reward + 1.0) / 2.0
        if state.last_call_timestamp is not None:
            elapsed = time.time() - state.last_call_timestamp
            v[21] = min(1.0, elapsed / 3600.0)
        else:
            v[21] = 1.0

        # Intenção padrão (22-25)
        v[22] = 0.5
        v[23] = 0.0
        v[24] = 0.0
        v[25] = 0.0

        return [max(0.0, min(1.0, x)) for x in v]

# ─────────────────────────────────────────────────────────────────────────────
# 3. ROTEADOR COGNITIVO
# ─────────────────────────────────────────────────────────────────────────────

class CognitiveLoadRouter:
    def __init__(self, agent: Any):
        self.agent = agent

    def _create_decision(
        self,
        depth: CognitiveDepth,
        reason: str,
        mode: ExecutionMode,
        god_mode: bool = False,
        forced_module: Optional[str] = None,
        needs_web: bool = False,
        needs_vault: bool = False,
    ) -> RoutingDecision:
        active = []
        if god_mode:
            active = ["web", "files", "terminal"]
        else:
            if needs_web:
                active.append("web")
            if depth in (CognitiveDepth.DELIBERATE, CognitiveDepth.DEEP):
                active.append("files")
                
        return RoutingDecision(
            depth=depth,
            reason=reason,
            execution_mode=mode,
            god_mode=god_mode,
            forced_module=forced_module,
            needs_web=needs_web,
            needs_vault=needs_vault,
            active_toolsets=active,
        )

    def route(self, text: str, mode: ExecutionMode = ExecutionMode.INTERACTIVE) -> RoutingDecision:
        text_stripped = text.strip()
        needs_web = bool(WEB_TRIGGERS.search(text_stripped))
        needs_vault = bool(VAULT_TRIGGERS.search(text_stripped))

        if SYSTEM_ANSWERABLE.search(text_stripped):
            return self._create_decision(
                depth=CognitiveDepth.REFLEX,
                reason="pergunta de sistema (data/hora)",
                mode=mode,
                needs_web=False,
                needs_vault=needs_vault,
                forced_module="system_time",
            )

        if GOD_MODE_PATTERNS.search(text_stripped):
            trigger = GOD_MODE_PATTERNS.search(text_stripped).group()
            return self._create_decision(
                depth=CognitiveDepth.DEEP,
                reason=f"god mode trigger: '{trigger}'",
                mode=mode,
                god_mode=True,
                needs_web=True,
                needs_vault=True,
            )

        if REFLEX_PATTERNS.match(text_stripped):
            return self._create_decision(
                depth=CognitiveDepth.REFLEX,
                reason="padrão reflex reconhecido",
                mode=mode,
                needs_web=needs_web,
                needs_vault=needs_vault,
            )

        words = len(text_stripped.split())
        has_question = "?" in text_stripped
        if words <= 3 and not DEEP_TRIGGERS.search(text_stripped) and not has_question:
            return self._create_decision(
                depth=CognitiveDepth.REFLEX,
                reason=f"input curto ({words} palavras), sem deep triggers",
                mode=mode,
                needs_web=needs_web,
                needs_vault=needs_vault,
            )

        deep_match = DEEP_TRIGGERS.search(text_stripped)
        if deep_match:
            return self._create_decision(
                depth=CognitiveDepth.DEEP,
                reason=f"deep trigger: '{deep_match.group()}'",
                mode=mode,
                needs_web=True,
                needs_vault=needs_vault,
            )

        # Heurísticas de complexidade
        questions = text_stripped.count("?")
        has_code = bool(_RE_CODE.search(text_stripped))
        sentences = len(re.split(r"[.!?]+", text_stripped)) - 1 or 1

        complexity_score = 0
        if words > 40:
            complexity_score += 1
        if questions >= 2:
            complexity_score += 1
        if has_code:
            complexity_score += 1
        if sentences > 5:
            complexity_score += 1

        if complexity_score >= 3:
            return self._create_decision(
                depth=CognitiveDepth.DEEP,
                reason=f"alta complexidade (score={complexity_score})",
                mode=mode,
                needs_web=True,
                needs_vault=needs_vault,
            )
        elif complexity_score >= 1 or words > 10:
            return self._create_decision(
                depth=CognitiveDepth.DELIBERATE,
                reason="complexidade moderada",
                mode=mode,
                needs_web=needs_web,
                needs_vault=needs_vault,
            )

        return self._create_decision(
            depth=CognitiveDepth.DELIBERATE,
            reason="default conservador",
            mode=mode,
            needs_web=needs_web,
        )

    def generate_reflex_response(self, text: str) -> str:
        """Responde queries simples localmente sem bater na API do LLM."""
        text_lower = text.lower().strip()
        
        # Perguntas de tempo/data
        if SYSTEM_ANSWERABLE.search(text_lower):
            local_time = time.strftime("%H:%M:%S")
            local_date = time.strftime("%Y-%m-%d")
            return f"🕒 Hora atual: {local_time} | 📅 Data: {local_date} (Local)"

        # Saudações simples (normaliza acentuação e pontuação)
        greetings = {"oi", "oii", "oiii", "olá", "ola", "hello", "hi", "hey", "e aí", "e ai", "salve", "fala"}
        clean_text = re.sub(r"[^\w\s]", "", text_lower).strip()

        if clean_text in greetings:
            return "Opa. Como prosseguimos? (Reflex)"
        if clean_text in {"bom dia", "boa tarde", "boa noite"}:
            return f"{clean_text.capitalize()}. O que temos na mesa? (Reflex)"
        
        # Status
        if clean_text == "status":
            return "✅ Seeker Agent operacional. Kernel da Sexta-feira ativo (Reflex/Deliberate/Deep)."

        return "Entendido. Como prosseguimos? (Reflex)"

# ─────────────────────────────────────────────────────────────────────────────
# 4. CASCADE BANDIT (LINUCB RL)
# ─────────────────────────────────────────────────────────────────────────────

ARMS = ["reflex", "deliberate", "deep"]

class CascadeBandit:
    def __init__(self, model_path: str, alpha: float = 1.0):
        self.model_path = model_path
        self._alpha = alpha
        
        # Inicializar A como matriz identidade e b como vetor nulo
        self._A = {arm: np.identity(STATE_DIM) for arm in ARMS}
        self._b = {arm: np.zeros(STATE_DIM) for arm in ARMS}
        self._n_updates = {arm: 0 for arm in ARMS}
        self._pending = {}
        self.load()

    def predict(self, features: List[float], router_arm: str, decision_id: str) -> str:
        x = np.array(features, dtype=float)
        ucb_scores = {}
        
        for arm in ARMS:
            try:
                A_inv = np.linalg.inv(self._A[arm])
                theta = A_inv @ self._b[arm]
                ucb = float(theta @ x + self._alpha * np.sqrt(x @ A_inv @ x))
                ucb_scores[arm] = ucb
            except Exception:
                ucb_scores[arm] = 0.0

        recommended = max(ucb_scores, key=ucb_scores.__getitem__)
        self._pending[decision_id] = {
            "features": features,
            "recommended": recommended,
            "router": router_arm
        }
        return recommended

    def update(self, decision_id: str, reward: float) -> bool:
        pending = self._pending.pop(decision_id, None)
        if not pending:
            return False

        x = np.array(pending["features"], dtype=float)
        arm = pending["router"]  # Atualiza o braço que foi realmente executado
        
        # Normaliza reward de [-1, 1] para [0, 1]
        r = (reward + 1.0) / 2.0
        
        self._A[arm] += np.outer(x, x)
        self._b[arm] += r * x
        self._n_updates[arm] += 1

        if sum(self._n_updates.values()) % 10 == 0:
            self.save()
        return True

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
            arrays = {}
            for arm in ARMS:
                arrays[f"A_{arm}"] = self._A[arm]
                arrays[f"b_{arm}"] = self._b[arm]
                arrays[f"n_{arm}"] = np.array([self._n_updates[arm]])
            np.savez(self.model_path, **arrays)
            logger.info(f"Bandit model saved successfully to {self.model_path}")
        except Exception as e:
            logger.error(f"Failed to save Bandit model: {e}")

    def load(self) -> bool:
        if not os.path.exists(self.model_path):
            return False
        try:
            data = np.load(self.model_path)
            for arm in ARMS:
                if f"A_{arm}" in data:
                    self._A[arm] = data[f"A_{arm}"]
                    self._b[arm] = data[f"b_{arm}"]
                    self._n_updates[arm] = int(data[f"n_{arm}"][0])
            logger.info(f"Bandit model loaded from {self.model_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to load Bandit model: {e}")
            return False

# ─────────────────────────────────────────────────────────────────────────────
# 5. EVIDENCE ARBITRAGE (TRIANGULAÇÃO)
# ─────────────────────────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """Analise esta pergunta e responda com fatos verificáveis.

PERGUNTA: {query}

Responda APENAS em JSON válido, sem markdown. Formato:
{{
  "claims": [
    {{
      "text": "afirmação factual específica e verificável",
      "confidence": 0.85
    }}
  ]
}}
"""

class EvidenceArbitrage:
    def __init__(self, agent: Any):
        self.agent = agent

    async def arbitrate(self, query: str) -> Dict[str, Any]:
        """Dispara chamadas assíncronas paralelas e cruza claims factuais."""
        # Seleciona fallbacks ou modelos alternativos
        providers = []
        if getattr(self.agent, "_fallback_chain", None):
            providers = self.agent._fallback_chain[:2]
        
        # Se não houver fallbacks configurados, emulamos usando o provedor ativo com temp=0.5
        models_to_call = [(self.agent.model, self.agent.provider, self.agent.base_url, self.agent.api_key)]
        for p in providers:
            models_to_call.append((p.get("model"), p.get("provider"), p.get("base_url"), p.get("api_key")))

        # Garante no mínimo 2 chamadas
        if len(models_to_call) < 2:
            models_to_call.append((self.agent.model, self.agent.provider, self.agent.base_url, self.agent.api_key))

        logger.info(f"Running evidence arbitrage with {len(models_to_call)} parallel calls")
        tasks = [self._call_model(m, query) for m in models_to_call]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        all_claims = []
        for r in responses:
            if isinstance(r, Exception) or not r:
                continue
            all_claims.extend(r)

        # Agrupamento simples de consensos vs contradições
        consensus = []
        conflicts = []
        seen_words = []

        for claim in all_claims:
            text = claim.get("text", "")
            confidence = claim.get("confidence", 0.5)
            words = set(w.lower() for w in text.split() if len(w) > 3)
            
            is_match = False
            for seen in seen_words:
                intersection = words & seen
                union = words | seen
                if union and (len(intersection) / len(union)) > 0.4:
                    is_match = True
                    break
            
            if is_match:
                consensus.append(claim)
            else:
                seen_words.append(words)
                conflicts.append(claim)

        # Se houver conflitos factuais relevantes, marcamos para o usuário
        return {
            "consensus": consensus,
            "conflicts": conflicts if len(consensus) > 0 else [],
            "has_conflicts": len(conflicts) > 1 and len(consensus) > 0
        }

    async def _call_model(self, model_info: Tuple[str, str, str, str], query: str) -> List[Dict[str, Any]]:
        model, provider, base_url, api_key = model_info
        
        # Usamos o cliente openai do agent ou criamos um temporário
        import openai
        client = getattr(self.agent, "client", None)
        if not client or provider != self.agent.provider:
            # Cria cliente descartável
            client = openai.AsyncOpenAI(api_key=api_key or "sk-dummy", base_url=base_url or None)
        
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": EXTRACTION_PROMPT.format(query=query)}],
                temperature=0.0,
                max_tokens=500
            )
            text = resp.choices[0].message.content
            # Limpa qualquer markdown
            text_cleaned = re.sub(r"```json|```", "", text).strip()
            data = json.loads(text_cleaned)
            return data.get("claims", [])
        except Exception as e:
            logger.warning(f"Arbitrage parallel call failed for {model}: {e}")
            return []

# ─────────────────────────────────────────────────────────────────────────────
# 6. PROVIDER CIRCUIT BREAKER
# ─────────────────────────────────────────────────────────────────────────────

class CircuitBreakerState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half-open"

class ProviderCircuitBreaker:
    def __init__(self, name: str, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = CircuitBreakerState.CLOSED
        self.failures = 0
        self.successes = 0
        self.opened_time = 0.0

    def record_success(self):
        self.failures = 0
        if self.state == CircuitBreakerState.HALF_OPEN:
            self.successes += 1
            if self.successes >= 3:
                self.state = CircuitBreakerState.CLOSED
                self.successes = 0
                logger.info(f"Circuit Breaker for {self.name} has recovered. State -> CLOSED.")

    def record_failure(self):
        self.failures += 1
        logger.warning(f"Circuit Breaker {self.name} failure recorded: {self.failures}/{self.failure_threshold}")
        if self.failures >= self.failure_threshold:
            self.state = CircuitBreakerState.OPEN
            self.opened_time = time.monotonic()
            logger.error(f"Circuit Breaker for {self.name} is OPEN. Blocking requests.")

    def allow_request(self) -> bool:
        if self.state == CircuitBreakerState.CLOSED:
            return True
        if self.state == CircuitBreakerState.OPEN:
            elapsed = time.monotonic() - self.opened_time
            if elapsed >= self.recovery_timeout:
                self.state = CircuitBreakerState.HALF_OPEN
                self.successes = 0
                logger.info(f"Circuit Breaker {self.name} entered HALF_OPEN. Testing recovery.")
                return True
            return False
        return True

def run_async_synchronously(coro):
    """Executa uma corrotina assíncrona em uma thread separada com loop dedicado."""
    import threading
    result = None
    exception = None
    
    def target():
        nonlocal result, exception
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(coro)
            loop.close()
        except Exception as e:
            exception = e

    t = threading.Thread(target=target)
    t.start()
    t.join()
    
    if exception:
        raise exception
    return result

