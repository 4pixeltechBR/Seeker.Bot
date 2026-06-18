# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MANUAL DE CONSULTA: FREE TIERS DE LLM & POLÍTICAS DE USO (Junho 2026)
# Compilação e Validação Fina: 27 de maio de 2026
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Este documento consolida as cotas gratuitas (Free Tiers) das principais plataformas de inferência de LLMs, incluindo limites técnicos e políticas de uso. Modelos descontinuados foram removidos.

---

## 1. QUADRO COMPARATIVO GERAL DE MODELOS FREE & POLÍTICAS

| Provedor | Modelo ID API | Contexto (In) | Limites de Cota Free (RPM / TPM / RPD) | Política de Uso |
| :--- | :--- | :---: | :---: | :--- |
| **Google** | `gemini-3.1-flash-lite` | **1M** | 15 RPM / 250K TPM / 500 RPD | Uso comercial permitido até 500 RPD; Grounding de 500 RPD habilitado. |
| **Google** | `gemini-3.5-flash` | **1M** | 5 RPM / 250K TPM / 20 RPD | Uso não‑comercial; Grounding **desativado**. |
| **Google** | `gemini-3-flash` | **1M** | 5 RPM / 250K TPM / 20 RPD | Idem ao acima. |
| **Google** | `gemini-2.5-flash-lite` | **1M** | 10 RPM / 250K TPM / 20 RPD | Grounding de 500 RPD habilitado. |
| **Google** | `gemini-2.5-flash` | **1M** | 5 RPM / 250K TPM / 20 RPD | Grounding de 500 RPD habilitado. |
| **Google** | `gemma-4-31b` / `gemma-4-26b` | **256K** | 15 RPM / Ilimitado TPM / 1.5K RPD | Uso livre, sem restrição comercial. |
| **Google** | `imagen-4-generate` | **-** | - RPM / - TPM / 25 RPD | Geração de imagens; uso pessoal. |
| **Google** | `gemini-2.5-flash-audio-dialog` | **1M** | Ilimitado RPM / 1M TPM / Ilimitado RPD | API Live de áudio; uso livre. |
| **Google** | `gemini-3.5-live-translate` | **-** | Ilimitado RPM / 20K TPM / Ilimitado RPD | Tradução em tempo real; uso livre. |
| **Google** | `gemini-3-flash-live` | **-** | Ilimitado RPM / 65K TPM / Ilimitado RPD | Interações rápidas de áudio; uso livre. |
| **Google** | `gemini-robotics-er-1.6-preview` | **1M** | 5 RPM / 250K TPM / 20 RPD | Modelo robótico; uso experimental. |
| **Google** | `gemini-robotics-er-1.5-preview` | **1M** | 10 RPM / 250K TPM / 20 RPD | Modelo robótico; uso experimental. |
| **Anthropic** | `claude-3.5-sonnet` | **200K** | Dinâmico (5‑100 msgs/dia) | Limite baseado em janela rolante de 5 h; uso pessoal e não‑comercial. |
| **Anthropic** | `claude-3-haiku` | **200K** | Dinâmico (similar ao Sonnet) | Mesma política de uso que Sonnet. |
| **OpenAI** | `gpt-4o-mini` (free tier) | **128K** | 20 RPM / 100K TPM / 200 RPD | Uso gratuito limitado a 200 RPD; proibição de uso comercial pesado. |
| **OpenAI** | `gpt-3.5-turbo` (free) | **16K** | 30 RPM / 150K TPM / 300 RPD | Uso pessoal, permitido em projetos open‑source. |
| **NVIDIA** | `deepseek-ai/deepseek-r1` | **128K** | 40 RPM / Dinâmico TPM / Sem cap diário | NIM Serverless; uso livre, sem crédito. |
| **NVIDIA** | `nvidia/llama-3.1-nemotron-ultra-253b-v1` | **128K** | 40 RPM / Dinâmico TPM / Sem cap diário | Uso livre; reasoning habilitado via prompt. |
| **NVIDIA** | `nvidia/nemotron-3-super-120b-a12b` | **1M** | 40 RPM / Dinâmico TPM / Sem cap diário | Contexto estendido; uso livre. |
| **Groq** | `meta-llama/llama-4-scout-17b-16e-instruct` | **131K** | 30 RPM / 30K TPM / 1K RPD | Uso gratuito limitado; recomendado para lógica avançada. |
| **Groq** | `llama-3.3-70b-versatile` | **128K** | 30 RPM / 12K TPM / 1K RPD | Modelo versátil; uso livre. |
| **Groq** | `openai/gpt-oss-120b` | **128K** | 30 RPM / 8K TPM / 1K RPD | MoE aberto; uso livre. |
| **Groq** | `qwen3-32b` | **128K** | 60 RPM / 6K TPM / 1K RPD | Modelo rápido para código. |
| **Cerebras** | `gpt-oss-120b` | **131K** | 30 RPM / Dinâmico TPM / 1M TPD (global) | Wafer‑Scale Engine; uso livre. |
| **Cerebras** | `zai-glm-4.7` | **131K** | 10 RPM / Dinâmico TPM / 1M TPD (global) | Preview; uso livre. |
| **OpenRouter** | `openrouter/free` | **200K** | 20 RPM / Dinâmico TPM / 200 RPD | Roteador inteligente que escolhe modelo free ativo. |
| **OpenRouter** | `openrouter/owl-alpha` | **1M** | 20 RPM / Dinâmico TPM / 200 RPD | Modelo focado em raciocínio profundo (CoT). |
| **OpenRouter** | `qwen/qwen3-coder:free` | **1M** | 20 RPM / Dinâmico TPM / 200 RPD | Otimizado para programação avançada. |
| **OpenRouter** | `poolside/laguna-m.1:free` | **262K** | 20 RPM / Dinâmico TPM / 200 RPD | Engenharia de software autônoma. |
| **Mistral AI** | `codestral-2508` | **-** | 625K TPM / Ilimitado Mês / 2.08 RPS | Geração de código rápido. |
| **Mistral AI** | `magistral-medium-2509` | **-** | 75K TPM / 1B TPD / 0.08 RPS | Raciocínio complexo. |
| **DeepSeek** | `deepseek-v4-flash` | **-** | 2.5K concurrent reqs | Uso gratuito, alta concorrência; limite por conexão. |
| **DeepSeek** | `deepseek-v4-pro` | **-** | 500 concurrent reqs | Plano pago; incluído para referência. |
| **KIMI / Moonshot AI** | `kimi-k2.6` | **-** | 20 RPM / 500K TPM / 1.5M TPD | Tier 0 gratuito; uso comercial limitado. |
| **Moonshot** | `moonshot-v1-128k` | **128K** | 20 RPM / 500K TPM / 1.5M TPD | Uso gratuito, foco em long‑context. |
| **Cohere** | `command-r` (free tier) | **64K** | 30 RPM / 150K TPM / 300 RPD | Uso pessoal; proibição de re‑treinamento. |
| **Deepinfra** | `deepinfra/llama-2-70b` (free) | **4K** | 25 RPM / 200K TPM / 250 RPD | Acesso via API pública; uso não‑comercial somente. |

