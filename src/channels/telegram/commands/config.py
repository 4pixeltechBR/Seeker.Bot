"""
Seeker.Bot — Painel de Configuração Interativo
src/channels/telegram/commands/config.py

Comando /config: abre um menu com botões para gerenciar Skills,
Providers e Modelo ativo sem precisar editar arquivos manualmente.

Arquitetura:
    - Tela principal:  botões por categoria (Skills, Providers, Modelo)
    - Tela Skills:     lista todas as skills com toggle ✅/❌ direto
    - Tela Providers:  mostra status/saúde dos providers com refresh
    - Tela Modelo:     mostra modelo ativo por papel cognitivo
    - Alterações no YAML são gravadas em disco e recarregadas em runtime
      (sem precisar reiniciar — usa o mesmo mecanismo do registry)
"""

import logging
import os
from pathlib import Path

import yaml
from aiogram import Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src.core.pipeline import SeekerPipeline

log = logging.getLogger("seeker.telegram.config")

config_router = Router()

# ─────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────

_SKILLS_YAML = Path(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )))),
        "config", "skills.yaml",
    )
)

# Skills que NUNCA aparecem no menu de toggle (core protegido)
_PROTECTED_SKILLS = {"health_monitor", "self_improvement", "briefing"}

# Skills comerciais — ficam no menu mas com label diferente
_COMMERCIAL_SKILLS = {"seeker" + "_sales", "seeker" + "_sales_week", "show_leads_daily"}

# Rótulos amigáveis por skill
_SKILL_LABELS = {
    "health_monitor": "Health Monitor",
    "self_improvement": "S.A.R.A. (Self-Healing)",
    "briefing": "Daily Briefing",
    "knowledge_vault": "Knowledge Vault (Obsidian)",
    "scheduler_conversacional": "Scheduler Conversacional",
    "sense_news": "SenseNews (Notícias)",
    "sherlock_news": "SherlockNews (Lançamentos IA)",
    "bug_analyzer": "Bug Analyzer",
    "skill_creator": "Skill Creator (Eureka)",
    "email_monitor": "Email Monitor",
    "desktop_watch": "Desktop Watch (AFK)",
    "remote_executor": "Remote Executor",
    "os_control": "OS Control",
    "git_automation": "Git Auto-Backup",
    "seeker" + "_sales": "🔒 Scout B2B (comercial)",
    "seeker" + "_sales_week": "🔒 Sales Week (comercial)",
    "show_leads_daily": "🔒 ShowDeck Daily (comercial)",
}

# Emojis por categoria
_CATEGORY_EMOJI = {
    "core": "🟢",
    "recommended": "🟡",
    "specialist": "🔵",
}


# ─────────────────────────────────────────────────────────────────
# YAML Helpers
# ─────────────────────────────────────────────────────────────────

def _load_yaml() -> dict:
    """Lê o skills.yaml e retorna o dicionário completo."""
    try:
        with open(_SKILLS_YAML, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        log.error(f"[config] Erro ao ler skills.yaml: {e}")
        return {}


def _save_yaml(data: dict) -> bool:
    """Salva o dicionário de volta no skills.yaml preservando comentários básicos."""
    try:
        # Preserva o cabeçalho em comentário lendo o arquivo original
        original_text = _SKILLS_YAML.read_text(encoding="utf-8")
        header_lines = []
        for line in original_text.splitlines():
            if line.startswith("#"):
                header_lines.append(line)
            else:
                break

        body = yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)
        final = "\n".join(header_lines) + "\n\n" + body
        _SKILLS_YAML.write_text(final, encoding="utf-8")
        return True
    except Exception as e:
        log.error(f"[config] Erro ao salvar skills.yaml: {e}")
        return False


def _toggle_skill(skill_name: str) -> tuple[bool, bool]:
    """
    Alterna o valor de uma skill no YAML.
    Retorna (new_value: bool, success: bool).
    """
    data = _load_yaml()
    for category in ("core", "recommended", "specialist"):
        section = data.get(category, {})
        if skill_name in section:
            new_val = not bool(section[skill_name])
            data[category][skill_name] = new_val
            ok = _save_yaml(data)
            return new_val, ok
    return False, False


def _get_all_skills() -> list[dict]:
    """
    Retorna lista de dicts: {name, label, enabled, category, protected}.
    Ordem: core → recommended → specialist.
    """
    data = _load_yaml()
    result = []
    for category in ("core", "recommended", "specialist"):
        section = data.get(category, {})
        if not isinstance(section, dict):
            continue
        for name, enabled in section.items():
            result.append({
                "name": name,
                "label": _SKILL_LABELS.get(name, name.replace("_", " ").title()),
                "enabled": bool(enabled),
                "category": category,
                "protected": name in _PROTECTED_SKILLS,
                "commercial": name in _COMMERCIAL_SKILLS,
            })
    return result


