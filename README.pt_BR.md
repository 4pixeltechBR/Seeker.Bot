# 🌌 Seeker.Bot

<div align="center">
  <h3>O Agente Autônomo Self-Hosted da Era Telegram-First</h3>
  <p><em>Autonomia de Nível 5 — Operação 24/7 — Gestão Dinâmica de Contexto</em></p>
  <p><strong>Desenvolvido via Vibe Coding 🌊</strong></p>
</div>

---

## ⚡ O que é Seeker.Bot?

**Seeker.Bot** é um agente autônomo de IA de código aberto e auto-hospedado que opera como um processo contínuo em background. Diferentemente de assistentes tradicionais que ficam aguardando em abas de navegador, Seeker.Bot vive na sua máquina local ou VPS, comunica-se diretamente via Telegram, e executa proativamente workflows complexos (mineração web, orquestração de APIs, análise de código) usando um sistema de roteamento multi-LLM em cascata.

Construído em **Python 3.10+**, foi desenhado para superar a "Barreira do Claude" (não conseguir executar scripts complexos), atuando não apenas como executor de código, mas como um sistema auto-adaptável com Memória Reflexiva e resiliência incorporada.

## 🚀 Por que escolher Seeker.Bot?

| Tradicional (ChatGPT/Claude) | Seeker.Bot |
|:---|:---|
| **Reativo**: Fica aguardando você abrir a aba. | **Proativo**: Roda 24/7 silenciosamente. |
| **Modelo Único**: Um modelo para tudo. | **Multi-LLM**: Groq (rápido/grátis) + Gemini/DeepSeek (cognição). Economiza 90% de custos. |
| **Amnésia**: Contexto reseta em novas sessões. | **Memória Persistente**: SQLite armazena fatos, diminui confiança com tempo, mas blinda "Regras Reflexivas". |
| **Caixa Preta**: Falha silenciosamente. | **S.A.R.A (Auto-Cura)**: Corrige seu próprio código, injeta via MCP, envia explicação via Telegram. |
| **Privacidade Cloud**: Dados vão para servidores remotos. | **Privacidade Local**: Tudo na sua máquina. SQLite local, zero nuvem, seus dados nunca saem. |
| **Extensibilidade Limitada**: Plugins pré-aprovados. | **Skills Dinâmicas**: Crie capacidades em linguagem natural — Seeker escreve, testa e registra. |
| **Vendor Lock-in**: Preso a uma plataforma. | **Multi-Provider + Fallback**: NVIDIA → Groq → Gemini → DeepSeek → Local. Mude quando quiser. |

---

## 💎 Habilidades Disponíveis

| Skill | Função | Saída |
|:---|:---|:---|
| **Revenue Hunter** 🎯 | Mineração B2B em 3 fases (Discovery, Enrich, Qualify). | Dossiê comercial + PDF. |
| **SenseNews** 📰 | Curadoria diária (10 AM) em nichos personalizados. | Relatório de inteligência em PDF. |
| **Desktop Watch** 👁️ | Monitoramento visual com AFK Protocol inteligente. | Contexto visual para decisões. |
| **Email Monitor** 📧 | Triagem e resposta automática de emails importantes. | Inbox auto-gerenciado. |
| **Git Automator** 💻 | Gestão de repos, deploy e health checks. | Sistema sempre íntegro. |
| **Skill Creator** 🧬 | Crie novas skills em linguagem natural. | Expansão orgânica. |
| **Scout Hunter** 🎯 | B2B lead generation completa (scraping + enrichment + copy). | Lista de leads com propostas. |

---

## 🚀 Quick Start (5 minutos)

### Pré-requisitos
- Python 3.10+
- Telegram Bot (create at @BotFather)
- API Key de pelo menos um provider (Groq é grátis)

### Instalação

```bash
# 1. Clone
git clone https://github.com/4pixeltech/Seeker.Bot.git
cd Seeker.Bot

# 2. Setup (interativo, bilíngue)
python setup.py

# 3. Inicie
python -m src
```

### Primeiros Comandos

**Operação:**
```
/start              # Menu principal
/search Python      # Buscar 5 resultados na web
/god                # Força análise profunda
/print              # Screenshot rápido
/watch              # Ativa vigilância visual (2 min)
```

