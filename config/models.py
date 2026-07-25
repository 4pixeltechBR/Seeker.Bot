"""
Seeker.Bot — Configuração de Roteamento de Modelos
config/models.py

6 providers, 6 datasets de treino distintos:
  DeepSeek  — dados chineses/multilíngue (pago, barato)
  Gemini    — dados Google (free tier)
  Groq      — Meta/Llama (free, ultrarrápido)
  Mistral   — dados europeus (free, 2 RPM limitante)
  NVIDIA    — Nemotron proprietário + hub de modelos (free, 40 RPM!)
  [futuro]  — Qwen/Alibaba via NIM

Rate Limits (free tier):
  NVIDIA NIM           : 40 RPM | sem limite diário  ← WORKHORSE
  Groq                 : 30 RPM | 14.4K RPD          ← velocidade
  Gemini 3.1 Flash Lite: 15 RPM | 500 RPD            ← volume Gemini (primário)
  Gemini 3.5 Flash     :  5 RPM |  20 RPD            ← qualidade (fallback)
  Mistral              :  2 RPM | 1B tok/mês          ← parcimônia
  DeepSeek             : sem limite (pago ~$0.28/1M)  ← backup confiável
"""

from dataclasses import dataclass, field
from enum import Enum


class CognitiveRole(str, Enum):
    FAST = "fast"
    LOCAL = "local"
    DEEP = "deep"
    ADVERSARIAL = "adversarial"
    SYNTHESIS = "synthesis"
    JUDGE = "judge"
    EMBEDDING = "embedding"


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    model_id: str
    display_name: str
    max_tokens: int = 4096
    temperature: float = 0.0
    context_window: int = 128_000
    cost_per_1m_input: float = 0.0
    cost_per_1m_output: float = 0.0
    supports_streaming: bool = True
    supports_tool_use: bool = False
    training_data_cutoff: str = ""
    rpm_limit: int = 0
    rpd_limit: int = 0


@dataclass
class ModelRouter:
    routes: dict[CognitiveRole, list[ModelConfig]] = field(default_factory=dict)

    def get(self, role: CognitiveRole) -> ModelConfig:
        configs = self.routes.get(role, [])
        if not configs:
            raise ValueError(f"Nenhum modelo configurado para o papel: {role}")
        return configs[0]

    def get_fallbacks(self, role: CognitiveRole) -> list[ModelConfig]:
        configs = self.routes.get(role, [])
        return configs[1:] if len(configs) > 1 else []

    def move_to_primary(self, role: CognitiveRole, provider: str):
        """Move um provedor para a primeira posição (primário) de um papel."""
        configs = self.routes.get(role, [])
        for i, cfg in enumerate(configs):
            if cfg.provider == provider:
                # Remove de onde está e coloca no topo
                target = configs.pop(i)
                configs.insert(0, target)
                return True
        return False

    def get_all_for_arbitrage(self) -> list[ModelConfig]:
        """
        Modelos de providers DIFERENTES para Evidence Arbitrage.
        Prioridade por diversidade de dados de treino.
        Max 3 para custo.
        """
        priority_order = ["nvidia", "deepseek", "gemini", "groq", "mistral"]
        seen_providers: set[str] = set()
        models: list[ModelConfig] = []
        for target in priority_order:
            for configs in self.routes.values():
                for cfg in configs:
                    if cfg.provider == target and cfg.provider not in seen_providers:
                        seen_providers.add(cfg.provider)
                        models.append(cfg)
                        break
                if target in seen_providers:
                    break
        return models[:3]


# ─────────────────────────────────────────────────────────────────────
# NVIDIA NIM — 40 RPM, sem limite diário, o novo workhorse
# ─────────────────────────────────────────────────────────────────────

NVIDIA_NEMOTRON_SUPER = ModelConfig(
    provider="nvidia",
    model_id="nvidia/nemotron-3-super-120b-a12b",
    display_name="Nemotron-3 Super 120B",
    max_tokens=4096,
    context_window=1_000_000,
    supports_tool_use=True,
    training_data_cutoff="2025-06",
    rpm_limit=40,
)

NVIDIA_NEMOTRON_3_ULTRA = ModelConfig(
    provider="nvidia",
    model_id="nvidia/nemotron-3-ultra-550b-a55b",
    display_name="Nemotron-3 Ultra 550B (MoE 55B ativo)",
    max_tokens=4096,
    context_window=1_000_000,
    supports_tool_use=True,
    training_data_cutoff="2026-04",
    rpm_limit=40,
)

