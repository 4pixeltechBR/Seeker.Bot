# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SEEKER.BOT — ANÁLISE PROFUNDA E CATÁLOGO DE APIS & MODELOS (Atualizado: 25/05/2026)
# Localização: E:\Seeker.Bot\docs\freetiers.md
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Este documento apresenta a **pesquisa de engenharia definitiva** mapeando o catálogo de modelos e seus limites de taxa (rate limits) vigentes, calibrados de acordo com os limites de cota ativa do console do **Google AI Studio** e do **NVIDIA NIM** em **25 de maio de 2026**.

---

## 1. QUADRO COMPARATIVO DE MODELOS DE FRONTEIRA (Maio/2026)

| Provedor | Modelo ID API | Tipo de Modelo | Contexto (In / Out) | Limites de Cota Free / Preço Pago |
| :--- | :--- | :--- | :---: | :---: |
| **DeepSeek** | `deepseek-v4-flash` | Híbrido (Chat & Reasoner) | **1M** / **384K** | Pago ($0.14/M In cache miss, $0.28/M Out) |
| **DeepSeek** | `deepseek-v4-pro` | Inteligência Avançada (CoT) | **1M** / **384K** | Pago ($0.435/M In cache miss, $0.87/M Out) |
| **Google Gemini**| `gemini-3.5-flash` | Multimodal / Agentes GA | **1M** / **65.536** | Free Tier (**5 RPM** / **250K TPM** / **20 RPD**) |
| **Google Gemini**| `gemini-3.1-flash-lite` | Baixa Latência / Custo Efetivo | **1M** / **64.000** | Free Tier (**15 RPM** / **250K TPM** / **500 RPD**) |
| **Google Gemini**| `gemini-3-flash` | Multimodal Geral | **1M** / **65.536** | Free Tier (**5 RPM** / **250K TPM** / **20 RPD**) |
| **Google Gemini**| `gemini-2.5-flash` | Multimodal Geral | **1M** / **8.192** | Free Tier (**5 RPM** / **250K TPM** / **20 RPD**) |
| **Google Gemini**| `gemini-2.5-flash-lite`| Baixa Latência | **1M** / **8.192** | Free Tier (**10 RPM** / **250K TPM** / **20 RPD**) |
| **Google Gemini**| `gemini-3.1-pro` / `2.5-pro` | Inteligência Geral / Agentes | **2M** / **65.536** | ❌ **Indisponível no Free Tier** (0 RPM / 0 RPD) |
| **Google Gemini**| `gemma-4-31b` / `4-26b` | Outros Modelos Dense | **256K** / **Variable**| Free Tier (**15 RPM** / **Ilimitado TPM** / **1.5K RPD**) |
| **Cerebras** | `gpt-oss-120b` | OpenAI OSS MoE 120B | **131.072** | Free Tier (30 RPM / 1M TPD) |
| **Cerebras** | `zai-glm-4.7` | Z.ai GLM 355B (Preview) | **131.072** | Free Tier (30 RPM / 1M TPD) |
| **Cerebras** | `llama-3.3-70b` | Llama 3.3 Ultra-Veloz | **128.000** | ❌ **Inativo/Depreciado** (desde 16/fev/2026) |
| **Groq** | `llama-3.3-70b-versatile` | Llama 3.3 LPU | **128.000** / **32K** | Free Tier (30 RPM / 1.000 RPD / 12K TPM) |
| **Groq** | `gpt-oss-120b` | OpenAI OSS MoE LPU | **128.000** / **65K** | Free Tier (30 RPM / 1.000 TPM / 8K TPD) |
| **Groq** | `qwen3-32b` | Inferência Código LPU | **128.000** / **40K** | Free Tier (60 RPM / 6K TPM) |
| **NVIDIA NIM** | `deepseek-ai/deepseek-r1` | Reasoning (Distilado/Full) | **128.000** | Cota Direta (**40 RPM** / Sem Créditos Iniciais) |

---

## 2. ANÁLISE TÉCNICA APROFUNDADA POR PROVEDOR

### 🔴 DEEPSEEK — A Família V4 (Híbridos de Modo Duplo)
A DeepSeek unificou suas linhas de *Chat* e *Reasoner* nos novos modelos V4 lançados em 24/abril/2026. Os aliases legados (`deepseek-chat` e `deepseek-reasoner`) continuam temporariamente ativos, mas serão **completamente desativados em 24 de julho de 2026**.

* **`deepseek-v4-flash` (284B total / 13B ativos, MoE):**
  * **Modo Duplo:** Suporta transição dinâmica entre Non-thinking e Thinking (CoT).
  * **Contexto de Output Extremo:** Janela de input de 1M de tokens e suporta até **384.000 tokens de output** (essencial para longos scripts e análises extensas).
  * **Custo/Concorrência:** 2.500 requests simultâneos. Preço: $0.14/M input (cache miss), $0.0028/M (cache hit), $0.28/M output.
