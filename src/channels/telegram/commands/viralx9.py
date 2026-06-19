import logging

from aiogram import Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from src.core.pipeline import SeekerPipeline
from src.skills.viralx9 import store
from src.skills.viralx9.bridge import create_project_async

log = logging.getLogger("seeker.telegram.viralx9")


def get_viralx9_goal(pipeline: SeekerPipeline, dp: Dispatcher):
    if hasattr(pipeline, "_goals") and pipeline._goals:
        for g in pipeline._goals:
            if hasattr(g, "name") and g.name == "viralx9":
                return g
    scheduler = dp.get("scheduler")
    if scheduler and hasattr(scheduler, "_goals"):
        for g in scheduler._goals.values():
            if hasattr(g, "name") and g.name == "viralx9":
                return g
    return None


def _replace_candidate_row(
    query: CallbackQuery, cand_id: str, new_label: str
) -> InlineKeyboardMarkup | None:
    """
    Reconstrói o teclado da mensagem (que lista vários candidatos), substituindo
    APENAS a linha do candidato acionado por um botão de status inerte (vx9_done).
    Preserva os botões dos demais candidatos — por isso editamos o teclado, e não o
    texto, que apagaria todos. Retorna None se não houver teclado.
    """
    markup = query.message.reply_markup
    if not markup or not markup.inline_keyboard:
        return None

    targets = {f"vx9_ok:{cand_id}", f"vx9_no:{cand_id}"}
    new_rows: list[list[InlineKeyboardButton]] = []
    for row in markup.inline_keyboard:
        matched = next((btn for btn in row if btn.callback_data in targets), None)
        if matched is not None:
            # Preserva o número do tema (prefixo "N ") no botão de status, p/ manter
            # o mapeamento com a lista numerada da mensagem.
            first_tok = (matched.text or "").split(" ", 1)[0]
            prefix = f"{first_tok} " if first_tok.isdigit() else ""
            new_rows.append([InlineKeyboardButton(text=f"{prefix}{new_label}", callback_data="vx9_done")])
        else:
            new_rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=new_rows)


async def _update_row(query: CallbackQuery, cand_id: str, label: str) -> None:
    markup = _replace_candidate_row(query, cand_id, label)
    if markup is not None:
        try:
            await query.message.edit_reply_markup(reply_markup=markup)
        except Exception as e:
            log.debug(f"[viralx9] edit_reply_markup falhou (provavelmente inalterado): {e}")


_REGIAO_FLAG = {"br": "🇧🇷", "us": "🌎", "eu": "🇪🇺", "asia": "🌏"}