NVIDIA_QWEN_3_5_397B = ModelConfig(
    provider="nvidia",
    model_id="qwen/qwen3.5-397b-a17b",
    display_name="Qwen 3.5 397B (NIM)",
    max_tokens=4096,
    context_window=131_072,
    supports_tool_use=True,
    training_data_cutoff="2026-04",
    rpm_limit=40,
)

NVIDIA_DEEPSEEK_V4_PRO = ModelConfig(
    provider="nvidia",
    model_id="deepseek-ai/deepseek-v4-pro",
    display_name="DeepSeek V4 Pro (NIM)",
    max_tokens=4096,
    context_window=128_000,
    supports_tool_use=True,
    training_data_cutoff="2026-01",
    rpm_limit=40,
)

NVIDIA_GEMMA_4_31B = ModelConfig(
    provider="nvidia",
    model_id="google/gemma-4-31b-it",
    display_name="Gemma 4 31B (NIM)",
    max_tokens=4096,
    context_window=32_000,  # NIM suporta a janela estendida do Gemma
    supports_tool_use=True,
    training_data_cutoff="2026-02",
    rpm_limit=40,
)


# ─────────────────────────────────────────────────────────────────────
# GEMINI — FREE TIER
# ─────────────────────────────────────────────────────────────────────

GEMINI_31_FLASH_LITE = ModelConfig(
    provider="gemini",
    model_id="gemini-3.1-flash-lite",
    display_name="Gemini 3.1 Flash Lite",
    max_tokens=4096,
    context_window=1_000_000,
    supports_tool_use=True,
    training_data_cutoff="2025-01",
    rpm_limit=15,
    rpd_limit=500,
)

GEMINI_25_FLASH = ModelConfig(
    provider="gemini",
    model_id="gemini-2.5-flash",
    display_name="Gemini 2.5 Flash",
    max_tokens=8192,
    context_window=1_000_000,
    supports_tool_use=True,
    training_data_cutoff="2025-03",
    rpm_limit=5,
    rpd_limit=1500,  # corrigido: manual jul/2026 confirma 1.5K RPD + Map 500 RPD + Search 1.5K RPD
)

GEMINI_35_FLASH = ModelConfig(
    provider="gemini",
    model_id="gemini-3.5-flash",
    display_name="Gemini 3.5 Flash",
    max_tokens=8192,
    context_window=1_000_000,
    supports_tool_use=True,
    training_data_cutoff="2026-03",
    rpm_limit=15,
    rpd_limit=1500,
)

GEMINI_EMBEDDING_2 = ModelConfig(
    provider="gemini",
    model_id="gemini-embedding-001",
    display_name="Gemini Embedding 2",
    max_tokens=0,
    context_window=8192,
    rpm_limit=100,
    rpd_limit=1000,
)


# ─────────────────────────────────────────────────────────────────────
# DEEPSEEK — PAGO (backup confiável)
# ─────────────────────────────────────────────────────────────────────

DEEPSEEK_CHAT = ModelConfig(
    provider="deepseek",
    model_id="deepseek-v4-flash",
    display_name="DeepSeek V4 Flash",
    max_tokens=8192,
    context_window=1_000_000,
    cost_per_1m_input=0.07,
    cost_per_1m_output=0.28,
    supports_tool_use=True,
    training_data_cutoff="2026-01",
)

DEEPSEEK_REASONER = ModelConfig(
    provider="deepseek",
    model_id="deepseek-v4-pro",
    display_name="DeepSeek V4 Pro",
    max_tokens=8192,
    context_window=1_000_000,
    cost_per_1m_input=0.87,
    cost_per_1m_output=3.48,
    supports_tool_use=True,
    training_data_cutoff="2026-01",
)

# ─────────────────────────────────────────────────────────────────────
# CEREBRAS — FREE TIER (1M tokens/dia, 30 RPM, ctx 131K)
# Signup: https://cloud.cerebras.ai/
# ─────────────────────────────────────────────────────────────────────

CEREBRAS_GPT_OSS_120B = ModelConfig(
    provider="cerebras",
    model_id="gpt-oss-120b",
    display_name="Cerebras GPT-OSS 120B",
    max_tokens=8192,
    context_window=131_072,
    cost_per_1m_input=0.0,   # free tier
    cost_per_1m_output=0.0,  # free tier
    supports_tool_use=True,
    training_data_cutoff="2025-06",
    rpm_limit=30,  # 30 RPM, 1M tokens/dia
)