* **`deepseek-v4-pro` (1.6T total / 49B ativos, MoE):**
  * **Lógica e Raciocínio de Fronteira:** O carro-chefe para tarefas científicas e algoritmos densos.
  * **Preço Pós-Promoção Permanente:** O desconto de 75% original tornou-se permanente. Preço: $0.435/M input (cache miss), $0.0145/M (cache hit), $0.87/M output. Suporta 500 requests simultâneos.

---

### 🟢 GOOGLE GEMINI — Limites Reais de Cota (Google AI Studio)
As cotas reais obtidas diretamente no console do Google AI Studio confirmam a estrutura de limites do Free Tier do desenvolvedor:

* **Gemini 3.5 Flash & 3 Flash:**
  * **Limites do Free Tier:** **5 RPM**, **250K TPM** e **20 RPD**.
  * **⚠️ Ferramenta de Grounding (Busca Google):** Totalmente **Inativa** (0 RPM / 0 RPD) para chamadas de ferramentas de fundamentação de mapa nesses modelos.
* **Gemini 3.1 Flash Lite:**
  * **Limites do Free Tier:** **15 RPM**, **250K TPM** e **500 RPD**.
  * **💡 Ferramenta de Grounding (Busca Google):** Habilitada no Free Tier com cota de **500 RPD** de fundamentação de mapa.
* **Gemini 2.5 Flash & 2.5 Flash Lite:**
  * **Limites:** 5 RPM (2.5 Flash) e 10 RPM (2.5 Flash Lite), mantendo 20 RPD de cota padrão e suporte a **500 RPD** de fundamentação de mapa/busca.
* **Modelos Pro (Gemini 3.1 Pro & 2.5 Pro):**
  * Totalmente **bloqueados** no Free Tier (0 RPM / 0 RPD). Exigem billing ativo.
* **Série Gemma 4 (31B & 26B):**
  * Excelentes limites para modelos densos: **15 RPM**, **TPM Ilimitado** e **1.500 RPD**.

---

### 🟢 CEREBRAS CLOUD — Ultra-velocidade Wafer-Scale
Incrível throughput servido diretamente em hardware CS-3.
* **Depreciação Importante:** O modelo `llama-3.3-70b` foi **desativado/depreciado em 16 de fevereiro de 2026**. Tentativas de uso desse model ID na API retornarão erro. A Cerebras recomenda a migração direta de fluxos de produção para o `gpt-oss-120b`.
* **Modelos Ativos e Recomendados:**
  * **`gpt-oss-120b` (Production):** O modelo MoE open-weight de 120B de parâmetros da OpenAI servido em velocidade ultra-rápida. Suporta janela de contexto de até **131.072 tokens**.
  * **`zai-glm-4.7` (Preview):** Modelo gigante de 355B de parâmetros com janela de 131.072 tokens.
* **Cota do Free Tier:** Mantém a cota generosa de **1.000.000 de tokens por dia (1M TPD)** e **30 RPM**.
* **Depreciações Próximas (27/maio/2026):** Os modelos `llama3.1-8b` e `qwen-3-235b-a22b-instruct-2507` sairão do catálogo oficial nesta data.

---

### 🟢 GROQ — LPU (Low Latency Engine)
* **`llama-3.3-70b-versatile`:** Ativo com contexto de 128.000 tokens. Free Tier limita a **30 RPM**, **1.000 RPD** (Requests Per Day) e **12.000 TPM**.
* **`gpt-oss-120b`:** O modelo open-weight MoE de 120B de parâmetros está disponível no Groq. Limites básicos do Developer Tier: 30 RPM, 1.000 TPM, 8.000 TPD.
* **`qwen3-32b`:** Excelente para desenvolvimento e código rápido. 60 RPM e 6.000 TPM.

---

### 🟢 NVIDIA NIM — Hub de Modelos & Prototipagem
A API de integração do NVIDIA NIM (`build.nvidia.com`) consolidou-se como um hub de inferência de altíssimo desempenho focado em taxas diretas de requisição.

* **Rate Limits e Créditos:** A plataforma do NVIDIA NIM não oferece mais créditos iniciais de desenvolvimento. A cota livre e gratuita é baseada diretamente na taxa de **40 RPM (Requests Per Minute)**. Erros `429` ocorrem se esse limite for excedido. Endpoint base da API compatível com o SDK da OpenAI: `https://integrate.api.nvidia.com/v1`.
* **Modelos Principais Otimizados:**
  * **`nvidia/llama-3.1-nemotron-ultra-253b-v1`:** Modelo reasoning de 253B baseado no Llama 3.1 405B. Suporta contexto de 128K com modo reasoning ativável via prompt.
  * **`nvidia/llama-3.3-nemotron-super-49b-v1.5`:** Modelo de 49B derivado do Llama 3.3 70B, otimizado para fluxos de trabalho agentic de alta eficiência com janela de 128K.
  * **`google/gemma-4-31b-it`:** Modelo multimodal GA de Google com janela de contexto estendida de **256K tokens** via atenção híbrida.
  * **`deepseek-ai/deepseek-r1`:** Reasoning completo com janela de 128K e alto throughput.

