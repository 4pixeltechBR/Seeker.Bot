#!/usr/bin/env python3
"""
Seeker.Bot Interactive Setup
Instalador bilíngue (Português/English) com configuração automática e validação.
"""

import os
import sys
import subprocess
import json
import shutil
import sqlite3
from pathlib import Path
from packaging import version


def clear_screen():
    """Limpa a tela do terminal."""
    os.system("cls" if os.name == "nt" else "clear")


def check_prerequisites(lang):
    """Verifica pré-requisitos do sistema."""
    clear_screen()
    if lang == "pt_BR":
        print("=" * 60)
        print("🔍 Verificando pré-requisitos...")
        print("=" * 60)
        print()
    else:
        print("=" * 60)
        print("🔍 Checking prerequisites...")
        print("=" * 60)
        print()

    # Check Python version
    py_version = sys.version_info
    if py_version < (3, 10):
        if lang == "pt_BR":
            print(f"❌ Python 3.10+ obrigatório (você tem {py_version.major}.{py_version.minor})")
        else:
            print(f"❌ Python 3.10+ required (you have {py_version.major}.{py_version.minor})")
        sys.exit(1)
    if lang == "pt_BR":
        print(f"✅ Python {py_version.major}.{py_version.minor}.{py_version.micro}")
    else:
        print(f"✅ Python {py_version.major}.{py_version.minor}.{py_version.micro}")

    # Check Git
    try:
        result = subprocess.run(['git', '--version'], capture_output=True, text=True, check=True)
        if lang == "pt_BR":
            print(f"✅ {result.stdout.strip()}")
        else:
            print(f"✅ {result.stdout.strip()}")
    except:
        if lang == "pt_BR":
            print("❌ Git não encontrado. Instale em https://git-scm.com/")
        else:
            print("❌ Git not found. Install from https://git-scm.com/")
        sys.exit(1)

    print()


def get_language():
    """Pergunta ao usuário qual idioma usar."""
    clear_screen()
    print("=" * 60)
    print("Seeker.Bot Setup")
    print("=" * 60)
    print()
    print("Choose language / Escolha o idioma:")
    print()
    print("[1] Português (Brasil)")
    print("[2] English")
    print()
    choice = input("> ").strip()
    return "pt_BR" if choice == "1" else "en_US"


def show_welcome(lang):
    """Exibe mensagem de boas-vindas."""
    clear_screen()
    if lang == "pt_BR":
        print("=" * 60)
        print("🤖 Bem-vindo ao Seeker.Bot!")
        print("=" * 60)
        print()
        print("Seeker.Bot é um agente autônomo de pesquisa com:")
        print("  ✓ Raciocínio estruturado em 3 camadas")
        print("  ✓ Memória semântica persistente")
        print("  ✓ Multi-provider LLM com fallback automático")
        print("  ✓ Skills dinâmicas criáveis via chat")
        print()
        print("Este instalador irá:")
        print("  1. Instalar dependências (pip)")
        print("  2. Configurar variáveis de ambiente (.env)")
        print("  3. Criar banco de dados inicial")
        print("  4. Testar conectividade com providers")
        print()
    else:
        print("=" * 60)
        print("🤖 Welcome to Seeker.Bot!")
        print("=" * 60)
        print()
        print("Seeker.Bot is an autonomous research agent with:")
        print("  ✓ Structured 3-layer reasoning")
        print("  ✓ Persistent semantic memory")
        print("  ✓ Multi-provider LLM with automatic fallback")
        print("  ✓ Dynamic skills creatable via chat")
        print()
        print("This installer will:")
        print("  1. Install dependencies (pip)")
        print("  2. Configure environment variables (.env)")
        print("  3. Create initial database")
        print("  4. Test provider connectivity")
        print()

    input("Press Enter to continue / Pressione Enter para continuar...")


def get_api_keys(lang):
    """Coleta as API keys do usuário."""
    clear_screen()
    keys = {}

    if lang == "pt_BR":
        print("=" * 60)
        print("🔑 Configurar API Keys")
        print("=" * 60)
        print()
        print("Cole suas API keys. Use Enter para pular (padrões serão usados).")
        print()
    else:
        print("=" * 60)
        print("🔑 Configure API Keys")
        print("=" * 60)
        print()
        print("Paste your API keys. Press Enter to skip (defaults will be used).")
        print()

    prompts = {
        "pt_BR": {
            "nvidia": ("NVIDIA NIM API Key (https://build.nvidia.com): ", True),
            "groq": ("Groq API Key (https://console.groq.com): ", True),
            "gemini": ("Google Gemini API Key (https://aistudio.google.com): ", True),
            "deepseek": ("DeepSeek API Key (https://platform.deepseek.com): ", False),
            "mistral": ("Mistral API Key (https://console.mistral.ai): ", False),
            "tavily": ("Tavily Search API Key (https://tavily.com): ", False),
            "telegram": ("Telegram Bot Token (@BotFather): ", True),
            "telegram_user": ("Your Telegram User ID: ", True),
            "github_token": ("GitHub Token (for auto-backup): ", False),
            "github_repo": ("GitHub Repo (owner/repo): ", False),
        },
        "en_US": {
            "nvidia": ("NVIDIA NIM API Key (https://build.nvidia.com): ", True),
            "groq": ("Groq API Key (https://console.groq.com): ", True),
            "gemini": ("Google Gemini API Key (https://aistudio.google.com): ", True),
            "deepseek": ("DeepSeek API Key (https://platform.deepseek.com): ", False),
            "mistral": ("Mistral API Key (https://console.mistral.ai): ", False),
            "tavily": ("Tavily Search API Key (https://tavily.com): ", False),
            "telegram": ("Telegram Bot Token (@BotFather): ", True),
            "telegram_user": ("Your Telegram User ID: ", True),
            "github_token": ("GitHub Token (for auto-backup): ", False),
            "github_repo": ("GitHub Repo (owner/repo): ", False),
        }
    }

    for key_name, (prompt_text, is_required) in prompts[lang].items():
        while True:
            value = input(prompt_text).strip()
            if is_required and not value:
                if lang == "pt_BR":
                    print(f"  ⚠️  {key_name} é obrigatório!")
                else:
                    print(f"  ⚠️  {key_name} is required!")
                continue
            if value:
                keys[key_name] = value
            break

    return keys


