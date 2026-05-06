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
    FAST       = "fast"
    LOCAL      = "local"
    DEEP       = "deep"
    ADVERSARIAL = "adversarial"
    SYNTHESIS  = "synthesis"
    JUDGE      = "judge"
    EMBEDDING  = "embedding"


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
    model_id="nvidia/llama-3.3-nemotron-super-49b-v1.5",
    display_name="Nemotron Super 49B v1.5",
    max_tokens=4096,
    context_window=128_000,
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

NVIDIA_DEEPSEEK_V32 = ModelConfig(
    provider="nvidia",
    model_id="deepseek-ai/deepseek-v3.2",
    display_name="DeepSeek V3.2 via NIM",
    max_tokens=4096,
    context_window=128_000,
    supports_tool_use=True,
    training_data_cutoff="2025-07",
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
    model_id="gemini-3.1-flash-lite-preview",
    display_name="Gemini 3.1 Flash Lite",
    max_tokens=4096,
    context_window=128_000,
    supports_tool_use=True,
    training_data_cutoff="2025-01",
    rpm_limit=15, rpd_limit=500,
)

GEMINI_3_FLASH = ModelConfig(
    provider="gemini",
    model_id="gemini-3-flash-preview",
    display_name="Gemini 3 Flash",
    max_tokens=8192,
    context_window=1_000_000,
    supports_tool_use=True,
    training_data_cutoff="2025-01",
    rpm_limit=5, rpd_limit=20,
)

GEMINI_25_FLASH = ModelConfig(
    provider="gemini",
    model_id="gemini-2.5-flash",
    display_name="Gemini 2.5 Flash",
    max_tokens=8192,
    context_window=1_000_000,
    supports_tool_use=True,
    training_data_cutoff="2025-03",
    rpm_limit=5, rpd_limit=20,
)

GEMINI_EMBEDDING_2 = ModelConfig(
    provider="gemini",
    model_id="gemini-embedding-001",
    display_name="Gemini Embedding 2",
    max_tokens=0,
    context_window=8192,
    rpm_limit=100, rpd_limit=1000,
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
# GROQ + MISTRAL
# ─────────────────────────────────────────────────────────────────────

GROQ_LLAMA = ModelConfig(
    provider="groq",
    model_id="meta-llama/llama-4-scout-17b-16e-instruct",
    display_name="Llama 4 Scout via Groq",
    max_tokens=4096,
    context_window=128_000,
    training_data_cutoff="2025-08",
    rpm_limit=30, rpd_limit=14_400,
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
    Roteamento reavaliado pós-teste de carga (15 goals paralelos).
    Nvidia NIM (Nemotron) sofreu timeouts crônicos (>25s) no cold start.
    Groq sofreu 429 imediato pela alta concorrência.
    Gemini 3.1 Flash Lite foi o único que segurou o tranco (com retries 503).

    FAST (alta frequência / extração):
      → Gemini 3.1 Flash Lite (Suportou carga paralela incrivelmente bem)
      → Groq Llama 4 (Para requisições espaçadas/isoladas)
      → DeepSeek V3.2 via NIM (NIM DeepSeek costuma ser mais rápido que o Nemotron)

    DEEP (qualidade + contexto longo):
      → DeepSeek V3.2 via NIM (40 RPM, excelente lógica)
      → Gemini 3 Flash (Free tier limitado, 5 RPM)
      → Nemotron Ultra 253B (Pesado, timeouts frequentes, bom como último recurso free)
      → DeepSeek Chat (Pago, infalível)

    ADVERSARIAL (reasoning, red team):
      → NVIDIA QwQ 32B (Raciocínio nativo, rápido no NIM)
      → DeepSeek Reasoner (Pago, melhor do mercado)
      → Gemini 3 Flash

    SYNTHESIS (relatório final):
      → Gemini 3.1 Flash Lite
      → NVIDIA DeepSeek V3.2
      → DeepSeek Chat

    JUDGE (verificação independente):
      → Gemini 3 Flash
      → Groq Llama 4
      → Mistral
    """
    return ModelRouter(routes={
        CognitiveRole.FAST: [
            GEMINI_31_FLASH_LITE,
            GROQ_LLAMA,
            NVIDIA_DEEPSEEK_V32,
        ],
        CognitiveRole.LOCAL: [
            OLLAMA_GEMMA_4,
            OLLAMA_QWEN,
            GEMINI_31_FLASH_LITE,
        ],
        CognitiveRole.DEEP: [
            NVIDIA_DEEPSEEK_V32,
            GEMINI_3_FLASH,
            NVIDIA_NEMOTRON_ULTRA,
            DEEPSEEK_CHAT,
        ],
        CognitiveRole.ADVERSARIAL: [
            NVIDIA_GEMMA_4_31B,  # Perspectiva "Google" sem gastar cota do Gemini API
            NVIDIA_QWQ_32B,
            DEEPSEEK_REASONER,
            GEMINI_3_FLASH,
        ],
        CognitiveRole.SYNTHESIS: [
            GEMINI_31_FLASH_LITE,
            NVIDIA_DEEPSEEK_V32,
            DEEPSEEK_CHAT,
        ],
        CognitiveRole.JUDGE: [
            NVIDIA_GEMMA_4_31B,  # O melhor árbitro divergente e denso
            GEMINI_3_FLASH,
            GROQ_LLAMA,
            MISTRAL_FREE,
        ],
        CognitiveRole.EMBEDDING: [
            GEMINI_EMBEDDING_2,
        ],
    })
