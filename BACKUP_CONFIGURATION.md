# ⚠️ CONFIGURAÇÃO CRÍTICA: AUTO-BACKUP DO SEEKER

## 🚨 PROBLEMA IDENTIFICADO

O Git Auto-Backup do Seeker está **DESCONFIGURADO**. A variável `GITHUB_REPO` está **VAZIA**, o que causa:

```
❌ CENÁRIO PERIGOSO (ATUAL):
   git_automation (a cada 6 horas)
   → GITHUB_REPO = "" (vazio)
   → Fallback: usa "origin"
   → origin = Seeker.Bot (PÚBLICO!)
   → Auto-backup vai para repositório PÚBLICO (RISCO!)
```

## ✅ SOLUÇÃO

Configure o `.env` para fazer backup APENAS em Seeker.ai (privado):

```bash
# Copie do template
cp .env.local.template .env

# Edite .env com seu GitHub token
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxx  # Token do GitHub
GITHUB_REPO=4pixeltechBR/Seeker.ai  # SEMPRE Seeker.ai (privado)
```

## 📋 Como Funciona

### Estrutura de Remotes

```
Seeker.Bot (local)
├── origin → https://github.com/4pixeltechBR/Seeker.Bot.git (PÚBLICO)
│           ↑ Código limpo, sem dados privados
│           ↑ Desenvolvido via PRs
│
└── (implicit via GITHUB_REPO env var)
    └── https://github.com/4pixeltechBR/Seeker.ai.git (PRIVADO)
        ↑ Auto-backup automático (a cada 6 horas)
        ↑ Dados sensíveis, snapshots
```

### Fluxo de Auto-Backup

```
1. git_automation executa (cron: a cada 6 horas)
   ├─ git status -u --short
   ├─ git add .
   ├─ LLM gera commit message
   ├─ git commit -m "msg"
   ├─ Se GITHUB_TOKEN está set:
   │  ├─ Constrói URL: https://x-access-token:{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git
   │  ├─ git push {GITHUB_REPO}
   │  └─ ✅ Envia para Seeker.ai (privado)
   └─ Se GITHUB_TOKEN vazio:
      ├─ Fallback: git push -u origin main
      └─ ❌ Envia para Seeker.Bot (PÚBLICO!) — PROBLEMA!
```

## 🔐 Configuração Recomendada

### 1. Criar Token GitHub

1. Vá para: https://github.com/settings/tokens/new
2. Nome: `Seeker-Backup`
3. Escopos:
   - ✅ `repo` (acesso a repositórios)
   - ✅ `admin:repo_hook` (webhooks)
4. Copie o token

### 2. Configurar `.env`

```env
# Único token necessário (apenas para backup automático)
GITHUB_TOKEN=ghp_seu_token_aqui

# Única configuração necessária (sempre Seeker.ai!)
GITHUB_REPO=4pixeltechBR/Seeker.ai
```

### 3. Verificar Configuração

```bash
# Confirmar variáveis
echo $GITHUB_TOKEN
echo $GITHUB_REPO

# Deve retornar:
# ghp_xxxxx...
# 4pixeltechBR/Seeker.ai
```

## ✅ Checklist de Segurança

| Item | Status | Descrição |
|------|--------|-----------|
| GITHUB_REPO definido | [ ] | Deve estar configurado como `4pixeltechBR/Seeker.ai` |
| GITHUB_TOKEN válido | [ ] | Token gerado e com escopos corretos |
| Seeker.Bot origin | ✅ | origin aponta para Seeker.Bot (público) |
| Seeker.ai backup | ✅ | Configurado via env var (privado) |
| .env em .gitignore | ✅ | `.env` nunca faz push ao GitHub |
| Token não exposto | ✅ | Token passado via env var, não em .git/config |

## 🚫 O QUE NÃO FAZER

```bash
# ❌ NUNCA faça isso:
git remote add backup https://github.com/4pixeltechBR/Seeker.ai.git
git remote set-url origin https://github.com/4pixeltechBR/Seeker.ai.git

# ❌ NUNCA coloque token em .git/config:
git config --global --add credential.helper store
# Isso expõe o token em ~/.git-credentials

# ❌ NUNCA configure Seeker.Bot como repo de backup:
GITHUB_REPO=4pixeltechBR/Seeker.Bot  # ERRADO!
```

## ✅ O QUE FAZER

```bash
# ✅ Configure APENAS via .env:
GITHUB_TOKEN=ghp_xxxxx
GITHUB_REPO=4pixeltechBR/Seeker.ai

# ✅ Script de git_automation usa env vars (seguro)
# Token não persiste em .git/config
# URL construída dinamicamente em tempo de execução
```

## 📊 Estado Atual vs Esperado

```
┌──────────────────────────────────────┬──────────────────────────────────────┐
│ ESTADO ATUAL (PERIGOSO)              │ ESTADO ESPERADO (SEGURO)             │
├──────────────────────────────────────┼──────────────────────────────────────┤
│ GITHUB_REPO = ""                     │ GITHUB_REPO = "4pixeltechBR/Se...ai" │
│ GITHUB_TOKEN = "" (não definido)     │ GITHUB_TOKEN = "ghp_xxxxx..."        │
│                                      │                                      │
│ git push → origin (Seeker.Bot)       │ git push → Seeker.ai (privado)       │
│ ❌ Auto-backup em repositório público│ ✅ Auto-backup em repositório privado│
│                                      │                                      │
│ RISCO: Dados sensíveis em público!   │ SEGURO: Dados isolados               │
└──────────────────────────────────────┴──────────────────────────────────────┘
```

## 🔧 Próximas Ações

1. **Imediatamente**:
   - [ ] Copie `.env.local.template` para `.env`
   - [ ] Adicione seu GITHUB_TOKEN para Seeker.ai
   - [ ] Configure GITHUB_REPO=4pixeltechBR/Seeker.ai

2. **Verificação**:
   ```bash
   source .env  # ou no Windows: type .env
   echo "GITHUB_REPO=$GITHUB_REPO"
   # Deve mostrar: GITHUB_REPO=4pixeltechBR/Seeker.ai
   ```

3. **Teste** (próximo ciclo de 6 horas):
   - Verifique logs do Telegram
   - Confirme que backup foi para Seeker.ai (não Seeker.Bot)

---

**Data**: 2026-04-08  
**Status**: 🔴 CRÍTICO — Requer configuração imediata  
**Impacto**: Auto-backup pode expor dados privados em repositório público