def create_env_file(lang, keys):
    """Cria arquivo .env com configurações em config/.env"""
    config_dir = Path("config")
    config_dir.mkdir(exist_ok=True)

    env_path = config_dir / ".env"

    if env_path.exists():
        if lang == "pt_BR":
            print(f"⚠️  {env_path} já existe. Atualizando...")
        else:
            print(f"⚠️  {env_path} already exists. Updating...")

    env_content = f"""# Seeker.Bot — Configuration
# Auto-generated by setup.py

# ── Providers ──
NVIDIA_API_KEY={keys.get('nvidia', '')}
GROQ_API_KEY={keys.get('groq', '')}
GEMINI_API_KEY={keys.get('gemini', '')}
DEEPSEEK_API_KEY={keys.get('deepseek', '')}
MISTRAL_API_KEY={keys.get('mistral', '')}

# ── Search ──
SEARCH_PROVIDER=tavily
TAVILY_API_KEY={keys.get('tavily', '')}
BRAVE_API_KEY=

# ── Telegram ──
TELEGRAM_BOT_TOKEN={keys.get('telegram', '')}
TELEGRAM_ALLOWED_USERS={keys.get('telegram_user', '')}

# ── Email (Gmail) ──
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
EMAIL_RECIPIENTS=
IMAP_SERVER=imap.gmail.com
IMAP_USER=
IMAP_PASSWORD=

# ── GitHub Auto-Backup ──
GITHUB_TOKEN={keys.get('github_token', '')}
GITHUB_REPO={keys.get('github_repo', '')}

# ── System ──
LOG_LEVEL=INFO
"""

    try:
        with open(env_path, "w") as f:
            f.write(env_content)

        if lang == "pt_BR":
            print(f"✅ Configuração salva em {env_path}")
        else:
            print(f"✅ Configuration saved to {env_path}")

        return True
    except Exception as e:
        if lang == "pt_BR":
            print(f"❌ Erro ao salvar .env: {e}")
        else:
            print(f"❌ Error saving .env: {e}")
        return False


def create_directories(lang):
    """Cria diretórios necessários."""
    dirs = [
        Path("data"),
        Path("logs"),
        Path("config"),
        Path("cache"),
    ]

    for dir_path in dirs:
        try:
            dir_path.mkdir(exist_ok=True)
        except Exception as e:
            if lang == "pt_BR":
                print(f"⚠️  Erro ao criar {dir_path}: {e}")
            else:
                print(f"⚠️  Error creating {dir_path}: {e}")


def init_database(lang):
    """Inicializa banco de dados SQLite."""
    db_path = Path("data") / "seeker_memory.db"

    if db_path.exists():
        if lang == "pt_BR":
            print(f"✅ Database já existe em {db_path}")
        else:
            print(f"✅ Database already exists at {db_path}")
        return

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Cria tabela simples para testar
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_status (
                id INTEGER PRIMARY KEY,
                initialized_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("INSERT INTO system_status DEFAULT VALUES")
        conn.commit()
        conn.close()

        if lang == "pt_BR":
            print(f"✅ Database criado em {db_path}")
        else:
            print(f"✅ Database created at {db_path}")
    except Exception as e:
        if lang == "pt_BR":
            print(f"❌ Erro ao inicializar database: {e}")
        else:
            print(f"❌ Error initializing database: {e}")


def install_dependencies(lang):
    """Instala dependências via pip."""
    clear_screen()

    if lang == "pt_BR":
        print("=" * 60)
        print("📦 Instalando dependências...")
        print("=" * 60)
        print()
    else:
        print("=" * 60)
        print("📦 Installing dependencies...")
        print("=" * 60)
        print()

    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-q", "-e", "."],
            cwd=Path(__file__).parent
        )

        if lang == "pt_BR":
            print("✅ Dependências instaladas com sucesso!")
        else:
            print("✅ Dependencies installed successfully!")

        input("Press Enter to continue / Pressione Enter para continuar...")

    except subprocess.CalledProcessError as e:
        if lang == "pt_BR":
            print(f"❌ Erro ao instalar dependências: {e}")
        else:
            print(f"❌ Error installing dependencies: {e}")
        sys.exit(1)


