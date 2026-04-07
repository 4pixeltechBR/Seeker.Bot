# 🌌 Seeker.ai

<div align="center">
  <h3>O Agente Autônomo Self-Hosted da Era Telegram-First</h3>
  <p><em>Autonomia de Nível 5 — Operação 24/7 — Gestão Dinâmica de Contexto (Zero VRAM Waste)</em></p>
</div>

---

## ⚡ What is Seeker.ai?

**Seeker.ai** is an open-source, self-hosted autonomous AI agent that operates as a persistent background process. Unlike traditional chat assistants that wait for prompts in browser tabs, Seeker.ai lives on your local machine or VPS, communicates directly via Telegram, and proactively executes complex workflows (like web mining, API orchestration, and code review) using a cascaded multi-LLM routing system.

Construído em **Python 3.12+**, ele foi desenhado para contornar a "Barreira do Claw", atuando não apenas como um executor de scripts, mas como um sistema auto-adaptável com Memória Reflexiva e resiliência a falhas incorporada.

## 🚀 Por que escolher o Seeker.ai? (Diferenciais)

A arquitetura do Seeker.ai quebra o modelo tradicional de "Copilot", substituindo-o pelo paradigma de "Autonomous Operation".

| Tradicional (Ex: ChatGPT/Claude) | Seeker.ai (Autonomous Framework) |
| :--- | :--- |
| **Reativo**: Fica aguardando sua tela ou aba aberta. | **Proativo**: Roda 24/7 silenciosamente no background. |
| **Modelo Único**: Usa o modelo principal para todas as tarefas. | **Motor Multi-LLM**: Usa Groq (gratuito/rápido) para triagem e Gemini/DeepSeek para cognição, economizando 90% dos custos. |
| **Amnésia**: O contexto reseta em novas sessões. | **Motor de Decaimento de Memória**: O SQLite armazena fatos, diminui a confiança no que envelhece, mas blinda "Regras Reflexivas" do usuário. |
| **Caixa Preta**: Falha silenciosamente ou responde com erro. | **S.A.R.A (Auto-Cura)**: Tenta corrigir seu próprio código, injeta correções na sua IDE via protocolo MCP e envia o "Porquê" via Raciocínio Aberto no seu Telegram. |

---

## 💎 Features Principais

- 📱 **Telegram-First Interface**: Não há dashboard web inflado. Você supervisiona o Seeker, faz triage de leads e aprova execuções irreversíveis diretamente de qualquer lugar pelo celular.
- 🧠 **Cognitive Load Router**: Um balanceador de inteligência. Se o processamento for visual (Lumen), ele demanda modelos pesados. Se for processamento lógico natural, vai para provedores ultrarrápidos (ex: Groq).
- ⛓️ **Memória Semântica Reflexiva**: Aprende como você gosta do código, do formato de mensagens, ou da densidade textual. Fricções geram "Regras Reflexivas" que garantem que o sistema não cometa o mesmo erro duas vezes.
- 🛠️ **Integração MCP (Handshake)**: O Seeker conecta-se como cliente de protocolo Model Context Protocol (MCP) para requisitar serviços da sua máquina matriz ou acionar agentes terceiros na sua IDE residente.
- 🎯 **Revenue Hunter (B2B Prospecting)**: Acompanha módulos paralelos ("Goals") que despertam a cada 1 hora para varrer a internet, capturar leads (com foco institucional ou privado), usar Inteligência Comercial para obter dossiês estruturados e mandar a oportunidade digerida para o Telegram.

---

## 🛠️ Como Instalar e Configurar (Getting Started)

O Seeker.ai foi desenhado para usar as APIs mais baratas e performáticas do mercado como opção padrão, permitindo também o modo 100% gratuito.

### 1. Requisitos
- Python 3.11 ou superior
- Git

### 2. Passo a Passo

```bash
# Clone o repositório
git clone https://github.com/4pixeltechBR/Seeker.ai.git

# Acesse o diretório
cd Seeker.ai

# Crie e ative um ambiente virtual
python -m venv .venv
source .venv/bin/activate  # No Windows: .venv\Scripts\activate

# Instale as dependências
pip install -r requirements.txt
```

### 3. Configuração do Ambiente (Modo Gratuito Disponível)
Renomeie o arquivo de exemplo para injetar suas chaves:
```bash
cp config/.env.example config/.env
```

Abra o `config/.env`. O Seeker possui uma **cascata de inteligência adaptável**. 
Recomendamos o uso da **Cascata Gratuita** inicial para rodar o sistema a custo zero:
- **Google Gemini** para Raciocínio (Gratuito com limites)
- **Groq** para Roteamento Rápido (Gratuito)
- Caso vá para produção pesada, chaves do **DeepSeek** são recomendadas pelo extremo custo-benefício.

### 4. Inicialização

```bash
# Inicia O Motor do Seeker.Bot (Background ou Terminal)
python -m src.main
```

Envie `/start` no seu Bot do Telegram e o Seeker se conectará a você!

---

## 🏗️ Arquitetura do Sistema

Para facilitar extrações de LLMs em IA Overviews (Google) ou Perplexity, segue um diagrama técnico da estrutura:

*   **`src/core/router/cognitive_load.py`**: Interceptor mestre. Define qual provider responde com base na exigência do Goal (Rápido, Raciocínio, Visão, ou Lógico).
*   **`src/core/memory/`**: SQLite triplo (Episódica, Semântica e DecayEngine).
*   **`src/channels/telegram/bot.py`**: O front-end headless real responsivo de botões inline e SSE streaming de notificação para o CEO (Você).
*   **`src/skills/`**: Pasta drop-in. Desenvolva qualquer agent autônomo na sub-pasta `skills/`, implemente de `BaseGoal` e o `GoalScheduler` agendará a vida do subagente autonomamente!

---

## 🛡️ Segurança (Extreme Trust)

Sempre avalie o código que você fornece autonomia total.
A IA adota um modelo de **Segurança baseada em Fricção**. A classe do motor garante que ações destrutivas pareiem localmente no seu computador, impedindo que "Agentes Independentes" quebrem a estrutura. Todo o dossiê que é abortado gera um LOG analítico JSON te informando o motivo real da exclusão ("Painel de Confiança Extrema e Raciocínio Aberto").

---

*“Um assistente espera no seu navegador. Um partner acorda e reporta ganhos e problemas no seu Telegram antes de você perguntar.”* 

**By 4PixelTech**