---

## 3. ROTEAMENTO COGNITIVO ATUALIZADO DO SEEKER.BOT

O roteamento de inferência do Seeker.Bot está ancorado nas seguintes políticas de modelos de produção:

1. **Geração de Código e Raciocínio Complexo (CognitiveRole.DEEP):**
   * **Primário:** `deepseek-v4-flash` (via API DeepSeek) — Excelente custo-benefício com janela de output de até 384K tokens.
   * **Secundário:** `deepseek-v4-pro` (ou `deepseek-reasoner` até o dia do sunset) para tarefas densas de lógica científica.
   * **Backup Free:** `gpt-oss-120b` (Cerebras) para contextos de até 131K sem custos.

2. **Grounding e Processamento de Logs Massivos (CognitiveRole.VAULT):**
   * **Primário:** `gemini-3.1-flash-lite` (Free Tier) — 15 RPM, 500 RPD e janela de context de 1M de tokens, permitindo uso de ferramentas de busca do Google (grounding) até 500 RPD.
   * **Secundário:** `gemini-3.5-flash` ou `gemini-3.1-pro-preview` (Paid Tier) quando o contexto de input de 2M ou recursos agentic dedicados forem necessários.

3. **Interação Rápida / Chat de Baixa Latência (CognitiveRole.FAST):**
   * **Primário:** `deepseek-v4-flash` — Pelo excelente throughput e custo mínimo.
   * **Secundário (Free):** `gpt-oss-120b` (Cerebras) — Inferência Wafer-scale de altíssima velocidade e sem custos (dentro de 1M TPD).
   * **Terciário (Free):** `llama-3.3-70b-versatile` (Groq) como backup geográfico imediato.

---

## 4. DIVERGÊNCIAS CRÍTICAS E DE ALINHAMENTO: CÓDIGO vs. LIMITES REAIS

Abaixo estão listadas as inconsistências encontradas em `config/models.py` frente ao catálogo real e ativo das APIs em **25/05/2026**. 

> **[!IMPORTANT]**
> As variáveis `CEREBRAS_LLAMA_70B` e `CEREBRAS_QWEN_32B` estão apontando para modelos inativos na Cerebras API e causarão falhas imediatas se executadas. Devem ser migradas com prioridade máxima.

| Config Variable | Parâmetro no Código | Valor Real na API/Console | Severidade | Ação de Correção Recomendada |
| :--- | :--- | :--- | :---: | :--- |
| `CEREBRAS_LLAMA_70B` | `model_id = "llama-3.3-70b"`<br>`context_window = 8_000` | **Inativo (404)**<br>(Novo: `gpt-oss-120b` com **131.072**) | **🚨 CRÍTICA** | **Mudar ID do modelo** para `gpt-oss-120b` e aumentar a janela para **131.072** no código. |
| `CEREBRAS_QWEN_32B` | `model_id = "qwen-3-32b"` | **Inativo (404)** | **🚨 CRÍTICA** | **Remover ou migrar** para `gpt-oss-120b` / desativar, pois o ID não existe na Cerebras. |
| `GEMINI_35_FLASH` | `rpm_limit = 15`<br>`rpd_limit = 1500` | **5 RPM**<br>**20 RPD** (Free Tier) | **🚨 CRÍTICA** | **Reduzir limites** no código de models.py para evitar erros `429` imediatos sob o Free Tier. |
| `DEEPSEEK_REASONER` | `cost_per_1m_input = 0.87`<br>`cost_per_1m_output = 3.48` | **0.435** (Input)<br>**0.87** (Output) | 💰 Média (Custo) | Atualizar os preços no config para refletir a redução permanente de 75% do V4 Pro. |
| `DEEPSEEK_CHAT` | `cost_per_1m_input = 0.07` | **0.14** | 💰 Média (Custo) | Atualizar para `$0.14/M` (cache miss) para manter cálculos de consumo realísticos. |
| `GROQ_LLAMA_70B` | `rpd_limit = 14_400` | **1.000** | ⚠️ Risco de Limite | Ajustar limite diário para 1.000 RPD na Free Tier para evitar interrupções. |
| `GEMINI_31_FLASH_LITE` | `rpm_limit = 15`<br>`rpd_limit = 500` | **15 RPM**<br>**500 RPD** | ✅ **Alinhado** | Nenhuma ação necessária — o código reflete fielmente o limite real de cota do usuário. |
