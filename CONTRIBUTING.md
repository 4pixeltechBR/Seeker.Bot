# Contributing to Seeker.Bot

Obrigado por considerar contribuir para o Seeker.Bot! Este documento descreve como participar do projeto.

## 🚀 Como Contribuir

### 1. **Reportar Bugs**
Se encontrou um bug:
- Abra uma [Issue](https://github.com/4pixeltech/Seeker.Bot/issues)
- Descreva: o que esperava, o que aconteceu, como reproduzir
- Inclua logs relevantes de `data/` ou console

### 2. **Sugerir Features**
Tem uma ideia? Abra uma [Discussion](https://github.com/4pixeltech/Seeker.Bot/discussions) primeiro para validar:
- Problema que resolve
- Como se integra com skills existentes
- Esforço estimado

### 3. **Submeter Código**

#### Setup Local
```bash
# Clone
git clone https://github.com/4pixeltech/Seeker.Bot.git
cd Seeker.Bot

# Ambiente
python -m venv .venv
source .venv/bin/activate  # ou .venv\Scripts\activate (Windows)

# Dependências
pip install -e ".[dev]"

# Copia .env.example → .env e preenche chaves de API
cp .env.example .env
```

#### Antes de Submeter PR
```bash
# Testes
pytest tests/ -v

# Type checking
pyright src/ config/

# Nenhum teste deve falhar
```

#### Padrões de Código
- **Python 3.10+** com type hints
- **async/await** para operações I/O
- **Logging**: `log = logging.getLogger("seeker.module.submodule")`
- **Error handling**: Sempre use `exc_info=True` em `log.error()`
- **Docstrings**: Classes e funções públicas devem ter docstring

#### Estrutura de Commits
```
<tipo>: <descrição curta>

<corpo detalhado se necessário>

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>
```

Tipos válidos: `feat`, `fix`, `test`, `docs`, `refactor`, `chore`

### 4. **Criar uma Nova Skill**

Herde de `AutonomousGoal` e implemente o factory:

```python
# src/skills/my_skill/goal.py
from src.core.goals.protocol import AutonomousGoal, GoalResult

class MySkill(AutonomousGoal):
    name = "my_skill"
    interval_seconds = 3600
    channels = [NotificationChannel.TELEGRAM]
    
    async def run_cycle(self) -> GoalResult:
        # Seu código aqui
        return GoalResult(
            success=True,
            summary="Resultado breve",
            notification="Mensagem pro Telegram",
            cost_usd=0.05
        )

def create_goal(pipeline):
    return MySkill(pipeline)
```

Registre em `src/core/goals/registry.py`:
```python
AVAILABLE_GOALS = {
    "my_skill": ("src.skills.my_skill.goal", "create_goal"),
}
```

### 5. **Melhorar Documentação**

- READMEs claros e attualizados
- Docstrings em código
- Exemplos de uso

---

## 📋 Checklist antes de submeter PR

- [ ] Testes passando (`pytest`)
- [ ] Type hints válidos (`pyright`)
- [ ] Nenhuma chave de API no código
- [ ] `.env` não foi commitado
- [ ] Commit message segue formato
- [ ] Documentação atualizada
- [ ] Mensagens de log incluem `exc_info=True`

---

## 🎯 Roadmap

Prioridades atuais:
- [ ] Dashboard web (`/api/health`)
- [ ] Suporte a mais providers LLM
- [ ] Integração com mais canais (Discord, Slack)
- [ ] Análise de padrões de falha (correlação com horários)
- [ ] Exportação de métricas para Prometheus

---

## 📞 Contato

- Issues: [GitHub Issues](https://github.com/4pixeltech/Seeker.Bot/issues)
- Discussões: [GitHub Discussions](https://github.com/4pixeltech/Seeker.Bot/discussions)
- Email: support@4pixeltech.com

Obrigado por contribuir! 🙏