# ─────────────────────────────────────────────────────────────────────
# MOONSHOT (KIMI) — PAGO
# ─────────────────────────────────────────────────────────────────────

MOONSHOT_KIMI_K2_6 = ModelConfig(
    provider="kimi",
    model_id="kimi-k2.6",
    display_name="Kimi K2.6 (current flagship, july 2026)",
    max_tokens=4096,
    context_window=262_144,
    cost_per_1m_input=0.95,
    cost_per_1m_output=4.00,
    supports_tool_use=True,
    training_data_cutoff="2026-04",
)


# ─────────────────────────────────────────────────────────────────────
# X.AI (GROK) — Paid tier
# Used by src/skills/x_search/x_search.py (Twitter/X Search) and
# indirectly by custom_extension/miner.py:trend_signal (_x_mentions_count).
# Updated jul 2026: grok-4.3 deprecated 17/07/2026, current = grok-4.5.
# ─────────────────────────────────────────────────────────────────────

XAI_GROK_4_5 = ModelConfig(
    provider="xai",
    model_id="grok-4.5",
    display_name="Grok 4.5 (X.AI, jul 2026)",
    max_tokens=8192,
    context_window=500_000,
    supports_tool_use=True,
    training_data_cutoff="2026-02",
    cost_per_1m_input=2.00,
    cost_per_1m_output=6.00,
)


# ─────────────────────────────────────────────────────────────────────
# OPENROUTER — FREE TIER (20 RPM, 200 RPD por modelo)
# Jul/2026: 23 modelos free. Selecionamos Tier S/A para produção.
# ─────────────────────────────────────────────────────────────────────

OPENROUTER_GEMMA_4_31B = ModelConfig(
    provider="openrouter",
    model_id="google/gemma-4-31b-it:free",
    display_name="Gemma 4 31B (OpenRouter Tier S)",
    max_tokens=8192,
    context_window=262_144,
    supports_tool_use=True,
    rpm_limit=20,
    rpd_limit=200,
)

OPENROUTER_QWEN3_CODER = ModelConfig(
    provider="openrouter",
    model_id="qwen/qwen3-coder:free",
    display_name="Qwen3 Coder (OpenRouter)",
    max_tokens=4096,
    context_window=1_000_000,
    supports_tool_use=True,
    rpm_limit=20,
    rpd_limit=200,
)

OPENROUTER_TENCENT_HY3 = ModelConfig(
    provider="openrouter",
    model_id="tencent/hy3:free",
    display_name="Tencent HY3 295B/21B (OpenRouter Tier A)",
    max_tokens=4096,
    context_window=262_144,
    supports_tool_use=True,
    rpm_limit=20,
    rpd_limit=200,
)

OPENROUTER_GPT_OSS_20B = ModelConfig(
    provider="openrouter",
    model_id="openai/gpt-oss-20b:free",
    display_name="GPT-OSS 20B (OpenRouter Tier S, tools)",
    max_tokens=8192,
    context_window=131_072,
    supports_tool_use=True,
    rpm_limit=20,
    rpd_limit=200,
)


# ─────────────────────────────────────────────────────────────────────
# Z.AI (ZHIPU) — FREE PERMANENTE (não é trial — input, cache e output = $0)
# GLM-4.7-Flash, GLM-4.5-Flash, GLM-4.6V-Flash são realmente grátis.
# ─────────────────────────────────────────────────────────────────────

ZAI_GLM_4_7_FLASH = ModelConfig(
    provider="zai",
    model_id="glm-4.7-flash",
    display_name="Z.ai GLM-4.7 Flash (free permanente)",
    max_tokens=4096,
    context_window=131_072,
    supports_tool_use=True,
    training_data_cutoff="2026-04",
    rpm_limit=10,
)

ZAI_GLM_4_5_FLASH = ModelConfig(
    provider="zai",
    model_id="glm-4.5-flash",
    display_name="Z.ai GLM-4.5 Flash (free permanente)",
    max_tokens=4096,
    context_window=131_072,
    supports_tool_use=True,
    training_data_cutoff="2026-01",
    rpm_limit=10,
)


# ─────────────────────────────────────────────────────────────────────
# COHERE — TRIAL (1.000 chamadas/mês, 20 RPM, não-comercial)
# Embed 4 é o embedding backup caso Gemini Embedding 2 falhe.
# ─────────────────────────────────────────────────────────────────────