def setup_viralx9_handlers(dp: Dispatcher, pipeline: SeekerPipeline):

    @dp.message(F.text.startswith("/viralx9"))
    async def cmd_viralx9(message):
        """Curadoria: lista os canais que o Seeker monitora.

        /viralx9            → resumo por nicho + fila de candidatos
        /viralx9 <nicho>    → lista os canais daquele nicho
        """
        from src.skills.viralx9.goal import WINDOWS, _load_channels

        cfg = _load_channels()
        parts = (message.text or "").split(maxsplit=1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        # Detalhe de um nicho
        if arg:
            nicho = arg if arg in cfg else None
            if not nicho:
                await message.answer(
                    "Nicho inválido. Opções:\n" + "\n".join(f"• <code>{n}</code>" for n in cfg),
                    parse_mode=ParseMode.HTML,
                )
                return
            seed = cfg[nicho].get("seed", [])
            ativos = sum(1 for x in seed if x.get("ativo", True))
            lines = [f"<b>🔭 {nicho} — {ativos}/{len(seed)} ativos</b>\n"]
            for i, x in enumerate(seed, 1):
                flag = _REGIAO_FLAG.get(x.get("regiao"), "🌐")
                pausado = " ⏸️ <i>pausado</i>" if x.get("ativo", True) is False else ""
                lines.append(f"{i}. {flag} {x.get('nome', x.get('url'))}{pausado}")
            sug = cfg[nicho].get("expansao_sugerida", [])
            if sug:
                lines.append(f"\n<i>+{len(sug)} sugeridos (aguardando aprovação)</i>")
            lines.append(
                f"\n<i>Gerir:</i> <code>/vx9_pausar {nicho} &lt;n&gt;</code> · "
                f"<code>/vx9_ativar {nicho} &lt;n&gt;</code> · <code>/vx9_remover {nicho} &lt;n&gt;</code>"
            )
            await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)
            return

        # Resumo geral
        state = store.load_state()
        cands = state.get("candidatos", {})
        pend = sum(1 for c in cands.values() if c.get("status") == "pending")
        appr = sum(1 for c in cands.values() if c.get("status") == "approved")
        rej = sum(1 for c in cands.values() if c.get("status") == "rejected")

        lines = ["<b>🔭 ViralX9 — Curadoria de Canais Monitorados</b>\n"]
        total = 0
        for nicho, c in cfg.items():
            seed = c.get("seed", [])
            total += len(seed)
            intl = sum(1 for x in seed if x.get("regiao") != "br")
            br = sum(1 for x in seed if x.get("regiao") == "br")
            sug = len(c.get("expansao_sugerida", []))
            extra = f" · +{sug} sugeridos" if sug else ""
            lines.append(f"• <b>{nicho}</b>: {len(seed)} ({intl} intl + {br} BR){extra}")

        lines.append(f"\n<b>Total monitorado:</b> {total} canais")
        lines.append(f"<b>Janelas:</b> {', '.join(WINDOWS)} BRT (2×/dia)")
        lines.append(f"<b>Fila:</b> {pend} pendentes · {appr} aprovados · {rej} rejeitados")
        lines.append("\n<i>Detalhe de um nicho:</i> <code>/viralx9 microbiologia_ia</code>")
        await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)

    async def _mutate_channel(message, action: str):
        """pausar | ativar | remover um canal da seed pelo índice mostrado em /viralx9 <nicho>."""
        from src.skills.viralx9.goal import _load_channels, _save_channels

        parts = (message.text or "").split()
        if len(parts) < 3:
            await message.answer(
                f"Uso: <code>/vx9_{action} &lt;nicho&gt; &lt;n&gt;</code>\n"
                "Veja o índice (n) em <code>/viralx9 &lt;nicho&gt;</code>.",
                parse_mode=ParseMode.HTML,
            )
            return

        nicho = parts[1]
        cfg = _load_channels()
        if nicho not in cfg:
            await message.answer("Nicho inválido: " + ", ".join(f"<code>{n}</code>" for n in cfg), parse_mode=ParseMode.HTML)
            return
        try:
            n = int(parts[2])
        except ValueError:
            await message.answer("O índice <n> deve ser um número.", parse_mode=ParseMode.HTML)
            return

        seed = cfg[nicho].get("seed", [])
        if not (1 <= n <= len(seed)):
            await message.answer(f"Índice fora do intervalo (1..{len(seed)}).")
            return

        canal = seed[n - 1]
        nome = canal.get("nome", canal.get("url"))

        if action == "pausar":
            canal["ativo"] = False
            verbo = "⏸️ Pausado (o miner vai ignorá-lo)"
        elif action == "ativar":
            canal["ativo"] = True
            verbo = "▶️ Reativado"
        else:  # remover
            seed.pop(n - 1)
            cfg[nicho]["seed"] = seed
            verbo = "🗑️ Removido da seed"

        _save_channels(cfg)
        suffix = "\n<i>Os índices podem ter mudado — rode /viralx9 " + nicho + " de novo.</i>" if action == "remover" else ""
        await message.answer(f"{verbo}: <b>{nome}</b> ({nicho}){suffix}", parse_mode=ParseMode.HTML)

    @dp.message(F.text.startswith("/vx9_pausar"))
    async def cmd_vx9_pausar(message):
        await _mutate_channel(message, "pausar")

    @dp.message(F.text.startswith("/vx9_ativar"))
    async def cmd_vx9_ativar(message):
        await _mutate_channel(message, "ativar")

    @dp.message(F.text.startswith("/vx9_remover"))
    async def cmd_vx9_remover(message):
        await _mutate_channel(message, "remover")

    @dp.callback_query(F.data == "vx9_done")
    async def cb_vx9_done(query: CallbackQuery):
        await query.answer("Item já processado.")

    @dp.callback_query(F.data.startswith("vx9_ok:"))
    async def cb_vx9_approve(query: CallbackQuery):
        cand_id = query.data.split(":", 1)[1]
        state = store.load_state()
        candidatos = state.get("candidatos", {})
        cand = candidatos.get(cand_id)

        if not cand:
            await query.answer("❌ Candidato não encontrado (estado reiniciado?).", show_alert=True)
            return

        if cand.get("status") == "approved":
            await query.answer("Já aprovado.", show_alert=True)
            return

        await query.answer("Criando projeto na curadoria...")

        result = await create_project_async(cand)

        if not result.get("success"):
            error = result.get("error", "erro desconhecido")
            log.error(f"[viralx9] Falha ao criar projeto p/ candidato {cand_id}: {error}")
            await _update_row(query, cand_id, f"⚠️ Falha: {cand['tema'][:30]}")
            await query.answer(f"Falha ao criar: {error}", show_alert=True)
            return

        cand["status"] = "approved"
        cand["project_id"] = result.get("projectId")
        candidatos[cand_id] = cand
        store.save_state(state)

        await _update_row(query, cand_id, f"✅ Na curadoria: {cand['tema'][:30]}")

    @dp.callback_query(F.data.startswith("vx9_no:"))
    async def cb_vx9_reject(query: CallbackQuery):
        cand_id = query.data.split(":", 1)[1]
        state = store.load_state()
        candidatos = state.get("candidatos", {})
        cand = candidatos.get(cand_id)

        if not cand:
            await query.answer("❌ Candidato não encontrado (estado reiniciado?).", show_alert=True)
            return

        cand["status"] = "rejected"
        candidatos[cand_id] = cand
        store.save_state(state)

        await _update_row(query, cand_id, f"❌ Descartado: {cand['tema'][:30]}")
        await query.answer("Descartado.")

    @dp.callback_query(F.data.startswith("vx9_add:"))
    async def cb_vx9_add_channel(query: CallbackQuery):
        chan_hash = query.data.split(":", 1)[1]
        state = store.load_state()
        sugeridos = state.get("canais_sugeridos", {})
        sugestao = sugeridos.get(chan_hash)

        if not sugestao:
            await query.answer("❌ Sugestão não encontrada (estado reiniciado?).", show_alert=True)
            return

        if sugestao.get("status") == "added":
            await query.answer("Canal já monitorado.", show_alert=True)
            return

        from src.skills.viralx9.goal import _load_channels, _save_channels

        try:
            cfg = _load_channels()
        except Exception as e:
            await query.answer(f"Erro ao ler config: {e}", show_alert=True)
            return

        nicho = sugestao["nicho"]
        cfg.setdefault(nicho, {}).setdefault("seed", []).append(
            {
                "nome": sugestao.get("nome") or sugestao.get("canal") or sugestao["url"],
                "url": sugestao["url"],
                "regiao": sugestao.get("regiao", "us"),
            }
        )
        _save_channels(cfg)

        sugestao["status"] = "added"
        sugeridos[chan_hash] = sugestao
        store.save_state(state)

        await query.message.edit_text(
            f"➕ <b>Canal monitorado</b>\n{sugestao['url']} ({nicho})",
            parse_mode=ParseMode.HTML,
        )
        await query.answer("Adicionado à seed.")