---

## 2. DETALHAMENTO TÉCNICO & POLÍTICAS DE USO POR PROVEDOR

### 🟢 GOOGLE AI STUDIO (Gemini API)
* **Cotas**: conforme tabela acima.
* **Política**: uso gratuito permitido em projetos pessoais e pesquisa; **não** para produção comercial de larga escala.

### 🟢 ANTHROPIC
* **Limites Dinâmicos**: janela rolante de 5 h; aproximadamente 30‑100 mensagens/dia, dependendo da complexidade.
* **Política de Uso**: permitido apenas em projetos **não‑comerciais**; proibição de redistribuição do output em produtos pagos.

### 🟢 OPENAI
* **Free Tier** (`gpt‑4o‑mini`, `gpt‑3.5‑turbo`): 20 RPM, 100K TPM, 200 RPD.
* **Política**: uso gratuito para prototipagem e testes; **restrito** a 200 RPD e não pode ser usado para serviços SaaS comerciais sem upgrade.

### 🟢 NVIDIA NIM
* **Cotas**: 40 RPM global, sem limite diário de tokens.
* **Política**: uso livre para pesquisa e desenvolvimento interno; **não** para geração de renda direta.

### 🟢 GROQ CLOUD
* **Cotas**: conforme tabela acima.
* **Política**: uso gratuito destinado a experimentação; proibição de tráfego de produção com SLA.

### 🟢 CEREBRAS CLOUD
* **Cotas**: limites compartilhados entre os dois modelos ativos.
* **Política**: uso livre apenas para **P&D** interno; proibição de redistribuição comercial.

### 🟢 OPENROUTER
* **Cotas**: 20 RPM / 200 RPD para o roteador gratuito.
* **Política**: rota inteligente; permite escolha automática do modelo free ativo. 
* **Uso**: ok para protótipos, **não** para SaaS em produção sem licença.

### 🟢 MISTRAL AI
* **Políticas**: planos gratuitos são para desenvolvimento e teste; **não** há permissões para uso comercial de alta escala.

### 🟢 DEEPSEEK
* **Cotas**: limite de concorrência (2.5 k reqs) ao invés de RPM/TPM.
* **Política**: uso gratuito para pesquisa; restrição de uso comercial pesado.

### 🟢 KIMI / MOONSHOT AI
* **Cotas**: 20 RPM, 500K TPM, 1.5M TPD no Tier 0.
* **Política**: uso gratuito permitido para **uso pessoal** e **prototipagem**; proibição de oferta de serviço pago.

### 🟢 COHERE
* **Cotas**: 30 RPM / 150K TPM / 300 RPD.
* **Política**: gratuito apenas para projetos **não‑comerciais**; saída deve ser atribuído ao Cohere.

### 🟢 DEEPINFRA
* **Cotas**: 25 RPM / 200K TPM / 250 RPD.
* **Política**: acesso público gratuito, restrito a **uso não‑comercial** e **não‑redistribuição**.

---

## 3. NOTAS DE INFRAESTRUTURA & INTEGRAÇÃO
1. **Roteamento Dinâmico** – Use LiteLLM ou camada de fallback para alternar entre provedores ao atingir limites.
2. **Depreciações** – Modelos listados como descontinuados foram removidos. Atualize seu código para evitar chamadas a `gemini-3-pro`, `gemini-2-flash` e similares.
3. **Monitoramento** – Implemente contadores de RPM/TPM por provedor para evitar 429.

---

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━