def test_providers(lang, keys):
    """Testa conectividade com os providers."""
    clear_screen()

    if lang == "pt_BR":
        print("=" * 60)
        print("🧪 Testando providers...")
        print("=" * 60)
        print()
    else:
        print("=" * 60)
        print("🧪 Testing providers...")
        print("=" * 60)
        print()

    providers_ok = 0
    providers_total = 3

    # Test Groq
    if keys.get("groq"):
        try:
            import httpx
            client = httpx.Client()
            resp = client.get("https://api.groq.com/api/health")
            if resp.status_code == 200:
                if lang == "pt_BR":
                    print("✅ Groq: OK")
                else:
                    print("✅ Groq: OK")
                providers_ok += 1
        except:
            if lang == "pt_BR":
                print("❌ Groq: Falha na conexão")
            else:
                print("❌ Groq: Connection failed")
    else:
        if lang == "pt_BR":
            print("⏭  Groq: Não configurado")
        else:
            print("⏭  Groq: Not configured")

    # Test Gemini
    if keys.get("gemini"):
        try:
            import httpx
            client = httpx.Client()
            resp = client.post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent",
                headers={"x-goog-api-key": keys["gemini"]},
                json={"contents": [{"parts": [{"text": "test"}]}]}
            )
            if resp.status_code in [200, 400]:  # 400 OK se key é válida mas request é inválido
                if lang == "pt_BR":
                    print("✅ Gemini: OK")
                else:
                    print("✅ Gemini: OK")
                providers_ok += 1
        except:
            if lang == "pt_BR":
                print("❌ Gemini: Falha na conexão")
            else:
                print("❌ Gemini: Connection failed")
    else:
        if lang == "pt_BR":
            print("⏭  Gemini: Não configurado")
        else:
            print("⏭  Gemini: Not configured")

    # Test Ollama (local)
    try:
        import httpx
        client = httpx.Client()
        resp = client.get("http://localhost:11434/api/tags")
        if resp.status_code == 200:
            if lang == "pt_BR":
                print("✅ Ollama (local): OK")
            else:
                print("✅ Ollama (local): OK")
            providers_ok += 1
    except:
        if lang == "pt_BR":
            print("⚠️  Ollama (local): Não disponível (opcional)")
        else:
            print("⚠️  Ollama (local): Not available (optional)")

    print()
    if lang == "pt_BR":
        print(f"Resultado: {providers_ok}/{providers_total} providers ativos")
        print()
        if providers_ok == 0:
            print("⚠️  Nenhum provider configurado. Configure API keys para usar o Bot.")
    else:
        print(f"Result: {providers_ok}/{providers_total} providers active")
        print()
        if providers_ok == 0:
            print("⚠️  No providers configured. Configure API keys to use the Bot.")

    input("Press Enter to continue / Pressione Enter para continuar...")


def show_summary(lang, keys):
    """Exibe resumo da configuração."""
    clear_screen()

    if lang == "pt_BR":
        print("=" * 60)
        print("✅ Setup Completo!")
        print("=" * 60)
        print()
        print("Próximos passos:")
        print("  1. Inicie o bot: python -m src")
        print("  2. Envie /start no Telegram")
        print("  3. Configure seus interesses (/configure_news)")
        print()
        print("Documentação: https://github.com/4pixeltech/Seeker.Bot")
        print()
    else:
        print("=" * 60)
        print("✅ Setup Complete!")
        print("=" * 60)
        print()
        print("Next steps:")
        print("  1. Start the bot: python -m src")
        print("  2. Send /start on Telegram")
        print("  3. Configure your interests (/configure_news)")
        print()
        print("Documentation: https://github.com/4pixeltech/Seeker.Bot")
        print()


def main():
    """Função principal."""
    lang = get_language()
    show_welcome(lang)

    # Check prerequisites
    check_prerequisites(lang)

    # Create directories
    if lang == "pt_BR":
        print("📁 Criando diretórios...")
    else:
        print("📁 Creating directories...")
    create_directories(lang)
    print()

    # Get API keys
    keys = get_api_keys(lang)

    # Create .env file
    if lang == "pt_BR":
        print("\n💾 Salvando configuração...")
    else:
        print("\n💾 Saving configuration...")
    if not create_env_file(lang, keys):
        sys.exit(1)

    # Install dependencies
    install_dependencies(lang)

    # Initialize database
    if lang == "pt_BR":
        print("🗄️  Inicializando database...")
    else:
        print("🗄️  Initializing database...")
    init_database(lang)
    print()

    # Test providers
    test_providers(lang, keys)

    # Show summary
    show_summary(lang, keys)

    input("Press Enter to continue / Pressione Enter para continuar...")

    if lang == "pt_BR":
        print("\nObrigado por usar Seeker.Bot! 🚀")
    else:
        print("\nThank you for using Seeker.Bot! 🚀")


if __name__ == "__main__":
    main()
