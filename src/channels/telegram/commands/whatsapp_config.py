"""Telegram /wa_config panel — gerencia config/whatsapp.yaml pelo chat.

Clona o padrão de src/channels/telegram/commands/config.py e custom_extension.py.
Mudanças são escritas em config/whatsapp.yaml (atomic .tmp + replace) e
aplicadas no próximo ciclo do WhatsAppVaultGoal (hot-reload).
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from aiogram import Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src.core.pipeline import SeekerPipeline

log = logging.getLogger("seeker.telegram.whatsapp_config")

# E:\Seeker.Bot\src\channels\telegram\commands\whatsapp_config.py
# → 5 níveis acima = E:\Seeker.Bot
_PROJECT_ROOT = Path(
    os.path.dirname(
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__))
                )
            )
        )
    )
)
CONFIG_PATH = _PROJECT_ROOT / "config" / "whatsapp.yaml"

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": False,
    "mode": "evolution_api",
    "evolution": {
        "base_url": "http://localhost:8080",
        "api_key": "",
        "instance": "seeker-main",
    },
    "target": {
        "group_id": "",
        "group_name": "",
        "forward_own_number": "",
    },
    "schedule": {
        "windows": [[2, 0], [6, 0], [10, 0], [14, 0], [18, 0], [22, 0]],
        "max_per_cycle": 20,
        "notify_on_empty": False,
    },
    "vault": {"type": "knowledge", "custom_path": ""},
    "notifications": {"telegram": True, "chat_id": ""},
}

YAML_HEADER = (
    "# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "# WhatsApp Vault — Configuração (gerenciado por /wa_config)\n"
    "# Hot-reloaded a cada ciclo do WhatsAppVaultGoal.\n"
    "# Edite via /wa_config no Telegram ou manualmente com cuidado.\n"
    "# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
)


# ── YAML I/O helpers ──────────────────────────────────────────────────


def _expand_env(value: Any) -> Any:
    """Resolve ${VAR} e ${VAR:-default} em strings, recursivamente em dicts/listas.

    Diferente de os.path.expandvars (POSIX-only, não entende ':-default'),
    esta implementação cobre tanto expansão simples quanto com default,
    compatível com shell bash/Docker Compose.

    Usa os.environ para resolver. Se a variável não existir e não tiver
    default, retorna string vazia.
    """
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    if not isinstance(value, str):
        return value

    # Padrão: ${VAR} ou ${VAR:-default} (default pode estar vazio)
    pattern = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

    def _replace(match: re.Match) -> str:
        var_name = match.group(1)
        default = match.group(2)  # None se não tem :-
        env_val = os.environ.get(var_name)
        if env_val is not None and env_val != "":
            return env_val
        if default is not None:
            return default
        return ""

    return pattern.sub(_replace, value)


def _load_config() -> dict[str, Any]:
    """Lê config/whatsapp.yaml. Fallback para DEFAULT_CONFIG se ausente/inválido.

    Aplica expansão de variáveis de ambiente (${VAR:-default}) em todos os
    valores string, recursivamente. Assim, se o YAML tem literal
    `${EVOLUTION_BASE_URL:-http://localhost:8080}` mas a env var não estiver
    setada, o default é usado.
    """
    if not CONFIG_PATH.exists():
        return _deep_copy_defaults()
    try:
        import yaml
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        cfg = raw.get("whatsapp", {})
        if not isinstance(cfg, dict):
            return _deep_copy_defaults()
        # Merge com defaults (deep keys novos não quebram)
        for k, v in DEFAULT_CONFIG.items():
            if k not in cfg:
                cfg[k] = _deep_copy(v)
            elif isinstance(v, dict) and isinstance(cfg[k], dict):
                for sk, sv in v.items():
                    if sk not in cfg[k]:
                        cfg[k][sk] = _deep_copy(sv)
                    elif isinstance(sv, dict) and isinstance(cfg[k][sk], dict):
                        for ssk, ssv in sv.items():
                            cfg[k][sk].setdefault(ssk, _deep_copy(ssv))
        # Resolve ${VAR} e ${VAR:-default} em todos os strings
        return _expand_env(cfg)
    except Exception as e:
        log.warning(f"[wa_config] Falha ao ler {CONFIG_PATH}: {e}; usando defaults")
        return _deep_copy_defaults()


def _deep_copy(value: Any) -> Any:
    """Deep copy leve para defaults aninhados (dict/list)."""
    if isinstance(value, dict):
        return {k: _deep_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_copy(v) for v in value]
    return value


def _deep_copy_defaults() -> dict[str, Any]:
    return _deep_copy(DEFAULT_CONFIG)


def _save_config(cfg: dict[str, Any]) -> bool:
    """Atomic write YAML preservando header. Retorna True se OK."""
    import yaml
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(YAML_HEADER)
            yaml.safe_dump({"whatsapp": cfg}, f, allow_unicode=True, sort_keys=False)
        os.replace(tmp, CONFIG_PATH)
        log.info(f"[wa_config] YAML salvo em {CONFIG_PATH}")
        return True
    except Exception as e:
        log.error(f"[wa_config] Falha ao salvar {CONFIG_PATH}: {e}")
        try:
            tmp.unlink()
        except OSError:
            pass
        return False


# ── Keyboards ────────────────────────────────────────────────────────


def _kb_main(cfg: dict[str, Any]) -> InlineKeyboardMarkup:
    enabled = cfg.get("enabled", False)
    mode = cfg.get("mode", "evolution_api")
    target = cfg.get("target", {}) or {}
    group_id = target.get("group_id", "")
    group_name = target.get("group_name", "") or "(não definido)"
    short_id = group_id.split("@")[0][-12:] if group_id else ""
    label = "✅ Ativo" if enabled else "❌ Desabilitado"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📊 Status: {label}", callback_data="wa_cfg_toggle:enabled")],
        [InlineKeyboardButton(text=f"📋 Grupo: {group_name[:20]} ({short_id})", callback_data="wa_cfg_menu:grupo")],
        [InlineKeyboardButton(text="⏰ Janelas de polling", callback_data="wa_cfg_menu:janelas")],
        [InlineKeyboardButton(text=f"🔄 Modo: {mode}", callback_data="wa_cfg_menu:modo")],
        [InlineKeyboardButton(text="📁 Vault destino", callback_data="wa_cfg_menu:vault")],
        [InlineKeyboardButton(text="🧪 Forçar poll agora", callback_data="wa_cfg_teste")],
        [InlineKeyboardButton(text="🔌 Status detalhado", callback_data="wa_cfg_menu:status")],
    ])


def _kb_back(target: str = "main") -> InlineKeyboardMarkup:
    if target == "main":
        cb = "wa_cfg_main"
    else:
        cb = f"wa_cfg_menu:{target}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="← Voltar", callback_data=cb)]
    ])


# ── Text builders ───────────────────────────────────────────────────


def _render_main_text(cfg: dict[str, Any]) -> str:
    enabled = cfg.get("enabled", False)
    mode = cfg.get("mode", "evolution_api")
    target = cfg.get("target", {}) or {}
    group_id = target.get("group_id", "")
    group_name = target.get("group_name", "")
    windows = (cfg.get("schedule", {}) or {}).get("windows", []) or []
    vault_type = (cfg.get("vault", {}) or {}).get("type", "knowledge")
    enabled_str = "✅ Ativo" if enabled else "❌ Desabilitado"
    win_str = ", ".join(f"{int(h):02d}:{int(mm):02d}" for h, mm in windows) or "(nenhuma)"
    return (
        "🔌 <b>WhatsApp Vault — Configuração</b>\n\n"
        f"<b>Status:</b> {enabled_str}\n"
        f"<b>Modo:</b> <code>{mode}</code>\n"
        f"<b>Grupo:</b> {group_name or '(não definido)'} <code>{group_id or ''}</code>\n"
        f"<b>Janelas:</b> {win_str}\n"
        f"<b>Vault destino:</b> {vault_type}\n\n"
        "<i>Mudanças aplicam no próximo ciclo (hot-reload).</i>"
    )


# ── Handlers — Entry Point ───────────────────────────────────────────


def setup_whatsapp_config_handlers(dp: Dispatcher, pipeline: SeekerPipeline):

    @dp.message(F.text.regexp(r"^/wa_config(\s|$)"))
    async def cmd_wa_config(message: Message):
        text = (message.text or "").strip()
        parts = text.split(maxsplit=1)
        if text == "/wa_config" or len(parts) == 1:
            cfg = _load_config()
            await message.answer(
                _render_main_text(cfg),
                parse_mode=ParseMode.HTML,
                reply_markup=_kb_main(cfg),
            )
            return
        sub = parts[1].strip()
        if sub == "grupo":
            await _show_groups(message, pipeline)
        elif sub == "janelas":
            await _show_windows(message)
        elif sub == "modo":
            await _show_modes(message)
        elif sub == "vault":
            await _show_vaults(message)
        elif sub == "status":
            await _show_status(message, pipeline)
        elif sub == "testar":
            await _do_test_poll(message, pipeline)
        else:
            await message.answer(
                "❓ Sub-comando inválido. Opções: <code>grupo</code> · "
                "<code>janelas</code> · <code>modo</code> · <code>vault</code> · "
                "<code>status</code> · <code>testar</code>",
                parse_mode=ParseMode.HTML,
            )

    @dp.callback_query(F.data == "wa_cfg_main")
    async def cb_main(call: CallbackQuery):
        await call.answer()
        cfg = _load_config()
        try:
            await call.message.edit_text(
                _render_main_text(cfg),
                parse_mode=ParseMode.HTML,
                reply_markup=_kb_main(cfg),
            )
        except Exception as e:
            log.debug(f"[wa_config] edit_text falhou: {e}")
            await call.message.answer(
                _render_main_text(cfg),
                parse_mode=ParseMode.HTML,
                reply_markup=_kb_main(cfg),
            )

    @dp.callback_query(F.data.startswith("wa_cfg_menu:"))
    async def cb_menu(call: CallbackQuery):
        await call.answer()
        target = call.data.split(":", 1)[1]
        if target == "grupo":
            await _show_groups(call.message, pipeline, edit=True)
        elif target == "janelas":
            await _show_windows(call.message, edit=True)
        elif target == "modo":
            await _show_modes(call.message, edit=True)
        elif target == "vault":
            await _show_vaults(call.message, edit=True)
        elif target == "status":
            await _show_status(call.message, pipeline, edit=True)
        else:
            await cb_main(call)

    @dp.callback_query(F.data == "wa_cfg_toggle:enabled")
    async def cb_toggle_enabled(call: CallbackQuery):
        cfg = _load_config()
        cfg["enabled"] = not bool(cfg.get("enabled", False))
        _save_config(cfg)
        await call.answer(f"{'✅ Ativado' if cfg['enabled'] else '❌ Desabilitado'}")
        await cb_main(call)

    @dp.callback_query(F.data.startswith("wa_cfg_grupo:"))
    async def cb_select_group(call: CallbackQuery):
        group_id = call.data.split(":", 1)[1]
        cfg = _load_config()
        target = cfg.setdefault("target", {})
        target["group_id"] = group_id
        # tenta preservar o nome do grupo via cache de conexão recente
        target["group_name"] = target.get("group_name", "") or _resolve_group_name(group_id)
        _save_config(cfg)
        short = group_id.split("@")[0][-12:]
        await call.answer(f"✅ Grupo selecionado: {short}")
        await cb_main(call)

    @dp.callback_query(F.data == "wa_cfg_grupos_all")
    async def cb_show_all_groups(call: CallbackQuery):
        """Mostra TODOS os 63 grupos (sem filtro de atividade)."""
        await call.answer("📜 Carregando todos os grupos...")
        await _show_groups(call.message, pipeline, edit=True, limit=63)

    @dp.callback_query(F.data.startswith("wa_cfg_janela:"))
    async def cb_toggle_window(call: CallbackQuery):
        parts = call.data.split(":")
        # Formato: wa_cfg_janela:HH:MM:state  (state="on" quer adicionar, "off" quer remover)
        if len(parts) != 4:
            await call.answer("❌ Callback malformado.", show_alert=True)
            return
        _, hh, mm, state = parts
        try:
            h, m = int(hh), int(mm)
        except ValueError:
            await call.answer("❌ Horário inválido.", show_alert=True)
            return
        cfg = _load_config()
        schedule = cfg.setdefault("schedule", {})
        windows = schedule.setdefault("windows", [])
        # Normaliza para list[list[int]] para comparação
        normalized = [list(w) if isinstance(w, (list, tuple)) else [int(w[0]), int(w[1])] for w in windows]
        target_pair = [h, m]
        if state == "on":
            if target_pair not in normalized:
                normalized.append(target_pair)
                normalized.sort(key=lambda w: (int(w[0]), int(w[1])))
        else:  # state == "off" → remover
            normalized = [w for w in normalized if not (int(w[0]) == h and int(w[1]) == m)]
        schedule["windows"] = normalized
        _save_config(cfg)
        await call.answer(f"⏰ Janela {h:02d}:{m:02d} {'ativada' if state == 'on' else 'desativada'}")
        await _show_windows(call.message, edit=True)

    @dp.callback_query(F.data.startswith("wa_cfg_modo:"))
    async def cb_set_mode(call: CallbackQuery):
        mode = call.data.split(":", 1)[1]
        if mode not in ("evolution_api", "manual_forward"):
            await call.answer("❌ Modo inválido.", show_alert=True)
            return
        cfg = _load_config()
        cfg["mode"] = mode
        _save_config(cfg)
        await call.answer(f"🔄 Modo: {mode}")
        await cb_main(call)

    @dp.callback_query(F.data.startswith("wa_cfg_vault:"))
    async def cb_set_vault(call: CallbackQuery):
        vtype = call.data.split(":", 1)[1]
        if vtype not in ("knowledge", "inbox", "custom"):
            await call.answer("❌ Tipo inválido.", show_alert=True)
            return
        cfg = _load_config()
        cfg.setdefault("vault", {})["type"] = vtype
        _save_config(cfg)
        await call.answer(f"📁 Vault: {vtype}")
        await cb_main(call)

    @dp.callback_query(F.data == "wa_cfg_teste")
    async def cb_teste(call: CallbackQuery):
        await call.answer("🧪 Disparando poll forçado...")
        await _do_test_poll(call.message, pipeline)


# ── Sub-telas (show + edit) ──────────────────────────────────────────


def _resolve_group_name(group_id: str) -> str:
    """Best-effort: tenta descobrir o nome do grupo via cache do goal/scheduler."""
    return ""


async def _send_or_edit(message, text: str, reply_markup, edit: bool) -> None:
    if edit:
        try:
            await message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
            return
        except Exception as e:
            log.debug(f"[wa_config] edit_text falhou, enviando novo: {e}")
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)


async def _show_groups(message: Message, pipeline: SeekerPipeline, edit: bool = False, limit: int = 15):
    """Lista grupos via Evolution API."""
    try:
        from src.channels.whatsapp.client import WhatsAppClient
        client = WhatsAppClient()
        if not client.is_configured:
            await _send_or_edit(
                message,
                "❌ <b>EVOLUTION_API_KEY não configurada</b>\n\n"
                "Defina no .env: <code>EVOLUTION_API_KEY=...</code>",
                _kb_back(),
                edit,
            )
            return
        await client.connect() if hasattr(client, "connect") else None
        try:
            groups = await client.find_recent_groups(limit=limit)
        finally:
            await client.close()
    except Exception as e:
        await _send_or_edit(
            message,
            f"❌ Falha ao conectar Evolution API: <code>{e}</code>",
            _kb_back(),
            edit,
        )
        return

    if not groups:
        await _send_or_edit(
            message,
            "⚠️ Nenhum grupo encontrado. Conecte a instância no painel Evolution "
            "(http://localhost:8080/manager) e tente novamente.",
            _kb_back(),
            edit,
        )
        return

    rows = []
    for g in groups:
        gid = g.get("id", "")
        if not gid:
            continue
        subject = (g.get("subject") or "(sem nome)")[:30]
        size = g.get("size", 0)
        # Indicador de atividade: ⏰ se foi renomeado/ativo recentemente
        import time as _t
        st = g.get("subject_time") or 0
        age_days = ((_t.time() - st) / 86400) if st else 999
        activity_marker = "🟢" if age_days < 30 else ("🟡" if age_days < 180 else "⚪")
        rows.append([
            InlineKeyboardButton(
                text=f"{activity_marker} {subject} ({size})",
                callback_data=f"wa_cfg_grupo:{gid}",
            )
        ])
    if len(groups) == limit and limit < 63:
        # Pode ter truncado — oferecer lista completa
        rows.append([InlineKeyboardButton(text="📜 Ver todos (63)", callback_data="wa_cfg_grupos_all")])
    rows.append([InlineKeyboardButton(text="← Voltar", callback_data="wa_cfg_main")])
    await _send_or_edit(
        message,
        f"📋 <b>Grupos disponíveis ({len(groups)})</b>\n\nSelecione para monitorar:",
        InlineKeyboardMarkup(inline_keyboard=rows),
        edit,
    )


async def _show_windows(message: Message, edit: bool = False):
    cfg = _load_config()
    windows_raw = (cfg.get("schedule", {}) or {}).get("windows", []) or []
    windows = set()
    for w in windows_raw:
        try:
            windows.add((int(w[0]), int(w[1])))
        except (TypeError, ValueError, IndexError):
            continue

    rows = []
    # Grid 2h: 00, 02, ..., 22
    for h in range(0, 24, 2):
        is_on = (h, 0) in windows
        icon = "✅" if is_on else "❌"
        state = "off" if is_on else "on"  # estado futuro: clicar vai para esse estado
        rows.append([
            InlineKeyboardButton(
                text=f"{icon} {h:02d}:00",
                callback_data=f"wa_cfg_janela:{h}:0:{state}",
            )
        ])
    rows.append([InlineKeyboardButton(text="← Voltar", callback_data="wa_cfg_main")])
    active = ", ".join(f"{h:02d}:00" for h, _ in sorted(windows)) or "(nenhuma)"
    await _send_or_edit(
        message,
        f"⏰ <b>Janelas de polling</b>\n\nAtivas: {active}\n\n"
        "Clique para toggle (bot salva no YAML automaticamente):",
        InlineKeyboardMarkup(inline_keyboard=rows),
        edit,
    )


async def _show_modes(message: Message, edit: bool = False):
    cfg = _load_config()
    mode = cfg.get("mode", "evolution_api")
    rows = [
        [InlineKeyboardButton(
            text=f"{'✅' if mode == 'evolution_api' else '⚪'} 🌐 evolution-api (auto-polling)",
            callback_data="wa_cfg_modo:evolution_api",
        )],
        [InlineKeyboardButton(
            text=f"{'✅' if mode == 'manual_forward' else '⚪'} 📲 Manual forward (Telegram)",
            callback_data="wa_cfg_modo:manual_forward",
        )],
        [InlineKeyboardButton(text="← Voltar", callback_data="wa_cfg_main")],
    ]
    await _send_or_edit(
        message,
        "🔄 <b>Modo de captura</b>\n\nSelecione:",
        InlineKeyboardMarkup(inline_keyboard=rows),
        edit,
    )


async def _show_vaults(message: Message, edit: bool = False):
    cfg = _load_config()
    vtype = (cfg.get("vault", {}) or {}).get("type", "knowledge")
    rows = [
        [InlineKeyboardButton(
            text=f"{'✅' if vtype == 'knowledge' else '⚪'} 📚 Knowledge/ (direto no KB)",
            callback_data="wa_cfg_vault:knowledge",
        )],
        [InlineKeyboardButton(
            text=f"{'✅' if vtype == 'inbox' else '⚪'} 📥 Inbox/ (você revisa antes)",
            callback_data="wa_cfg_vault:inbox",
        )],
        [InlineKeyboardButton(
            text=f"{'✅' if vtype == 'custom' else '⚪'} 📝 Custom path...",
            callback_data="wa_cfg_vault:custom",
        )],
        [InlineKeyboardButton(text="← Voltar", callback_data="wa_cfg_main")],
    ]
    await _send_or_edit(
        message,
        "📁 <b>Vault destino</b>\n\nEscolha onde gravar:",
        InlineKeyboardMarkup(inline_keyboard=rows),
        edit,
    )


async def _show_status(message: Message, pipeline: SeekerPipeline, edit: bool = False):
    """Read-only status."""
    cfg = _load_config()
    enabled = cfg.get("enabled", False)
    target = cfg.get("target", {}) or {}
    group_id = target.get("group_id", "") or ""
    group_name = target.get("group_name", "") or ""
    evolution = cfg.get("evolution", {}) or {}
    base = evolution.get("base_url", "?")
    instance = evolution.get("instance", "?")
    api_set = bool(evolution.get("api_key", ""))
    # Formata a connection state com emoji adequado
    state_raw = ""
    state_icon = "❔"
    try:
        from src.channels.whatsapp.client import WhatsAppClient
        client = WhatsAppClient(
            base_url=evolution.get("base_url") or None,
            api_key=evolution.get("api_key") or None,
            instance=evolution.get("instance") or None,
        )
        if client.is_configured:
            state = await client.connection_state()
            # Resposta típica: {"instance": {"instanceName": "...", "state": "open"}}
            # Mas pode vir como {"state": "open"} direto também.
            inner = state.get("instance", state) if isinstance(state, dict) else {}
            if not isinstance(inner, dict):
                inner = state if isinstance(state, dict) else {}
            state_raw = str(inner.get("state", "?"))
            state_icon = {
                "open": "🟢",
                "connecting": "🟡",
                "close": "🔴",
            }.get(state_raw, "❔")
            inst_name = inner.get("instanceName", instance) if isinstance(inner, dict) else instance
            conn_status = f"{state_icon} {state_raw} ({inst_name})"
        else:
            conn_status = "⚠️ não configurado"
        await client.close()
    except Exception as e:
        conn_status = f"🔴 erro: {e}"

    vault_cfg = cfg.get("vault", {}) or {}
    vtype = vault_cfg.get("type", "knowledge")
    vault_path = "<Knowledge/> (default)" if vtype == "knowledge" else vault_cfg.get("custom_path", "")

    # Tenta localizar goal ativo para contar seen_ids
    seen_count = "?"
    goal = _find_whatsapp_goal(pipeline)
    if goal is not None:
        try:
            seen_count = str(len(getattr(goal, "_seen_ids", [])))
        except Exception:
            seen_count = "?"

    # Formata o grupo alvo de forma mais legível
    if group_id and group_name:
        grupo_display = f"<code>{group_id}</code>\n       ({group_name})"
    elif group_id:
        grupo_display = f"<code>{group_id}</code>"
    else:
        grupo_display = "<i>(vazio — use /wa_config → Grupo para escolher)</i>"

    # Formata Seen IDs com emoji
    seen_display = f"📋 {seen_count}"

    text = (
        "🔌 <b>WhatsApp Vault — Status</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"  <b>Habilitado:</b>  {'✅ sim' if enabled else '❌ não'}\n"
        f"  <b>Modo:</b>  {cfg.get('mode', 'evolution_api')}\n\n"
        f"  <b>🌐 Evolution URL:</b>  <code>{base}</code>\n"
        f"  <b>🔑 API Key:</b>  {'✅ configurada' if api_set else '❌ vazia'}\n"
        f"  <b>📡 Conexão:</b>  {conn_status}\n\n"
        f"  <b>🎯 Grupo alvo:</b>  {grupo_display}\n"
        f"  <b>📁 Vault destino:</b>  {vault_path}\n"
        f"  <b>🗂️  Seen IDs:</b>  {seen_display}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<i>Use /wa_config para editar. /wa_teste para forçar poll.</i>"
    )

    # Teclado com ações rápidas
    rows = [
        [InlineKeyboardButton(text="🧪 Forçar poll agora", callback_data="wa_cfg_teste")],
        [InlineKeyboardButton(text="⚙️ Abrir /wa_config", callback_data="wa_cfg_main")],
    ]
    await _send_or_edit(message, text, InlineKeyboardMarkup(inline_keyboard=rows), edit)


def _find_whatsapp_goal(pipeline: SeekerPipeline):
    """Localiza a instância do WhatsAppVaultGoal (mesmo padrão de /test_email)."""
    candidates = []
    if hasattr(pipeline, "_goals") and pipeline._goals:
        candidates.extend(pipeline._goals)
    scheduler = getattr(pipeline, "_scheduler", None)
    if scheduler is not None and hasattr(scheduler, "_goals"):
        try:
            candidates.extend(scheduler._goals.values())
        except Exception:
            pass
    for g in candidates:
        if getattr(g, "name", None) == "whatsapp_vault":
            return g
    return None


async def _do_test_poll(message: Message, pipeline: SeekerPipeline):
    """Força um poll agora (bypass de janela)."""
    await message.answer("🧪 Forçando poll agora...", parse_mode=ParseMode.HTML)
    try:
        goal = _find_whatsapp_goal(pipeline)
        if goal is None:
            # Fallback: instancia um efêmero
            from src.skills.whatsapp_vault.goal import WhatsAppVaultGoal
            goal = WhatsAppVaultGoal(pipeline)
        # Hot-reload config
        goal._config = goal._load_config()
        # Bypass de janela: sobrescreve _is_in_window apenas para este call
        original_window_check = goal._is_in_window
        goal._is_in_window = lambda: True
        try:
            result = await goal.run_cycle()
        finally:
            goal._is_in_window = original_window_check
        summary = (result.summary or "(sem summary)")[:500]
        await message.answer(
            f"🧪 <b>Poll forçado concluído</b>\n\n"
            f"<pre>{summary}</pre>\n\n"
            f"<i>success={result.success} · cost=${result.cost_usd:.4f}</i>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        log.exception("[wa_config] _do_test_poll falhou")
        await message.answer(
            f"❌ Erro ao forçar poll: <code>{e}</code>",
            parse_mode=ParseMode.HTML,
        )