COHERE_EMBED_V4 = ModelConfig(
    provider="cohere",
    model_id="embed-v4",
    display_name="Cohere Embed v4 (trial 1K/mês)",
    max_tokens=0,
    context_window=131_072,
    rpm_limit=20,
    rpd_limit=33,  # 1.000/mês ≈ 33/dia
    training_data_cutoff="2025-09",
)


# ─────────────────────────────────────────────────────────────────────
# GROQ + MISTRAL
# ─────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# GROQ + MISTRAL — Jul/2026
# Groq: modelos antigos (Llama-3.3, Llama-4-Scout, qwen3-32b) descontinuados.
# Substitutos: gpt-oss-120b (Reasoning frontier, 1000 t/s) e qwen/qwen3.6-27b
# (multimodal, 500 t/s). Mantemos Mistral Small (free tier).
# ─────────────────────────────────────────────────────────────────────────────

GROQ_GPT_OSS_120B = ModelConfig(
    provider="groq",
    model_id="openai/gpt-oss-120b",
    display_name="GPT-OSS 120B via Groq",
    max_tokens=8192,
    context_window=131_072,
    supports_tool_use=True,
    training_data_cutoff="2025-09",
    rpm_limit=30,
    rpd_limit=14_400,
)

GROQ_QWEN_3_6_27B = ModelConfig(
    provider="groq",
    model_id="qwen/qwen3.6-27b",
    display_name="Qwen 3.6 27B (multimodal) via Groq",
    max_tokens=4096,
    context_window=131_072,
    supports_tool_use=True,
    training_data_cutoff="2026-04",
    rpm_limit=30,
    rpd_limit=14_400,
)

GROQ_GPT_OSS_SAFEGUARD = ModelConfig(
    provider="groq",
    model_id="openai/gpt-oss-safeguard-20b",
    display_name="GPT-OSS Safeguard 20B (safety)",
    max_tokens=8192,
    context_window=131_072,
    supports_tool_use=False,
    training_data_cutoff="2025-09",
    rpm_limit=30,
    rpd_limit=14_400,
)

MISTRAL_FREE = ModelConfig(
    provider="mistral",
    model_id="mistral-small-2506",
    display_name="Mistral Small 2506 (Standard Pool free)",
    max_tokens=4096,
    context_window=128_000,
    supports_tool_use=True,
    training_data_cutoff="2025-06",
    rpm_limit=1,  # manual: ~1 req/s global no free tier
)


# ─────────────────────────────────────────────────────────────────────
# OLLAMA — LOCAL (zero custo, GPU/CPU)
# ─────────────────────────────────────────────────────────────────────

OLLAMA_QWEN = ModelConfig(
    provider="ollama",
    model_id="qwen3.5:4b",
    display_name="Qwen3.5 4B (local)",
    max_tokens=2048,
    context_window=32_000,
    supports_streaming=False,
    supports_tool_use=False,
    training_data_cutoff="2025-09",
    rpm_limit=0,  # Sem limite — é local
)

OLLAMA_GEMMA_4 = ModelConfig(
    provider="ollama",
    model_id="gemma4:9b",  # Ajuste conforme a tag que você importou no Ollama
    display_name="Gemma 4 (local)",
    max_tokens=4096,
    context_window=32_000,
    supports_streaming=False,
    supports_tool_use=True,
    training_data_cutoff="2026-02",
    rpm_limit=0,
)


# ─────────────────────────────────────────────────────────────────────
# ROTEAMENTO PADRÃO
# ─────────────────────────────────────────────────────────────────────


