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
  Gemini 3.1 Flash Lite: 15 RPM | 500 RPD            ← volume Gemini
  Gemini 3 Flash       :  5 RPM |  20 RPD            ← qualidade
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

NVIDIA_NEMOTRON_ULTRA = ModelConfig(
    provider="nvidia",
    model_id="nvidia/llama-3.1-nemotron-ultra-253b-v1",
    display_name="Nemotron Ultra 253B",
    max_tokens=4096,
    context_window=128_000,
    supports_tool_use=True,
    training_data_cutoff="2025-06",
    rpm_limit=40,
)

NVIDIA_QWQ_32B = ModelConfig(
    provider="nvidia",
    model_id="qwen/qwq-32b",
    display_name="QwQ 32B via NIM",
    max_tokens=4096,
    context_window=128_000,
    supports_tool_use=False,
    training_data_cutoff="2025-03",
    rpm_limit=40,
)

NVIDIA_DEEPSEEK_R1 = ModelConfig(
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

GEMINI_3_FLASH = ModelConfig(
    provider="gemini",
    model_id="gemini-3-flash",
    display_name="Gemini 3 Flash",
    max_tokens=8192,
    context_window=1_000_000,
    supports_tool_use=True,
    training_data_cutoff="2025-01",
    rpm_limit=5,
    rpd_limit=20,
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
    rpd_limit=20,
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

CEREBRAS_ZAI_GLM_4_7 = ModelConfig(
    provider="cerebras",
    model_id="zai-glm-4.7",
    display_name="Cerebras Zai-GLM 4.7",
    max_tokens=8192,
    context_window=131_072,
    cost_per_1m_input=0.0,
    cost_per_1m_output=0.0,
    supports_tool_use=True,
    training_data_cutoff="2026-04",
    rpm_limit=10,
    rpd_limit=100,
)

# ─────────────────────────────────────────────────────────────────────
# MOONSHOT (KIMI) — PAGO
# ─────────────────────────────────────────────────────────────────────

MOONSHOT_KIMI_V1 = ModelConfig(
    provider="kimi",
    model_id="moonshot-v1-32k",
    display_name="Kimi Moonshot v1",
    max_tokens=4096,
    context_window=32_000,
    cost_per_1m_input=1.65,  # Estimado, ajuste conforme necessário
    cost_per_1m_output=1.65,
    supports_tool_use=True,
    training_data_cutoff="2025-10",
)


# ─────────────────────────────────────────────────────────────────────
# OPENROUTER — FREE TIER (20 RPM, 200 RPD)
# ─────────────────────────────────────────────────────────────────────

OPENROUTER_DEEPSEEK_R1 = ModelConfig(
    provider="openrouter",
    model_id="google/gemma-4-31b-it:free",
    display_name="Gemma 4 31B (OpenRouter)",
    max_tokens=8192,
    context_window=128_000,
    supports_tool_use=True,
    rpm_limit=20,
    rpd_limit=200,
)

OPENROUTER_QWEN3_235B = ModelConfig(
    provider="openrouter",
    model_id="qwen/qwen3-coder:free",
    display_name="Qwen3 Coder (OpenRouter)",
    max_tokens=4096,
    context_window=128_000,
    supports_tool_use=True,
    rpm_limit=20,
    rpd_limit=200,
)


# ─────────────────────────────────────────────────────────────────────
# GROQ + MISTRAL
# ─────────────────────────────────────────────────────────────────────

GROQ_LLAMA = ModelConfig(
    provider="groq",
    model_id="meta-llama/llama-4-scout-17b-16e-instruct",
    display_name="Llama 4 Scout via Groq",
    max_tokens=4096,
    context_window=128_000,
    training_data_cutoff="2025-08",
    rpm_limit=30,
    rpd_limit=14_400,
)

GROQ_LLAMA_70B = ModelConfig(
    provider="groq",
    model_id="llama-3.3-70b-versatile",
    display_name="Llama 3.3 70B via Groq",
    max_tokens=8192,
    context_window=128_000,
    supports_tool_use=True,
    training_data_cutoff="2024-12",
    rpm_limit=30,
    rpd_limit=14_400,
)

GROQ_LLAMA_70B_SPECDEC = ModelConfig(
    provider="groq",
    model_id="llama-3.3-70b-specdec",
    display_name="Llama 3.3 70B SpecDec via Groq",
    max_tokens=8192,
    context_window=128_000,
    supports_tool_use=True,
    training_data_cutoff="2024-12",
    rpm_limit=30,
    rpd_limit=14_400,
)

GROQ_DEEPSEEK_R1_70B = ModelConfig(
    provider="groq",
    model_id="deepseek-r1-distill-llama-70b",
    display_name="DeepSeek R1 70B via Groq",
    max_tokens=8192,
    context_window=128_000,
    supports_tool_use=True,
    training_data_cutoff="2025-01",
    rpm_limit=30,
    rpd_limit=14_400,
)

MISTRAL_FREE = ModelConfig(
    provider="mistral",
    model_id="mistral-small-latest",
    display_name="Mistral Small (free tier)",
    max_tokens=4096,
    context_window=128_000,
    supports_tool_use=True,
    training_data_cutoff="2025-06",
    rpm_limit=2,
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
    Roteamento otimizado pós-teste de carga e latência.
    Prioriza LPUs ultra rápidas (Cerebras, Groq) para FAST e JUDGE.
    Usa Gemini Flash Lite para volumes robustos e contextos longos.
    Reserva modelos de CoT (DeepSeek R1) estritamente para DEEP e ADVERSARIAL.
    """
    return ModelRouter(
        routes={
            CognitiveRole.FAST: [
                CEREBRAS_GPT_OSS_120B,  # Primário: Wafer-scale LPU (~700 tok/s), sem custo
                GROQ_LLAMA_70B,         # Fallback 1: Llama 3.3 70B via Groq LPU
                GEMINI_31_FLASH_LITE,   # Fallback 2: Gemini 3.1 Flash Lite grátis (volume 500 RPD)
                DEEPSEEK_CHAT,          # Fallback 3: Backup pago oficial v4 Flash
            ],
            CognitiveRole.LOCAL: [
                OLLAMA_GEMMA_4,
                OLLAMA_QWEN,
                GEMINI_31_FLASH_LITE,
            ],
            CognitiveRole.DEEP: [
                NVIDIA_DEEPSEEK_R1,     # Primário: Raciocínio profundo (R1) grátis via NIM (40 RPM)
                DEEPSEEK_REASONER,      # Fallback 1: Backup oficial pago v4 Pro
                GEMINI_3_FLASH,         # Fallback 2: Gemini 3 Flash grátis
                OPENROUTER_DEEPSEEK_R1, # Fallback 3: R1 grátis via OpenRouter
            ],
            CognitiveRole.ADVERSARIAL: [
                NVIDIA_GEMMA_4_31B,     # Primário: Gemma 4 via NIM grátis (40 RPM)
                DEEPSEEK_REASONER,      # Fallback 1: DeepSeek Reasoner pago
                GROQ_LLAMA_70B,         # Fallback 2: Groq Llama 3.3 70B
                OPENROUTER_QWEN3_235B,  # Fallback 3: Qwen3 235B grátis via OpenRouter
            ],
            CognitiveRole.SYNTHESIS: [
                GEMINI_31_FLASH_LITE,   # Primário: Grande janela de contexto grátis (1M context)
                GEMINI_35_FLASH,        # Fallback 1: Gemini 3.5 Flash grátis (1500 RPD)
                CEREBRAS_ZAI_GLM_4_7,   # Fallback 2: Cerebras Zai-GLM 4.7
                DEEPSEEK_CHAT,          # Fallback 3: DeepSeek Chat pago
            ],
            CognitiveRole.JUDGE: [
                GROQ_LLAMA_70B,         # Primário: Llama 3.3 70B via Groq LPU
                CEREBRAS_GPT_OSS_120B,  # Fallback 1: 120B grátis via Cerebras LPU
                NVIDIA_GEMMA_4_31B,     # Fallback 2: Gemma 4 via NIM
                MISTRAL_FREE,           # Fallback 3: Mistral Small free
            ],
            CognitiveRole.EMBEDDING: [
                GEMINI_EMBEDDING_2,
            ],
        }
    )
