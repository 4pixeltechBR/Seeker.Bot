import logging
from aiogram import Dispatcher, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.enums import ParseMode
from src.core.pipeline import SeekerPipeline
from src.skills.vision.afk_protocol import AFKProtocol

log = logging.getLogger("seeker.telegram.vision")

def setup_vision_handlers(dp: Dispatcher, pipeline: SeekerPipeline):
    @dp.message(F.text == "/watch")
    async def cmd_watch(message: Message):
        scheduler = dp.get("scheduler")
        if not scheduler:
            await message.answer("Scheduler não inicializado.")
            return
        # Procura o goal desktop_watch
        watch_goal = scheduler._goals.get("desktop_watch")
        if not watch_goal:
            await message.answer("Desktop Watch não está registrado.")
            return
        watch_goal.enable()
        await message.answer(
            "👁️ <b>Desktop Watch ATIVADO</b>\n\n"
            "Estou monitorando sua tela a cada 2 minutos.\n"
            "Você será notificado se algo precisar de atenção.\n\n"
            "<i>Use /watchoff para desativar.</i>",
            parse_mode=ParseMode.HTML,
        )

    @dp.message(F.text == "/watchoff")
    async def cmd_watchoff(message: Message):
        scheduler = dp.get("scheduler")
        if not scheduler:
            await message.answer("Scheduler não inicializado.")
            return
        watch_goal = scheduler._goals.get("desktop_watch")
        if not watch_goal:
            await message.answer("Desktop Watch não está registrado.")
            return
        scans = watch_goal._scans_total
        alerts = watch_goal._alerts_sent
        watch_goal.disable()
        await message.answer(
            "👁️ <b>Desktop Watch DESATIVADO</b>\n\n"
            f"Sessão: {scans} scans, {alerts} alertas.\n"
            "<i>Use /watch para reativar.</i>",
            parse_mode=ParseMode.HTML,
        )

    @dp.message(F.text == "/print")
    async def cmd_print(message: Message):
        status_msg = await message.answer("📸 Capturando tela...")
        try:
            from src.skills.vision.screenshot import capture_desktop
            from aiogram.types import BufferedInputFile
            
            screenshot_bytes = await capture_desktop()
            if not screenshot_bytes:
                await status_msg.edit_text("Falha ao capturar a tela.")
                return
                
            photo = BufferedInputFile(screenshot_bytes, filename="print.png")
            await message.bot.send_photo(
                chat_id=message.chat.id,
                photo=photo,
                caption="📸 Aqui está a sua tela atual."
            )
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit_text(f"Erro no print: {e}")


    # ────────────────────────────────────────────────────────────────
    # Remote Executor Approval Callbacks (L0_MANUAL actions)
    # ────────────────────────────────────────────────────────────────

    @dp.callback_query(F.data.startswith("vis_auth_"))
    async def handle_vision_auth(callback: CallbackQuery):
        # Example data: vis_auth_yes_2
        parts = callback.data.split("_")
        if len(parts) >= 3:
            result = parts[2] # "yes" or "no"
            tier = parts[3] if len(parts) > 3 else "2"
            
            # Buscando o AFK Protocol no Dispatcher (setado no start)
            afk_protocol = dp.get("afk_protocol")
            if afk_protocol:
                await afk_protocol.resolve_request(result, tier)
                
            await callback.message.edit_text(
                f"{callback.message.text}\n\n<b>➔ Resposta do Usuário: {'✅ Autorizado' if result == 'yes' else '❌ Negado'}</b>"
            )
        await callback.answer()

    # ────────────────────────────────────────────────────────
    # Scheduler Conversacional Commands
    # ────────────────────────────────────────────────────────