**Sistema & Inteligência:**
```
/status             # Painel de providers e memória
/saude              # Dashboard de goals
/memory             # Fatos aprendidos sobre você
/scout              # Dispara campanha B2B Scout
/configure_news     # Personaliza notícias (SenseNews)
```

**Dados & Análise:**
```
/crm                # Últimos 5 leads qualificados
/rate               # Status dos rate limiters
/decay              # Limpeza manual de confiança
/habits             # Padrões de decisão aprendidos
```

---

## 🧬 Criar Skills Dinamicamente

Uma das maiores vantagens do Seeker.Bot é criar novas capacidades sem modificar código:

```
Você: "Crie uma skill que me avise quando X acontecer"
Seeker: "Entendido. Vou criar um monitor que verifica X a cada 5min."
        → Escreve goal_monitor_x.py
        → Testa sintaxe e imports
        → Registra no auto-discovery
        → "Pronto! /start e escolha 'Ativar Monitor X'"
```

Exemplos de skills que você pode criar:
- **Notificações**: Avisos personalizados via Telegram
- **Monitores**: Vigilância de websites, preços, eventos
- **Integrações**: Conectar com suas APIs favoritas
- **Relatórios**: Gerar análises automáticas
- **Bots**: Responders automáticos para tarefas repetitivas

---

## 🔧 Configuração

### Variáveis de Ambiente (.env)

```env
# Obrigatório
TELEGRAM_BOT_TOKEN=seu_token_aqui

# Pelo menos 1 (Groq é grátis)
GROQ_API_KEY=sk-...
GEMINI_API_KEY=ai-...
DEEPSEEK_API_KEY=sk-...

# Opcional (web search)
TAVILY_API_KEY=tvly-...

# Idioma
LANGUAGE=pt_BR  # ou en_US
```

### Ollama (Fallback Local)

Para usar modelos locais (privacidade máxima):

```bash
# Instale Ollama: https://ollama.ai
ollama pull qwen2:7b

# Seeker automaticamente usa como fallback
```

---

## 📊 Architecture

```
┌─ Telegram Bot ─────────────────────┐
│  (Comunicação com usuário)          │
└─────────────┬──────────────────────┘
              │
         ┌────▼─────────────┐
         │  Cognitive Router │  (Decide REFLEX/DELIBERATE/DEEP)
         └────┬─────────────┘
              │
    ┌─────────┼─────────────┐
    │         │             │
┌───▼──┐  ┌──▼──┐  ┌──────▼─┐
│ FAST │  │ NIM  │  │ DEEP  │
│Groq  │  │NVIDIA│  │ Gemini│
└──┬───┘  └──┬───┘  └───┬───┘
   │         │          │
   └─────────┼──────────┘
             │
      ┌──────▼──────┐
      │ LLM Cascade │  (Fallback automático)
      │ NVIDIA→Groq │
      │ →Gemini→    │
      │ DeepSeek    │
      │ →Local      │
      └──────┬──────┘
             │
      ┌──────▼────────────┐
      │ Semantic Memory   │
      │ (SQLite + Decay)  │
      └───────────────────┘
```

---

## 🛡️ Privacidade & Segurança

- ✅ **Tudo Local**: Banco de dados SQLite na sua máquina
- ✅ **Sem Sincronização Cloud**: Seus dados nunca saem da máquina
- ✅ **Fallback Local**: Ollama permite rodar sem APIs cloud
- ✅ **AFK Protocol**: Controlador da visão pessoal com autorização explícita
- ✅ **Open Source**: Código auditável, sem black boxes

---

## 📚 Documentação

- **[CONTRIBUTING.md](CONTRIBUTING.md)** — Como contribuir
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — Design profundo
- **[API Reference](docs/api.md)** — Endpoints e funções
- **[GitHub Issues](https://github.com/4pixeltech/Seeker.Bot/issues)** — Bugs e features

---

## 💬 Suporte

- 📧 **Email**: 4pixeltech@gmail.com
- 🐛 **Bugs**: GitHub Issues
- 💡 **Features**: GitHub Discussions
- 📖 **Docs**: https://github.com/4pixeltech/Seeker.Bot

---

## 📜 Licença

MIT License — Use livremente! 🚀

---

**Desenvolvido com ❤️ por 4Pixel Tech**
