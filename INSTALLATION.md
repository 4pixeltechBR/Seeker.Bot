# 🚀 Seeker.Bot — Installation Guide

**Português | [English](#english)**

---

## 📋 Pré-requisitos

- **Python 3.10+** ([download](https://www.python.org/downloads/))
- **Git** ([download](https://git-scm.com/))
- **Docker** (opcional, para deployment containerizado)

### APIs Obrigatórias

Para usar o Seeker.Bot você precisa de pelo menos 2 dos 3 providers principais:

1. **NVIDIA NIM** (Recomendado) — [build.nvidia.com](https://build.nvidia.com/)
   - Gratuito, 40 RPM, Nemotron Super 49B
   
2. **Google Gemini** — [aistudio.google.com](https://aistudio.google.com/)
   - Gratuito, 5 RPM (modelo flash)
   
3. **Groq** — [console.groq.com](https://console.groq.com/)
   - Gratuito, 30 RPM, Llama 4

### APIs Opcionais

- **Telegram Bot Token** — [@BotFather](https://t.me/BotFather)
- **Tavily Search** — [tavily.com](https://tavily.com/) (web search)
- **GitHub Token** — [github.com/settings/tokens](https://github.com/settings/tokens) (auto-backup)

---

## 🔧 Instalação Rápida (Recomendado)

### 1️⃣ Clone o Repositório

```bash
git clone https://github.com/4pixeltechBR/Seeker.Bot.git
cd Seeker.Bot
```

### 2️⃣ Execute o Setup Wizard

```bash
python setup.py
```

O wizard irá:
- ✅ Verificar Python e Git
- ✅ Criar ambiente virtual
- ✅ Instalar dependências
- ✅ Configurar variáveis de ambiente (.env)
- ✅ Inicializar banco de dados
- ✅ Testar conectividade das APIs

### 3️⃣ Inicie o Bot

```bash
python -m src
```

Procure por mensagens como:
```
07:35:21 [seeker.telegram] INFO: Seeker.Bot iniciado
07:35:21 [seeker.telegram] INFO: Aguardando mensagens...
```

### 4️⃣ Use no Telegram

Abra o Telegram e procure por **@SeekerBR1_bot** (ou o seu bot configurado):

```
/start           — Menu principal
/god             — Ativa análise profunda
/search [query]  — Busca na web
/status          — Status do sistema
/scout           — Dispara campanha B2B Scout
```

---

## 🐳 Instalação com Docker

### Pré-requisitos

- **Docker** ([install](https://docs.docker.com/get-docker/))
- **Docker Compose** (incluído no Docker Desktop)

### 1️⃣ Configure o Arquivo de Ambiente

Crie `config/.env`:

```bash
cp config/.env.example config/.env
```

Edite com suas API keys:

```env
NVIDIA_API_KEY=nvapi-...
GEMINI_API_KEY=AIza...
GROQ_API_KEY=gsk_...
TELEGRAM_BOT_TOKEN=123456789:ABCde...
TELEGRAM_ALLOWED_USERS=7607235163
```

### 2️⃣ Execute com Docker Compose

```bash
# Build e inicie
docker-compose up -d

# Ver logs em tempo real
docker-compose logs -f seeker-bot

# Parar
docker-compose down
```

### 3️⃣ Verificar Status

```bash
docker ps                  # Containers ativos
docker-compose ps          # Status dos serviços
docker-compose logs        # Histórico de logs
```

---

## 📁 Estrutura de Arquivos

```
Seeker.Bot/
├── setup.py                    # ⭐ Setup wizard interativo
├── Dockerfile                  # Docker image
├── docker-compose.yml          # Docker deployment
├── requirements.txt            # Dependências Python
│
├── config/
│   ├── .env                   # 🔑 Variáveis de ambiente
│   ├── .env.example           # Template
│   └── models.py              # Configuração de modelos LLM
│
├── src/
│   ├── __main__.py            # Entry point
│   ├── core/                  # Pipeline, memória, reasoning
│   ├── providers/             # NVIDIA, Groq, Gemini, etc
│   ├── skills/                # Goals autonomos
│   ├── channels/              # Telegram, Email
│   └── ...
│
├── data/                      # 💾 SQLite database
│   └── seeker_memory.db
│
├── logs/                      # 📝 Log files
└── cache/                     # ⚡ Cache local
```

---

## 🔑 Variáveis de Ambiente

### Providers (Obrigatórios)

```env
# NVIDIA — Recomendado, gratuito, fast
NVIDIA_API_KEY=nvapi-...

# Google Gemini — Para embeddings de alta qualidade
GEMINI_API_KEY=AIza...

# Groq — Fallback rápido
GROQ_API_KEY=gsk_...
```

### Telegram

```env
# Bot Token do BotFather
TELEGRAM_BOT_TOKEN=123456789:ABCde...

# Seu Telegram ID (quem pode usar o bot)
TELEGRAM_ALLOWED_USERS=7607235163
```

### Opcional

```env
# Search web
TAVILY_API_KEY=tvly-...

# Auto-backup no GitHub
GITHUB_TOKEN=ghp_...
GITHUB_REPO=4pixeltechBR/Seeker.ai

# Log level
LOG_LEVEL=INFO  # ou DEBUG, WARNING, ERROR
```

---

## 🆘 Troubleshooting

### "ModuleNotFoundError: No module named..."

```bash
# Reinstale dependências
pip install -r requirements.txt
```

### "NVIDIA_API_KEY not found"

```bash
# Verifique se config/.env existe
ls -la config/.env

# Se não, copie o template
cp config/.env.example config/.env
```

### "Telegram Bot não responde"

1. Verifique `TELEGRAM_BOT_TOKEN` é válido
2. Verifique seu `TELEGRAM_ALLOWED_USERS` está correto
3. Veja logs: `python -m src 2>&1 | grep -i telegram`

### "AttributeError: '_build_search_queries'"

```bash
# Você está com código antigo. Update:
git pull origin main
python setup.py
```

---

## 🚀 Deployment em Produção

### Via Docker (Recomendado)

```bash
# Usar docker-compose
docker-compose -f docker-compose.yml up -d

# Com Ollama local (GPU)
# Descomente as seções GPU no docker-compose.yml
```

### Systemd Service (Linux)

Crie `/etc/systemd/system/seeker-bot.service`:

```ini
[Unit]
Description=Seeker.Bot Autonomous Agent
After=network.target

[Service]
Type=simple
User=seeker
WorkingDirectory=/opt/Seeker.Bot
ExecStart=/usr/bin/python3 -m src
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Inicie:

```bash
sudo systemctl daemon-reload
sudo systemctl enable seeker-bot
sudo systemctl start seeker-bot
sudo journalctl -u seeker-bot -f
```

---

## 📚 Próximos Passos

1. **Explorar Skills**
   ```
   /status      — Ver status de todos os 10 goals
   /saude       — Dashboard detalhado
   ```

2. **Configurar Interesses**
   ```
   /configure_news   — Setup SenseNews (notícias personalizadas)
   ```

3. **Usar Scout Hunter**
   ```
   /scout   — Prospectação B2B automatizada
   ```

4. **Ler Documentação**
   - [GitHub Repo](https://github.com/4pixeltechBR/Seeker.Bot)
   - [Issues & Roadmap](https://github.com/4pixeltechBR/Seeker.Bot/issues)

---

## 🔗 Links Úteis

| Recurso | Link |
|---------|------|
| Repo | https://github.com/4pixeltechBR/Seeker.Bot |
| Issues | https://github.com/4pixeltechBR/Seeker.Bot/issues |
| Telegram Bot | @SeekerBR1_bot |
| NVIDIA NIM | https://build.nvidia.com/ |
| Gemini API | https://aistudio.google.com |
| Groq Console | https://console.groq.com |

---

## 📝 Changelog

**Sprint 6 — UX/Installation (2026-04-09)**
- ✅ Setup wizard interativo melhorado
- ✅ Docker & docker-compose para deployment
- ✅ Melhor validação de pré-requisitos
- ✅ Guide de troubleshooting

---

# English

## 🚀 Quick Installation

### 1️⃣ Clone Repository

```bash
git clone https://github.com/4pixeltechBR/Seeker.Bot.git
cd Seeker.Bot
```

### 2️⃣ Run Setup

```bash
python setup.py
```

### 3️⃣ Start Bot

```bash
python -m src
```

### 4️⃣ Use on Telegram

Search for **@SeekerBR1_bot** and send `/start`

---

## 🐳 Docker Deployment

```bash
# Configure environment
cp config/.env.example config/.env
# Edit config/.env with your API keys

# Start services
docker-compose up -d

# View logs
docker-compose logs -f seeker-bot
```

---

## Requirements

- **Python 3.10+**
- **Git**
- At least 2 of these LLM providers:
  - NVIDIA NIM (Free, 40 RPM)
  - Google Gemini (Free tier available)
  - Groq (Free, 30 RPM)

---

For full documentation in Portuguese, see [Português](#pré-requisitos) section above.

**Happy researching! 🤖**
