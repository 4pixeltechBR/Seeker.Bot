# S4b — SenseNews (Curadoria + PDF)

## Arquivos NOVOS

```
src/skills/sense_news/__init__.py     ← criar vazio
src/skills/sense_news/goal.py         ← goal.py
src/skills/sense_news/prompts.py      ← prompts.py
src/skills/sense_news/pdf_builder.py  ← pdf_builder.py
```

## Dependência nova

```bash
pip install fpdf2
```

## DIFF: scheduler.py — enviar PDF como documento no Telegram

O SenseNews retorna `data={"pdf_path": "/path/to.pdf"}` no GoalResult.
O notifier precisa enviar como documento, não como texto.

### No GoalNotifier._send_telegram — SUBSTITUIR método inteiro:

```python
    async def _send_telegram(self, goal_name: str, content: str, data: dict | None = None):
        if not self.bot:
            return
        for uid in self.admin_chats:
            try:
                # Se tem PDF, envia como documento
                pdf_path = (data or {}).get("pdf_path", "")
                if pdf_path and os.path.exists(pdf_path):
                    from aiogram.types import FSInputFile
                    doc = FSInputFile(pdf_path)
                    await self.bot.send_document(uid, doc, caption=content[:1024])
                else:
                    await self.bot.send_message(uid, content)
            except Exception as e:
                log.error(f"[notifier/{goal_name}] Telegram falhou {uid}: {e}")
```

### No GoalNotifier.send — PASSAR data:

```python
# ANTES:
async def send(self, goal_name: str, content: str, channels: list[NotificationChannel]):
    for channel in channels:
        if channel in (NotificationChannel.TELEGRAM, NotificationChannel.BOTH):
            await self._send_telegram(goal_name, content)

# DEPOIS:
async def send(self, goal_name: str, content: str, channels: list[NotificationChannel], data: dict | None = None):
    for channel in channels:
        if channel in (NotificationChannel.TELEGRAM, NotificationChannel.BOTH):
            await self._send_telegram(goal_name, content, data)
        if channel in (NotificationChannel.EMAIL, NotificationChannel.BOTH):
            await self._send_email(goal_name, content)
```

### No GoalScheduler._run_goal_loop — PASSAR data na notificação:

```python
# ANTES:
if result.notification:
    await self.notifier.send(
        goal.name, result.notification, goal.channels
    )

# DEPOIS:
if result.notification:
    await self.notifier.send(
        goal.name, result.notification, goal.channels, data=result.data
    )
```

### Adicionar import no scheduler.py:

```python
import os  # No topo, se não existir
```

## DIFF: briefing goal.py — renomear para DailyNews

### No arquivo `src/skills/briefing/goal.py`:

```python
# ANTES:
class BriefingGoal:

# DEPOIS:
class DailyNewsGoal:
```

```python
# ANTES:
@property
def name(self) -> str:
    return "briefing"

# DEPOIS:
@property
def name(self) -> str:
    return "daily_news"
```

```python
# ANTES:
def create_goal(pipeline) -> BriefingGoal:
    return BriefingGoal(pipeline)

# DEPOIS:
def create_goal(pipeline) -> DailyNewsGoal:
    return DailyNewsGoal(pipeline)
```

**NOTA:** Ao renomear, delete o `data/goals/briefing.json` para o scheduler
criar novo estado com o nome correto. Senão ele tenta restaurar estado
com o nome antigo.

---

## Deploy

1. `pip install fpdf2`
2. Criar pasta `src/skills/sense_news/`
3. Copiar os 3 arquivos + `__init__.py` vazio
4. Aplicar diffs no `scheduler.py` (3 mudanças)
5. Aplicar diffs no `src/skills/briefing/goal.py` (renomear)
6. Deletar `data/goals/briefing.json`
7. Reiniciar

## Log esperado

```
[registry] ✅ briefing — registrado
[registry] ✅ revenue_hunter — registrado
[registry] ✅ sense_news — registrado
[registry] ✅ viralclip_curator — registrado
[scheduler] 4 goals iniciados.
```

Às 10:00:
```
[sensenews] BIO-ESCALAR: 3 temas analisados
[sensenews] FORENSIC TECH: 2 temas analisados
[sensenews] SÍTIO 404: 2 temas analisados
[sensenews] CRIMES DIGITAIS: 3 temas analisados
[sensenews] PDF gerado: data/sense_news/SenseNews_2026-04-02.pdf
[scheduler/sense_news] Ciclo OK | SenseNews: 10 temas, PDF gerado | $0.0000
```

E no Telegram: PDF como documento anexo com caption resumindo os nichos.
