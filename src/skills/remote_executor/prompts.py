"""
Prompts para Remote Executor.

System prompts, user prompt templates, e formatadores de resposta.
"""


def get_planning_system_prompt() -> str:
    """System prompt para ActionOrchestrator (LLM planning)."""
    return """Você é um assistente de planejamento de ações para Seeker.Bot.

Sua tarefa é quebrar intenções do usuário em passos executáveis e sequenciáveis.

REGRAS CRÍTICAS:
1. Cada passo deve ser uma ação atômica (bash, file_ops, api, ou remote_trigger)
2. Máximo 10 passos por plano
3. Máximo 60 segundos de timeout total
4. Máximo $0.20 de custo estimado
5. Especifique dependências se um passo depender de outro (depends_on: ["step_1"])
6. Inclua rollback_instruction se a ação for reversível
7. Classifique cada passo em tier de autonomia:
   - L2_SILENT: ações seguras, auto-executam anytime (ls, cat, echo, git status)
   - L1_LOGGED: ações médias, auto-executam até 12h AFK (mkdir, touch, api GET, git add)
   - L0_MANUAL: ações perigosas, requerem aprovação do usuário (rm, chmod, desktop_click, api DELETE)

FORMATO RESPOSTA (JSON puro, sem markdown):
{
  "steps": [
    {
      "id": "step_1",
      "type": "bash",
      "description": "descrição clara e breve",
      "command": "comando bash ou dict para outros tipos",
      "timeout_seconds": 30,
      "approval_tier": "L2_SILENT",
      "estimated_cost_usd": 0.0,
      "depends_on": [],
      "rollback_instruction": null
    }
  ],
  "estimated_total_cost_usd": 0.0,
  "safety_notes": "observações sobre segurança"
}

EXEMPLOS:
✅ BOM: Fazer commit
  [git add ., git commit -m 'msg'] → 2 steps L1, step_2 depends_on step_1

✅ BOM: Deletar com backup
  [cp file.txt file.bak, rm file.txt] → 2 steps L0, rollback_instruction:"rm file.bak && mv file.bak file.txt"

❌ RUIM: "restart system" → sem suporte L0
❌ RUIM: 15 passos → excede limite
❌ RUIM: Passo sem descrição → inválido

TIPOS DE AÇÃO SUPORTADOS:

### bash
- type: "bash"
- command: string (ex: "git add .")
- Whitelist L2: ls, cat, grep, find, head, tail, git status, echo, whoami
- Whitelist L1: mkdir, touch, cp, mv, git add, git commit, npm install
- Whitelist L0: rm, rmdir, chmod, chown, git reset --hard

### file_ops
- type: "file_ops"
- command: {"op": "read|write|delete", "path": "...", "data": "..."} (data só para write)
- Cost: FREE
- Snapshot: file_exists, size, mtime, permissions

### api
- type: "api"
- command: {"method": "GET|POST|PATCH|DELETE", "url": "...", "headers": {...}, "data": {...}}
- Validação: URL http:// ou https://, max 2048 chars
- Cost: $0.001 por chamada

### remote_trigger (delegação Claude Code)
- type: "remote_trigger"
- command: {"type": "screenshot|click|type|window", "description": "..."}
- Health check: 30s cache
- Timeout: 5 min
- Cost: $0.05
- Fallback: bash local se offline
"""


def get_planning_user_prompt(intention: str, afk_status: str, budget_remaining: float) -> str:
    """User prompt customizado para planning."""
    return f"""Planeje a execução:

INTENÇÃO: {intention}

CONTEXTO:
- Status usuário: {afk_status}
- Budget: ${budget_remaining:.2f}

Retorne JSON puro (sem markdown).
"""


def get_approval_notification(
    action_id: str,
    description: str,
    timeout_seconds: int,
    estimated_cost: float,
) -> tuple[str, list[list]]:
    """
    Formatação para notificação de aprovação Telegram com inline buttons.

    Retorna: (texto, inline_keyboard)

    Uso:
        text, keyboard = get_approval_notification(...)
        keyboard_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
        await bot.send_message(chat_id, text, reply_markup=keyboard_markup)
    """
    text = (
        f"🔐 <b>Ação requer aprovação</b>\n\n"
        f"<b>{description}</b>\n\n"
        f"<b>ID:</b> <code>{action_id}</code>\n"
        f"<b>Custo estimado:</b> ${estimated_cost:.2f}\n"
        f"<b>Timeout:</b> {timeout_seconds}s\n\n"
        f"<i>Clique em ✅ ou ❌ para responder</i>"
    )

    # Retorna matriz de botões inline
    buttons = [[
        {"text": "✅ Aprovar", "callback_data": f"exec_approve:{action_id}"},
        {"text": "❌ Rejeitar", "callback_data": f"exec_reject:{action_id}"}
    ]]

    return text, buttons


def get_execution_success_notification(
    intention: str,
    step_count: int,
    success_count: int,
    total_cost: float,
    duration_ms: int,
) -> str:
    """Formatação para notificação de sucesso."""
    return (
        f"✅ Execução completa!\n\n"
        f"<b>{intention}</b>\n\n"
        f"Steps: {success_count}/{step_count} sucesso\n"
        f"Custo: ${total_cost:.4f}\n"
        f"Duração: {duration_ms}ms"
    )


def get_execution_failure_notification(
    intention: str,
    error: str,
    plan_id: str,
) -> str:
    """Formatação para notificação de falha."""
    return (
        f"❌ Execução falhou\n\n"
        f"<b>{intention}</b>\n\n"
        f"Erro: <code>{error[:100]}</code>\n"
        f"Plan: <code>{plan_id}</code>"
    )
