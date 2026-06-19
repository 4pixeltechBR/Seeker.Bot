import os
import json
import logging
from aiogram import Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from src.core.pipeline import SeekerPipeline

log = logging.getLogger("seeker.telegram.radar")

UFS = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas",
    "BA": "Bahia", "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo",
    "GO": "Goiás", "MA": "Maranhão", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul",
    "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
    "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina",
    "SP": "São Paulo", "SE": "Sergipe", "TO": "Tocantins"
}
NAME_TO_UF = {v: k for k, v in UFS.items()}

def get_radar_goal(pipeline: SeekerPipeline, dp: Dispatcher):
    # Busca em pipeline._goals
    if hasattr(pipeline, '_goals') and pipeline._goals:
        for g in pipeline._goals:
            if hasattr(g, 'name') and g.name == 'event_radar':
                return g
    # Busca em scheduler
    scheduler = dp.get("scheduler")
    if scheduler and hasattr(scheduler, '_goals'):
        for g in scheduler._goals.values():
            if hasattr(g, 'name') and g.name == 'event_radar':
                return g
    return None

def setup_radar_handlers(dp: Dispatcher, pipeline: SeekerPipeline):

    def build_radar_menu(state: dict):
        is_paused = state.get("user_paused", False)
        uf_atual = state.get("uf", "GO")
        estado_nome = state.get("estado_alvo", "Goiás")
        cidade_atual = state.get("cidade_atual", "Nenhuma")
        pendentes = len(state.get("cidades_pendentes", []))
        
        status_text = "⏸️ PAUSADO" if is_paused else "🟢 RODANDO"
        pause_btn_text = "▶️ Retomar Varredura" if is_paused else "⏸️ Pausar Varredura"
        
        text = (
            f"<b>🗺️ EventRadar — Configurações</b>\n\n"
            f"<b>Status:</b> {status_text}\n"
            f"<b>Estado Alvo:</b> {estado_nome} ({uf_atual})\n"
            f"<b>Cidade Atual:</b> {cidade_atual}\n"
            f"<b>Restantes na Fila:</b> {pendentes}\n\n"
            f"<i>Selecione um novo Estado abaixo para reiniciar a varredura, ou pause a execução atual.</i>"
        )
        
        buttons = []
        # Botão de Pausa/Retoma + Estados Mapeados
        buttons.append([
            InlineKeyboardButton(text=pause_btn_text, callback_data="radar_toggle_pause"),
            InlineKeyboardButton(text="📊 Estados Mapeados", callback_data="radar_mapped"),
        ])

        # Botões de UF (4 por linha)
        row = []
        for uf, nome in UFS.items():
            check = "✅ " if uf == uf_atual else ""
            row.append(InlineKeyboardButton(text=f"{check}{uf}", callback_data=f"radar_set_uf:{uf}"))
            if len(row) == 4:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
            
        return text, InlineKeyboardMarkup(inline_keyboard=buttons)


    @dp.message(F.text == "/radar")
    async def cmd_radar(message: Message):
        goal = get_radar_goal(pipeline, dp)
        if not goal:
            await message.answer("❌ Goal EventRadar não encontrado no sistema.")
            return
            
        state = goal._load_state_file()
        text, markup = build_radar_menu(state)
        await message.answer(text, reply_markup=markup, parse_mode=ParseMode.HTML)


    @dp.callback_query(F.data == "radar_toggle_pause")
    async def cb_radar_toggle_pause(query: CallbackQuery):
        goal = get_radar_goal(pipeline, dp)
        if not goal:
            await query.answer("❌ Goal EventRadar não encontrado.", show_alert=True)
            return
            
        state = goal._load_state_file()
        is_paused = state.get("user_paused", False)
        
        # Toggle
        state["user_paused"] = not is_paused
        goal._save_state_file(state)
        
        # Update menu
        text, markup = build_radar_menu(state)
        await query.message.edit_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        
        action = "pausado" if not is_paused else "retomado"
        await query.answer(f"EventRadar {action} com sucesso!")


    @dp.callback_query(F.data.startswith("radar_set_uf:"))
    async def cb_radar_set_uf(query: CallbackQuery):
        goal = get_radar_goal(pipeline, dp)
        if not goal:
            await query.answer("❌ Goal EventRadar não encontrado.", show_alert=True)
            return
            
        new_uf = query.data.split(":")[1]
        if new_uf not in UFS:
            await query.answer("❌ UF inválida.", show_alert=True)
            return
            
        state = goal._load_state_file()
        
        if state.get("uf") == new_uf:
            await query.answer(f"O estado já é {new_uf}.", show_alert=True)
            return
            
        # Reseta o estado para a nova UF
        state["uf"] = new_uf
        state["estado_alvo"] = UFS[new_uf]
        state["cidade_atual"] = None
        state["cidades_pendentes"] = []
        state["finalizado"] = False
        # Mantém o user_paused igual
        
        goal._save_state_file(state)

        # Update menu
        text, markup = build_radar_menu(state)
        await query.message.edit_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        await query.answer(f"Estado alterado para {new_uf}. A fila de cidades foi resetada!")


    @dp.callback_query(F.data == "radar_mapped")
    async def cb_radar_mapped(query: CallbackQuery):
        goal = get_radar_goal(pipeline, dp)
        if not goal:
            await query.answer("❌ Goal EventRadar não encontrado.", show_alert=True)
            return

        from src.skills.event_radar.query import EventQuery
        q = EventQuery()
        all_events = q.all()
        total_eventos = len(all_events)
        total_cidades = len({e.get("cidade") for e in all_events if e.get("cidade")})

        names = goal.mapped_state_names()
        state = goal._load_state_file()
        uf_atual = state.get("uf", "")
        finalizado = state.get("finalizado", False)

        mapped_ufs = set()
        mapped_lines = []
        for nome in names:
            uf = NAME_TO_UF.get(nome)
            if not uf:
                continue
            mapped_ufs.add(uf)
            if uf == uf_atual and not finalizado:
                mapped_lines.append(f"🔄 <b>{nome} ({uf})</b> <i>(em andamento)</i>")
            else:
                mapped_lines.append(f"✅ <b>{nome} ({uf})</b>")

        restantes = [uf for uf in UFS if uf not in mapped_ufs]

        if not mapped_lines:
            corpo = "Nenhum estado mapeado ainda."
        else:
            n = len(mapped_lines)
            total_ufs = len(UFS)
            corpo = (
                f"<b>Estados varridos ({n}/{total_ufs}):</b>\n"
                + "\n".join(mapped_lines)
            )
            if restantes:
                corpo += f"\n\n<b>Ainda não mapeados:</b>\n<i>{', '.join(restantes)}</i>"

        text = (
            f"<b>📊 Cobertura do EventRadar</b>\n\n"
            f"{total_eventos} eventos mapeados em {total_cidades} cidades.\n\n"
            f"{corpo}"
        )

        back_btn = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="⬅️ Voltar", callback_data="radar_back")
        ]])
        await query.message.edit_text(text, reply_markup=back_btn, parse_mode=ParseMode.HTML)
        await query.answer()


    @dp.callback_query(F.data == "radar_back")
    async def cb_radar_back(query: CallbackQuery):
        goal = get_radar_goal(pipeline, dp)
        if not goal:
            await query.answer("❌ Goal EventRadar não encontrado.", show_alert=True)
            return

        state = goal._load_state_file()
        text, markup = build_radar_menu(state)
        await query.message.edit_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
        await query.answer()
