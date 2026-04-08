# Configuração do GitHub Repository

Este arquivo descreve como configurar seu repositório Seeker.Bot no GitHub.

## ✅ Já Feito Automaticamente

- ✅ Código foi feito push para `main` branch
- ✅ GitHub Actions (CI/CD) foi configurado em `.github/workflows/tests.yml`
- ✅ LICENSE (MIT) foi adicionado
- ✅ .env.example e CONTRIBUTING.md foram adicionados

## 🔧 Próximos Passos (Configure Manualmente)

Abra https://github.com/4pixeltechBR/Seeker.Bot/settings

### 1. **Branches → Add Rule** (Proteção)

1. Clique em **Branches** (no menu esquerdo)
2. Clique em **Add rule**
3. **Branch name pattern**: `main`
4. Ative as opções:
   - ✅ Require a pull request before merging
   - ✅ Require status checks to pass before merging
     - Procure por "tests" quando aparecer
   - ✅ Require branches to be up to date before merging
   - ✅ Include administrators

### 2. **General → Features** (Habilitar Discussions)

1. Clique em **General** (menu esquerdo)
2. Desça até **Features**
3. ✅ Discussions: Ativar
4. ✅ Issues: Ativar
5. ✅ Projects: Ativar

### 3. **Code security and analysis**

1. Clique em **Code security and analysis** (menu esquerdo)
2. ✅ Dependabot alerts: Ativar (avisa quando há vulnerabilidades em dependências)
3. ✅ Dependabot security updates: Ativar
4. ✅ Secret scanning: Ativar (avisa se alguém faz push de API keys por acaso)

### 4. **Criar um Projects Board** (opcional mas recomendado)

1. Clique na aba **Projects**
2. Clique em **New project**
3. **Project name**: Roadmap ou v2.1
4. **Template**: Table ou Board
5. Adicione issues relacionadas ao roadmap

### 5. **Discussions Setup** (Categorias)

1. Clique na aba **Discussions**
2. Clique em **Settings**
3. Crie categorias (se quiser):
   - 🎯 Features Requests
   - 🐛 Troubleshooting
   - 💡 Ideas
   - 📢 Announcements

---

## 🤖 Configuração via GitHub CLI (mais rápido)

Se você tem `gh` instalado (https://cli.github.com/):

```bash
# Fazer login
gh auth login

# Criar branch protection para main
gh api repos/4pixeltechBR/Seeker.Bot/branches/main/protection \
  -X PUT \
  -f required_status_checks='{"strict":true,"contexts":["tests"]}' \
  -f required_pull_request_reviews='{"dismiss_stale_reviews":true,"require_code_owner_reviews":false}' \
  -f enforce_admins=true

# Ativar Discussions
gh api repos/4pixeltechBR/Seeker.Bot \
  -X PATCH \
  -F has_discussions=true
```

---

## 📋 Checklist Final

- [ ] Branch `main` está protegido (requer PR + status check)
- [ ] Discussions estão ativadas
- [ ] GitHub Actions está rodando (vê o badge ✅ no README)
- [ ] Dependabot está ativado
- [ ] Secret scanning está ativado

Pronto! Seu repositório está configurado profissionalmente! 🚀
