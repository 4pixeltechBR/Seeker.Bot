#!/usr/bin/env python3
"""
Seeker.Bot — API Key Validation Suite
Tests all configured API keys for validity and access
"""

import os
import sys
from dotenv import load_dotenv

# Load .env
load_dotenv()

print("=" * 70)
print("SEEKER.BOT — API KEY VALIDATION SUITE")
print("=" * 70)
print()

tests = {}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. TELEGRAM
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

print("1️⃣  TELEGRAM BOT")
try:
    import httpx
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("   ❌ TELEGRAM_BOT_TOKEN não configurado")
        tests["TELEGRAM"] = "❌"
    else:
        print(f"   ✓ Token encontrado: {token[:20]}...")
        resp = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ok"):
                bot_info = data["result"]
                print(f"   ✅ VÁLIDO — Bot: @{bot_info.get('username')} (ID: {bot_info.get('id')})")
                tests["TELEGRAM"] = "✅"
            else:
                print(f"   ❌ Erro: {data.get('description')}")
                tests["TELEGRAM"] = "❌"
        else:
            print(f"   ❌ HTTP {resp.status_code}")
            tests["TELEGRAM"] = "❌"
except Exception as e:
    print(f"   ❌ Erro: {e}")
    tests["TELEGRAM"] = "❌"

print()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. GEMINI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

print("2️⃣  GOOGLE GEMINI (embeddings + vision fallback)")
try:
    import google.generativeai as genai
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        print("   ❌ GEMINI_API_KEY não configurado")
        tests["GEMINI"] = "❌"
    else:
        print(f"   ✓ Key encontrada: {key[:20]}...")
        genai.configure(api_key=key)
        models = list(genai.list_models())
        if models:
            print(f"   ✅ VÁLIDO — {len(models)} modelos disponíveis")
            print(f"      Modelos: {', '.join([m.name.split('/')[-1] for m in models[:3]])}")
            tests["GEMINI"] = "✅"
        else:
            print("   ❌ Sem modelos disponíveis")
            tests["GEMINI"] = "❌"
except Exception as e:
    print(f"   ❌ Erro: {e}")
    tests["GEMINI"] = "❌"

print()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. GROQ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

print("3️⃣  GROQ (fast LLM)")
try:
    from groq import Groq
    key = os.getenv("GROQ_API_KEY")
    if not key:
        print("   ❌ GROQ_API_KEY não configurado")
        tests["GROQ"] = "❌"
    else:
        print(f"   ✓ Key encontrada: {key[:20]}...")
        client = Groq(api_key=key)
        models = client.models.list()
        if models.data:
            print(f"   ✅ VÁLIDO — {len(models.data)} modelos disponíveis")
            print(f"      Modelos: {', '.join([m.id for m in models.data[:3]])}")
            tests["GROQ"] = "✅"
        else:
            print("   ❌ Sem modelos disponíveis")
            tests["GROQ"] = "❌"
except Exception as e:
    print(f"   ❌ Erro: {e}")
    tests["GROQ"] = "❌"

print()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. NVIDIA NIM
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

print("4️⃣  NVIDIA NIM (high-quality LLM)")
try:
    from openai import OpenAI
    key = os.getenv("NVIDIA_NIM_API_KEY")
    if not key:
        print("   ❌ NVIDIA_NIM_API_KEY não configurado")
        tests["NVIDIA_NIM"] = "❌"
    else:
        print(f"   ✓ Key encontrada: {key[:20]}...")
        client = OpenAI(
            api_key=key,
            base_url="https://integrate.api.nvidia.com/v1"
        )
        models = client.models.list()
        if models.data:
            print(f"   ✅ VÁLIDO — {len(models.data)} modelos disponíveis")
            print(f"      Modelos: {', '.join([m.id for m in models.data[:3]])}")
            tests["NVIDIA_NIM"] = "✅"
        else:
            print("   ❌ Sem modelos disponíveis")
            tests["NVIDIA_NIM"] = "❌"
except Exception as e:
    print(f"   ❌ Erro: {e}")
    tests["NVIDIA_NIM"] = "❌"

print()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. DEEPSEEK
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

print("5️⃣  DEEPSEEK (high accuracy LLM)")
try:
    from openai import OpenAI
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        print("   ❌ DEEPSEEK_API_KEY não configurado")
        tests["DEEPSEEK"] = "❌"
    else:
        print(f"   ✓ Key encontrada: {key[:20]}...")
        client = OpenAI(api_key=key, base_url="https://api.deepseek.com")
        models = client.models.list()
        if models.data:
            print(f"   ✅ VÁLIDO — {len(models.data)} modelos disponíveis")
            print(f"      Modelos: {', '.join([m.id for m in models.data[:3]])}")
            tests["DEEPSEEK"] = "✅"
        else:
            print("   ❌ Sem modelos disponíveis")
            tests["DEEPSEEK"] = "❌"
except Exception as e:
    print(f"   ❌ Erro: {e}")
    tests["DEEPSEEK"] = "❌"

print()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 6. MISTRAL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

