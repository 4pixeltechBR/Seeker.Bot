<div align="center">

# 🤖 Seeker.Bot

**Agente cognitivo autônomo para Telegram com memória persistente, visão computacional e 17 skills modulares.**

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776ab?logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-lightgrey)]()
[![Telegram](https://img.shields.io/badge/Telegram-Bot-26A5E4?logo=telegram&logoColor=white)]()

🇺🇸 [Read in English](README.md)

<img src="docs/demo.png" width="380" alt="Seeker.Bot Demo">

</div>

---

## ✨ O que é o Seeker?

O Seeker.Bot não é um chatbot — é um **agente cognitivo autônomo** que vive no seu Telegram. Ele decide como pensar sobre cada mensagem (reflexiva, deliberada, ou análise profunda), pesquisa na web, lembra de tudo que vocês discutiram, e roda 17 skills independentes em background — de curadoria diária de notícias até prospecção de vendas B2B.

O que o torna diferente: uma **cascade multi-provider de APIs** que nunca para de funcionar, um **RL Bandit** (Aprendizado por Reforço) que aprende qual modelo de IA funciona melhor para cada tarefa, e **Evidence Arbitrage** — triangulação de respostas de múltiplos providers para pegar alucinações.

Você pode rodar ele inteiramente na nuvem com tiers gratuitos de API, ou **100% localmente** na sua GPU sem precisar de internet.

---

## ⚡ Início Rápido

```bash
git clone https://github.com/4pixeltechBR/Seeker.Bot
cd Seeker.Bot
install.bat
```

O instalador te guia por tudo: nomear seu assistente, escolher modo cloud ou local, e selecionar quais skills ativar.

---

## 🔑 Providers de API e Modelos

O Seeker usa uma **cascade multi-provider** — você pode usar apenas **1 chave de API** ou até 6+ providers para máxima resiliência.

### Providers

| Provider | Modelo | Função no Seeker | Tier Gratuito | Obter Chave |
|---|---|---|---|---|
| **Google Gemini** | `gemini-3.1-flash-lite` | ⚡ FAST (alta frequência) | ✅ 15 RPM, 500/dia | [aistudio.google.com](https://aistudio.google.com/apikey) |
| **Google Gemini** | `gemini-3-flash` | 🧠 DEEP + ⚖️ JUDGE | ✅ 5 RPM, 20/dia | mesma chave |
| **Google Gemini** | `gemini-embedding-001` | 💾 Embeddings (memória) | ✅ 100 RPM | mesma chave |
| **Google Gemini** | `gemini-2.5-flash` | 👁️ VLM Cloud (visão) | ✅ 5 RPM | mesma chave |
| **Groq** | `llama-4-scout-17b` | ⚡ FAST (ultra-rápido) | ✅ 30 RPM, 14.4K/dia | [console.groq.com](https://console.groq.com/keys) |
| **NVIDIA NIM** | `deepseek-v3.2` | 🧠 DEEP + 📝 SYNTHESIS | ✅ 40 RPM, ilimitado | [build.nvidia.com](https://build.nvidia.com/) |
| **NVIDIA NIM** | `nemotron-ultra-253b` | 🧠 DEEP (fallback pesado) | ✅ 40 RPM | mesma chave |
| **NVIDIA NIM** | `qwq-32b` | 🔴 ADVERSARIAL (reasoning) | ✅ 40 RPM | mesma chave |
| **NVIDIA NIM** | `gemma-4-31b-it` | ⚖️ JUDGE + 🔴 ADVERSARIAL | ✅ 40 RPM | mesma chave |
| **DeepSeek** | `deepseek-chat` | 🧠 DEEP (backup pago) | ❌ ~$0.28/1M tok | [platform.deepseek.com](https://platform.deepseek.com/) |
| **Mistral** | `mistral-small-latest` | ⚖️ JUDGE (fallback) | ✅ 2 RPM | [console.mistral.ai](https://console.mistral.ai/) |
| **Ollama** | `qwen3.5:4b` | 👁️ VLM Local (visão offline) | ✅ 100% local | [ollama.com](https://ollama.com/) |

### Cenários de Configuração

| Cenário | Chaves | Resultado | Custo Mensal |
|---|---|---|---|
| 🟢 **Mínimo** | 1× Gemini | Funcional, mais lento em pico | $0 |
| 🟡 **Recomendado** | Gemini + Groq + NVIDIA | Rápido e resiliente. 3 providers gratuitos | $0 |
| 🔵 **Full Power** | Todos os 5+ providers | Máxima velocidade. Zero downtime | ~$2-5 (DeepSeek) |
| 🏠 **100% Local** | Nenhuma (Ollama) | Offline, privado, sem custo | $0 + GPU |

> **Nota:** Você pode rodar com UMA única chave (Gemini). O Seeker se adapta e usa o que tem. Quanto mais providers, mais resiliente.

---

## 🧠 Como a Cascade Funciona

Quando o Seeker precisa chamar um modelo de IA, ele não depende de um único provider. Usa uma **cascade de 6 tiers com fallback automático**:

```
Requisição → Tier 1 (Gemini Flash Lite)
                  ↓ falhou?
             Tier 2 (Groq Llama 4)
                  ↓ falhou?
             Tier 3 (NVIDIA NIM)
                  ↓ falhou?
             Tier 4 (DeepSeek Pago)
                  ↓ falhou?
             Tier 5 (Mistral)
                  ↓ falhou?
             Cache Local (última resposta)
```

Um **RL Bandit** (Aprendizado por Reforço) aprende continuamente qual provider é mais rápido e confiável para cada tipo de tarefa e reordena a cascade em tempo real.

---

## 🏠 Modo 100% Local (Sem Internet)

O Seeker pode rodar inteiramente no seu computador, sem API keys e sem internet.

### Requisitos
- [Ollama](https://ollama.com/) instalado
- GPU com VRAM suficiente

### Perfis por VRAM

| Sua VRAM | Modelo FAST | Modelo DEEP | Visão (VLM) | Embeddings |
|---|---|---|---|---|
| **8 GB** | Qwen 3.5 4B | Qwen 3.5 4B | Qwen 3.5 4B | nomic-embed-text |
| **16 GB** | Qwen 3.5 4B | Gemma 4 12B | Qwen 3.5 4B | nomic-embed-text |
| **24 GB+** | Qwen 3.5 4B | Qwen 3.5 27B | Gemma 4 E4B | mxbai-embed-large |

### Configuração
```bash
# No seu .env:
SEEKER_MODE=local
LOCAL_VRAM_GB=8    # sua VRAM disponível

# Baixe os modelos:
ollama pull qwen3.5:4b
ollama pull nomic-embed-text

# Inicie:
start_watchdog.bat
```

---

## 🛠️ Skills Modulares

Skills são agentes autônomos que rodam em background num agendamento. Você escolhe quais ativar durante a instalação.

### 🟢 Core (Sempre Ativas)
| Skill | Descrição |
|---|---|
| **Health Monitor** | Dashboard de saúde do sistema em tempo real |
| **Self-Improvement** | S.A.R.A. — auto-cura a cada 6 horas |
| **Daily Briefing** | Briefing matinal às 7h com agenda e prioridades |

### 🟡 Recomendadas
| Skill | Descrição |
|---|---|
| **Knowledge Vault** | Segundo Cérebro — salve fatos no Obsidian com um toque |
| **Scheduler** | Agendamento de tarefas por linguagem natural via wizard |
| **SenseNews** | Curadoria de notícias do ecossistema de IA por nicho |
| **Sherlock News** | Monitoramento de lançamentos tech e modelos |
| **Bug Analyzer** | Envie um traceback, receba análise de causa raiz |
| **Skill Creator** | Auto-geração de novas skills a partir de padrões |

### 🔵 Especialistas
| Skill | Descrição | Requer |
|---|---|---|
| **Seeker Sales** | BDR Unificado — prospecção B2B + mineração de eventos | — |
| **Event Map Scout** | Mapeamento preditivo regional de eventos com PDF | — |
| **Seeker Sales Week** | Relatório semanal com dossiês de leads | SMTP |
| **Email Monitor** | Monitoramento de inbox com filtros inteligentes | IMAP |
| **Desktop Watch** | Vigilância AFK da tela com detecção de padrões | VLM |
| **Remote Executor** | Execução de planos complexos com workflow de aprovação | — |
| **OS Control** | Controle de arquivos e aplicações do sistema | — |
| **Git Automation** | Auto-backup em repositório GitHub privado | GitHub Token |

---

## 📋 Guia Completo de Instalação

### Passo 1: Criar o Bot no Telegram
1. Abra o Telegram e busque **@BotFather**
2. Envie `/newbot`
3. Escolha um nome (ex: "Meu Seeker")
4. Copie o **TOKEN** — você vai precisar dele no `.env`
5. Para descobrir seu **User ID**: envie `/start` para **@userinfobot**

### Passo 2: Obter Chaves de API
No mínimo, você precisa de **1 chave** (Gemini). Para melhores resultados, pegue 3 (todas gratuitas):

| Provider | Passos | Link |
|---|---|---|
| **Google Gemini** | 1. Login com Google → 2. Clique "Criar Chave API" | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| **Groq** | 1. Crie conta → 2. Vá em API Keys → 3. Crie chave | [console.groq.com/keys](https://console.groq.com/keys) |
| **NVIDIA NIM** | 1. Crie conta → 2. Vá em qualquer modelo → 3. Clique "Get API Key" | [build.nvidia.com](https://build.nvidia.com/) |

### Passo 3: Clonar e Instalar
```bash
git clone https://github.com/4pixeltechBR/Seeker.Bot
cd Seeker.Bot
install.bat
```

### Passo 4: Configurar o `.env`
O instalador abre o `.env`. Preencha no mínimo:
```env
ASSISTANT_NAME=NomeDoSeuAssistente
TELEGRAM_BOT_TOKEN=seu_token_do_botfather
TELEGRAM_ALLOWED_USERS=seu_user_id_telegram
GEMINI_API_KEY=sua_chave_gemini
```

### Passo 5: Iniciar
```bash
start_watchdog.bat
```

### Passo 6 (Opcional): Integração Obsidian
1. Instale o [Obsidian](https://obsidian.md/)
2. Crie um vault
3. Defina `OBSIDIAN_VAULT_PATH=C:\Users\Voce\Obsidian\Vault` no `.env`

### Passo 7 (Opcional): Backup Git Automático
1. Crie um repositório **privado** no GitHub
2. Gere um [Token de Acesso Pessoal](https://github.com/settings/tokens) (escopo repo)
3. Preencha `GITHUB_TOKEN` e `GITHUB_REPO` no `.env`

### Passo 8 (Opcional): Monitoramento de Email
1. Acesse [Segurança da Conta Google](https://myaccount.google.com/security)
2. Ative Verificação em 2 Fatores
3. Gere uma [Senha de App](https://myaccount.google.com/apppasswords)
4. Preencha os campos SMTP/IMAP no `.env`

---

## 🛠️ Desenvolvido Com

- **[Google Antigravity](https://blog.google/technology/google-deepmind/)** — Ambiente de desenvolvimento com IA
- **[Claude Code](https://claude.ai/)** — Pair programming avançado com IA
- **[Python 3.10+](https://python.org)** — Runtime principal
- **[aiogram 3](https://aiogram.dev/)** — Framework assíncrono para Telegram Bot
- **[Ollama](https://ollama.com/)** — Motor de inferência local para LLMs

---

## 🤝 Contribuindo

Contribuições são bem-vindas! Leia [CONTRIBUTING.md](CONTRIBUTING.md) para diretrizes.

---

## 📜 Licença

Este projeto está licenciado sob a **Apache License 2.0** — veja o arquivo [LICENSE](LICENSE) para detalhes.

```
Copyright 2026 4pixeltech / Victor Machado Mendonça
```

---

<div align="center">

**Feito com 🧠 por [4pixeltech](https://github.com/4pixeltechBR)**

*Se o Seeker te ajudou, considere dar uma ⭐ no GitHub!*

</div>
