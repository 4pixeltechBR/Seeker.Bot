# ⚡ Configuração Rápida do GitHub (5 minutos)

Seu repositório está em: https://github.com/4pixeltechBR/Seeker.Bot

## ✅ Já Feito (Automático)
- ✅ Código publicado
- ✅ GitHub Actions (CI/CD) criado
- ✅ Documentação completa
- ✅ LICENSE (MIT) adicionado

## 🔧 O QUE VOCÊ PRECISA FAZER AGORA

### **Opção 1: Automático (Recomendado)** ⚡

Se você tiver um GitHub token:

```bash
# Instale requests (se não tiver)
pip install requests

# Gere um token em: https://github.com/settings/tokens/new
# Selecione: repo, admin:repo_hook, admin:org_hook
# Copie o token e execute:

python scripts/setup_github_repo.py seu_token 4pixeltechBR Seeker.Bot
```

Pronto! Tudo configurado automaticamente ✨

---

### **Opção 2: Manual** (Sem token)

Se não tiver token ou preferir fazer manualmente, abra:
https://github.com/4pixeltechBR/Seeker.Bot/settings

E siga estas 3 coisas:

#### **1️⃣ Ativar Discussions e Projects**
- Desça a página até **Features**
- ✅ Marque: Discussions, Issues, Projects
- **Save**

#### **2️⃣ Proteger a Branch Main** (Muito Importante!)
- Menu esquerdo: **Branches**
- Clique: **Add rule**
- Branch pattern: `main`
- Ative:
  - ✅ Require a pull request before merging
  - ✅ Require status checks to pass
    - Procure por "tests"
  - ✅ Require branches to be up to date
  - ✅ Include administrators
- **Create**

#### **3️⃣ Segurança** (Opcional mas bom)
- Menu esquerdo: **Code security and analysis**
- ✅ Dependabot alerts
- ✅ Secret scanning

---

## ✨ Resultado Final

Quando terminar, você terá:

```
🚀 GitHub Repository: https://github.com/4pixeltechBR/Seeker.Bot
├── ✅ CI/CD automático (testes em cada push)
├── ✅ Branch protegida (requer PR + testes passando)
├── ✅ Secret scanning (avisa se API key for feita push)
├── ✅ Discussions (comunidade sugerir features)
├── ✅ Projects (roadmap visual)
└── ✅ Documentação completa
```

---

## 📊 Badges para o README (Copie)

Depois de tudo pronto, adicione ao topo do README.md:

```markdown
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://github.com/4pixeltechBR/Seeker.Bot/actions/workflows/tests.yml/badge.svg)](https://github.com/4pixeltechBR/Seeker.Bot/actions)
```

---

## 🎉 Pronto!

Seu repositório está profissional e pronto para receber contribuições!

**Próximos passos:**
1. Avise seus amigos: `https://github.com/4pixeltechBR/Seeker.Bot`
2. Adicione ao seu portfólio/CV
3. Aguarde PRs e feedback da comunidade 🚀