print("6️⃣  MISTRAL (open-source LLM)")
try:
    import httpx
    key = os.getenv("MISTRAL_API_KEY")
    if not key:
        print("   ❌ MISTRAL_API_KEY não configurado")
        tests["MISTRAL"] = "❌"
    else:
        print(f"   ✓ Key encontrada: {key[:20]}...")
        headers = {"Authorization": f"Bearer {key}"}
        resp = httpx.get("https://api.mistral.ai/v1/models", headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            models = data.get("data", [])
            if models:
                print(f"   ✅ VÁLIDO — {len(models)} modelos disponíveis")
                print(f"      Modelos: {', '.join([m['id'] for m in models[:3]])}")
                tests["MISTRAL"] = "✅"
            else:
                print("   ❌ Sem modelos disponíveis")
                tests["MISTRAL"] = "❌"
        else:
            print(f"   ❌ HTTP {resp.status_code}")
            tests["MISTRAL"] = "❌"
except Exception as e:
    print(f"   ❌ Erro: {e}")
    tests["MISTRAL"] = "❌"

print()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 7. TAVILY SEARCH
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

print("7️⃣  TAVILY SEARCH (web search API)")
try:
    import httpx
    key = os.getenv("TAVILY_API_KEY")
    if not key:
        print("   ❌ TAVILY_API_KEY não configurado")
        tests["TAVILY"] = "❌"
    else:
        print(f"   ✓ Key encontrada: {key[:20]}...")
        payload = {"api_key": key, "query": "test"}
        resp = httpx.post("https://api.tavily.com/search", json=payload, timeout=5)
        if resp.status_code == 200:
            print(f"   ✅ VÁLIDO")
            tests["TAVILY"] = "✅"
        else:
            print(f"   ❌ HTTP {resp.status_code}")
            tests["TAVILY"] = "❌"
except Exception as e:
    print(f"   ❌ Erro: {e}")
    tests["TAVILY"] = "❌"

print()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 8. BRAVE SEARCH
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

print("8️⃣  BRAVE SEARCH (web search API)")
try:
    import httpx
    key = os.getenv("BRAVE_API_KEY")
    if not key:
        print("   ❌ BRAVE_API_KEY não configurado")
        tests["BRAVE"] = "❌"
    else:
        print(f"   ✓ Key encontrada: {key[:20]}...")
        headers = {"Accept": "application/json", "X-Subscription-Token": key}
        resp = httpx.get("https://api.search.brave.com/res/v1/web/search?q=test", headers=headers, timeout=5)
        if resp.status_code == 200:
            print(f"   ✅ VÁLIDO")
            tests["BRAVE"] = "✅"
        else:
            print(f"   ❌ HTTP {resp.status_code}")
            tests["BRAVE"] = "❌"
except Exception as e:
    print(f"   ❌ Erro: {e}")
    tests["BRAVE"] = "❌"

print()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 9. GMAIL SMTP/IMAP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

print("9️⃣  GMAIL (SMTP/IMAP)")
try:
    import imaplib
    user = os.getenv("IMAP_USER")
    password = os.getenv("IMAP_PASSWORD")
    if not user or not password:
        print("   ❌ IMAP_USER ou IMAP_PASSWORD não configurado")
        tests["GMAIL"] = "❌"
    else:
        print(f"   ✓ Credenciais encontradas: {user}")
        imap = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        status, _ = imap.login(user, password)
        if status == "OK":
            print(f"   ✅ VÁLIDO — Autenticação IMAP bem-sucedida")
            try:
                imap.close()
            except:
                pass  # Ignore close errors
            tests["GMAIL"] = "✅"
        else:
            print("   ❌ Falha na autenticação IMAP")
            tests["GMAIL"] = "❌"
except Exception as e:
    print(f"   ❌ Erro: {e}")
    tests["GMAIL"] = "❌"

print()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 10. GITHUB
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

print("🔟 GITHUB (auto-backup token)")
try:
    import httpx
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        print("   ❌ GITHUB_TOKEN não configurado")
        tests["GITHUB"] = "❌"
    else:
        print(f"   ✓ Token encontrado: {token[:20]}...")
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"}
        resp = httpx.get("https://api.github.com/user", headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            print(f"   ✅ VÁLIDO — User: {data.get('login')} (ID: {data.get('id')})")
            tests["GITHUB"] = "✅"
        else:
            print(f"   ❌ HTTP {resp.status_code}")
            tests["GITHUB"] = "❌"
except Exception as e:
    print(f"   ❌ Erro: {e}")
    tests["GITHUB"] = "❌"

print()
print("=" * 70)
print("RESUMO")
print("=" * 70)

passed = sum(1 for v in tests.values() if v == "✅")
total = len(tests)

for api, status in sorted(tests.items()):
    print(f"{status} {api}")

print()
print(f"Total: {passed}/{total} válidos")

if passed == total:
    print("🎉 TODAS AS CHAVES VÁLIDAS!")
    sys.exit(0)
else:
    print(f"⚠️  {total - passed} chave(s) com problema")
    sys.exit(1)