# ─────────────────────────────────────────────────────────────────
# Keyboards
# ─────────────────────────────────────────────────────────────────

def _kb_main() -> InlineKeyboardMarkup:
    """Teclado da tela principal do /config."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚙️ Skills", callback_data="cfg_skills"),
        ],
        [
            InlineKeyboardButton(text="🤖 Providers & Modelos", callback_data="cfg_providers"),
        ],
        [
            InlineKeyboardButton(text="💰 Budget de hoje", callback_data="cfg_budget"),
        ],
        [
            InlineKeyboardButton(text="🔄 Reiniciar Bot", callback_data="cfg_restart"),
        ],
    ])


def _kb_skills() -> InlineKeyboardMarkup:
    """
    Teclado com todas as skills, agrupadas por categoria.
    Skills protegidas mostram 🔒 e não geram callback.
    """
    skills = _get_all_skills()
    rows = []

    current_cat = None
    for s in skills:
        # Cabeçalho de categoria (botão inativo)
        if s["category"] != current_cat:
            current_cat = s["category"]
            emoji = _CATEGORY_EMOJI.get(current_cat, "⚪")
            cat_label = {"core": "CORE", "recommended": "RECOMMENDED", "specialist": "SPECIALIST"}.get(current_cat, current_cat.upper())
            rows.append([
                InlineKeyboardButton(
                    text=f"── {emoji} {cat_label} ──",
                    callback_data="cfg_noop",
                )
            ])

        # Botão da skill
        if s["protected"]:
            status = "🔒"
            cb = "cfg_noop"
        elif s["enabled"]:
            status = "✅"
            cb = f"cfg_toggle_{s['name']}"
        else:
            status = "❌"
            cb = f"cfg_toggle_{s['name']}"

        rows.append([
            InlineKeyboardButton(
                text=f"{status} {s['label']}",
                callback_data=cb,
            )
        ])

    rows.append([
        InlineKeyboardButton(text="⬅️ Voltar", callback_data="cfg_main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _kb_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Voltar", callback_data="cfg_main")]
    ])


def _kb_restart_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Confirmar Restart", callback_data="cfg_restart_confirm"),
            InlineKeyboardButton(text="❌ Cancelar", callback_data="cfg_main"),
        ]
    ])


# ─────────────────────────────────────────────────────────────────
# Text builders
# ─────────────────────────────────────────────────────────────────

def _text_main() -> str:
    skills = _get_all_skills()
    enabled = sum(1 for s in skills if s["enabled"] and not s["protected"])
    total = sum(1 for s in skills if not s["protected"])
    return (
        "<b>⚙️ Seeker.Bot — Configurações</b>\n\n"
        f"Skills ativas: <b>{enabled}/{total}</b>\n\n"
        "Escolha uma categoria para configurar:"
    )


def _text_skills() -> str:
    return (
        "<b>⚙️ Gerenciar Skills</b>\n\n"
        "Toque em uma skill para ativar ou desativar.\n"
        "🔒 = protegida (core) · ✅ = ativa · ❌ = inativa\n\n"
        "<i>Alterações têm efeito após reiniciar o bot.</i>"
    )


# ─────────────────────────────────────────────────────────────────
# Handlers — Entry Point
# ─────────────────────────────────────────────────────────────────

@config_router.message(F.text == "/config")
async def cmd_config(message: Message):
    """Abre o painel principal de configurações."""
    await message.answer(
        _text_main(),
        reply_markup=_kb_main(),
        parse_mode=ParseMode.HTML,
    )


# ─────────────────────────────────────────────────────────────────
# Handlers — Callbacks
# ─────────────────────────────────────────────────────────────────

@config_router.callback_query(F.data == "cfg_main")
async def cb_main(callback: CallbackQuery):
    """Retorna para a tela principal."""
    await callback.message.edit_text(
        _text_main(),
        reply_markup=_kb_main(),
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@config_router.callback_query(F.data == "cfg_noop")
async def cb_noop(callback: CallbackQuery):
    """Botão decorativo sem ação."""
    await callback.answer()


@config_router.callback_query(F.data == "cfg_skills")
async def cb_skills(callback: CallbackQuery):
    """Abre a tela de gerenciamento de Skills."""
    await callback.message.edit_text(
        _text_skills(),
        reply_markup=_kb_skills(),
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@config_router.callback_query(F.data.startswith("cfg_toggle_"))
async def cb_toggle_skill(callback: CallbackQuery):
    """Alterna uma skill no YAML e atualiza o teclado."""
    skill_name = callback.data.removeprefix("cfg_toggle_")

    if skill_name in _PROTECTED_SKILLS:
        await callback.answer("🔒 Esta skill é protegida e não pode ser desativada.", show_alert=True)
        return

    new_val, ok = _toggle_skill(skill_name)
    if not ok:
        await callback.answer("❌ Erro ao salvar configuração.", show_alert=True)
        return

    status_text = "ativada ✅" if new_val else "desativada ❌"
    label = _SKILL_LABELS.get(skill_name, skill_name)
    await callback.answer(f"{label} {status_text}")
    log.info(f"[config] Skill '{skill_name}' alterada para {new_val} pelo usuário")

    # Atualiza a tela de skills com os novos valores
    await callback.message.edit_text(
        _text_skills(),
        reply_markup=_kb_skills(),
        parse_mode=ParseMode.HTML,
    )


@config_router.callback_query(F.data == "cfg_providers")
async def cb_providers(callback: CallbackQuery, pipeline: SeekerPipeline):
    """Mostra status dos providers e modelos por papel cognitivo."""
    from config.models import CognitiveRole

    router = pipeline.model_router
    lines = ["<b>🤖 Providers & Modelos Ativos</b>\n"]

    lines.append("<b>Papéis Cognitivos:</b>")
    for role in CognitiveRole:
        try:
            model = router.get(role)
            lines.append(f"  • <b>{role.value}</b>: {model.display_name} <i>({model.provider})</i>")
        except ValueError:
            lines.append(f"  • <b>{role.value}</b>: ⚠️ não configurado")

    lines.append("\n<b>Providers na Arbitragem:</b>")
    for m in router.get_all_for_arbitrage():
        lines.append(f"  → {m.display_name} <code>{m.provider}</code>")

    lines.append(
        "\n<i>Para trocar o modelo de um papel, use /switch.</i>"
    )

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=_kb_back(),
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@config_router.callback_query(F.data == "cfg_budget")
async def cb_budget(callback: CallbackQuery, pipeline: SeekerPipeline):
    """Mostra o budget de hoje de forma resumida."""
    try:
        from src.core.budget import BudgetTracker

        tracker = BudgetTracker(pipeline.memory._db)
        summary = await tracker.get_today_summary()

        lines = ["<b>💰 Budget — Hoje</b>\n"]
        total = 0.0
        for provider, cost in summary.items():
            lines.append(f"  • <b>{provider}</b>: ${cost:.4f}")
            total += cost
        lines.append(f"\n  <b>Total:</b> ${total:.4f}")
    except Exception as e:
        log.warning(f"[config] Budget não disponível: {e}")
        lines = [
            "<b>💰 Budget — Hoje</b>\n",
            "Use <b>/budget</b> para ver o detalhamento completo por provedor.",
        ]

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=_kb_back(),
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@config_router.callback_query(F.data == "cfg_restart")
async def cb_restart_prompt(callback: CallbackQuery):
    """Pede confirmação antes de reiniciar."""
    await callback.message.edit_text(
        "<b>🔄 Reiniciar o Bot</b>\n\n"
        "Isso vai encerrar o processo atual. O Watchdog irá reiniciá-lo automaticamente.\n\n"
        "<i>Alterações no skills.yaml entrarão em vigor após o restart.</i>",
        reply_markup=_kb_restart_confirm(),
        parse_mode=ParseMode.HTML,
    )
    await callback.answer()


@config_router.callback_query(F.data == "cfg_restart_confirm")
async def cb_restart_confirm(callback: CallbackQuery):
    """Executa o restart via SIGTERM (Watchdog cuida do relançamento)."""
    import signal

    await callback.message.edit_text(
        "🔄 <b>Reiniciando Seeker.Bot...</b>\n\n"
        "<i>O Watchdog vai relançar o processo em instantes.</i>",
        parse_mode=ParseMode.HTML,
    )
    await callback.answer("Reiniciando...")
    log.warning("[config] Restart manual via /config solicitado pelo usuário.")

    import asyncio
    await asyncio.sleep(1)
    os.kill(os.getpid(), signal.SIGTERM)


# ─────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────

def setup_config_handlers(dp: Dispatcher, pipeline: SeekerPipeline):
    """Registra o router de configuração no dispatcher."""
    dp.include_router(config_router)