def build_default_router() -> ModelRouter:
    """
    Roteamento Jul/2026 — pós-Ground Truth day (15/07/2026).

    Política: priorizar 100% FREE primeiro, pago (DeepSeek V4 Pro) só em DEEP
    quando o stack free não tem qualidade suficiente. Z.ai GLM-4.7-Flash é
    $0 permanente e entra como fallback intermediário em vários roles.

    Cadeia resumida:
    - FAST: Gemini 3.1 Lite → Z.ai 4.7-Flash → Groq gpt-oss-120b → Cerebras → DeepSeek
    - DEEP: NVIDIA V4 Pro (NIM) → NVIDIA Nemotron-3 Ultra 550B → DeepSeek pago
            → Gemini 2.5 Flash (1.5K RPD) → OpenRouter gpt-oss-120b
    - JUDGE/SYNTHESIS: Gemini 3.1 Lite → Gemini 2.5 Flash → Z.ai 4.7-Flash
            → Groq gpt-oss-120b → Cerebras
    - ADVERSARIAL: NVIDIA Gemma 4 31B → Groq qwen3.6-27b → Gemini 2.5 Flash
            → OpenRouter tencent/hy3 → Z.ai 4.7-Flash
    - LOCAL: Ollama Gemma 4 → Ollama Qwen3.5 → Z.ai 4.5-Flash → Gemini 3.1 Lite
    - EMBEDDING: Gemini Embedding 2 → Cohere Embed v4 (trial backup)

    Referência: docs/freetiers.md + E:\Arquivos desenvolvimento\\freetiers_apis.md
    """
    return ModelRouter(
        routes={
            CognitiveRole.FAST: [
                GEMINI_31_FLASH_LITE,      # Primário: Gemini 3.1 Flash Lite (free, 500 RPD, 15 RPM)
                ZAI_GLM_4_7_FLASH,         # Fallback 1: Z.ai 4.7-Flash (free permanente $0)
                GROQ_GPT_OSS_120B,         # Fallback 2: Groq gpt-oss-120b (free, 30 RPM)
                CEREBRAS_GPT_OSS_120B,     # Fallback 3: Cerebras free (1M tokens/dia)
                DEEPSEEK_CHAT,             # Fallback 4: DeepSeek V4 Flash (pago, $0.14/M)
            ],
            CognitiveRole.LOCAL: [
                OLLAMA_GEMMA_4,            # Primário: Gemma 4 9B local (sem limite)
                OLLAMA_QWEN,               # Fallback 1: Qwen3.5 4B local
                ZAI_GLM_4_5_FLASH,         # Fallback 2: Z.ai 4.5-Flash (free $0)
                GEMINI_31_FLASH_LITE,      # Fallback 3: Gemini cloud
            ],
            CognitiveRole.DEEP: [
                NVIDIA_DEEPSEEK_V4_PRO,    # Primário: V4 Pro via NIM (40 RPM, free)
                NVIDIA_NEMOTRON_3_ULTRA,   # Fallback 1: Nemotron-3 Ultra 550B (NIM, free, 1M ctx)
                DEEPSEEK_REASONER,         # Fallback 2: DeepSeek V4 Pro pago ($0.87/M, ctx longo)
                GEMINI_25_FLASH,           # Fallback 3: Gemini 2.5 Flash (free, 1.5K RPD)
                OPENROUTER_GPT_OSS_20B,    # Fallback 4: GPT-OSS 20B OpenRouter (free)
            ],
            CognitiveRole.ADVERSARIAL: [
                NVIDIA_GEMMA_4_31B,        # Primário: Gemma 4 31B via NIM (40 RPM, free)
                GROQ_QWEN_3_6_27B,         # Fallback 1: Qwen 3.6 27B multimodal Groq (free)
                GEMINI_25_FLASH,           # Fallback 2: Gemini 2.5 Flash (free, 1.5K RPD)
                OPENROUTER_TENCENT_HY3,    # Fallback 3: Tencent HY3 295B/21B (free, Tier A)
                ZAI_GLM_4_7_FLASH,         # Fallback 4: Z.ai free permanente
            ],
            CognitiveRole.SYNTHESIS: [
                GEMINI_31_FLASH_LITE,      # Primário: Gemini 3.1 Flash Lite (free, 500 RPD)
                GEMINI_25_FLASH,           # Fallback 1: Gemini 2.5 Flash (free, 1.5K RPD)
                ZAI_GLM_4_7_FLASH,         # Fallback 2: Z.ai 4.7-Flash (free permanente)
                DEEPSEEK_CHAT,             # Fallback 3: DeepSeek V4 Flash (pago)
            ],
            CognitiveRole.JUDGE: [
                GEMINI_31_FLASH_LITE,      # Primário: Gemini 3.1 Flash Lite (free, 500 RPD)
                GEMINI_25_FLASH,           # Fallback 1: Gemini 2.5 Flash (free, 1.5K RPD)
                ZAI_GLM_4_7_FLASH,         # Fallback 2: Z.ai 4.7-Flash (free permanente)
                GROQ_GPT_OSS_120B,         # Fallback 3: Groq gpt-oss-120b (free, reasoning)
                CEREBRAS_GPT_OSS_120B,     # Fallback 4: Cerebras free
            ],
            CognitiveRole.EMBEDDING: [
                GEMINI_EMBEDDING_2,        # Primário: Gemini Embedding 2 (free, 1K RPD)
                COHERE_EMBED_V4,           # Fallback: Cohere Embed v4 (trial, 1K/mês)
            ],
        }
    )
