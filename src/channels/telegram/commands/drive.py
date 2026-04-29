import os
import asyncio
from aiogram import Router, F, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from src.skills.drive_manager.client import DriveClient

drive_router = Router()
drive_client = DriveClient()

_auth_waiting = {}
_upload_pending = {}

def build_drive_kb(files, current_folder_id="root", parent_id=None):
    keyboard = []
    # Add navigation back
    if current_folder_id != "root":
        keyboard.append([InlineKeyboardButton(text="⬆️ Voltar", callback_data=f"drive_nav:{parent_id or 'root'}")])
    
    # List files and folders
    for f in files:
        name = f.get("name", "Unknown")
        fid = f.get("id")
        is_folder = f.get("mimeType") == "application/vnd.google-apps.folder"
        icon = "📁" if is_folder else "📄"
        
        row = [InlineKeyboardButton(text=f"{icon} {name}", callback_data=f"drive_nav:{fid}" if is_folder else f"drive_file:{fid}")]
        keyboard.append(row)
        
    # Actions
    keyboard.append([
        InlineKeyboardButton(text="➕ Nova Pasta", callback_data=f"drive_mkdir:{current_folder_id}"),
        InlineKeyboardButton(text="⬆️ Upload", callback_data=f"drive_up:{current_folder_id}")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def build_file_kb(file_id, folder_id):
    keyboard = [
        [InlineKeyboardButton(text="⬇️ Download", callback_data=f"drive_dl:{file_id}")],
        [InlineKeyboardButton(text="🗑️ Deletar", callback_data=f"drive_del:{file_id}")],
        [InlineKeyboardButton(text="🔙 Voltar", callback_data=f"drive_nav:{folder_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

@drive_router.message(Command("drive"))
async def cmd_drive(message: Message):
    user_id = message.from_user.id
    
    async def send_link(msg_text):
        await message.answer(msg_text, parse_mode="HTML")
        _auth_waiting[user_id] = True

    if not drive_client.is_authenticated():
        auth_ok = await drive_client.authenticate(send_link)
        if not auth_ok:
            return
            
    await list_folder_ui(message, "root")

async def list_folder_ui(message: Message | CallbackQuery, folder_id: str):
    files = await drive_client.list_folder(folder_id)
    info = await drive_client.get_info(folder_id) if folder_id != "root" else {}
    parent_id = info.get("parents", ["root"])[0] if folder_id != "root" else "root"
    
    kb = build_drive_kb(files, folder_id, parent_id)
    text = "📂 <b>Google Drive</b>"
    if folder_id != "root":
        text = f"📂 <b>{info.get('name', 'Pasta')}</b>"
    
    if isinstance(message, Message):
        await message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await message.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@drive_router.callback_query(F.data.startswith("drive_nav:"))
async def cq_drive_nav(callback: CallbackQuery):
    folder_id = callback.data.split(":")[1]
    await list_folder_ui(callback, folder_id)
    await callback.answer()

@drive_router.callback_query(F.data.startswith("drive_file:"))
async def cq_drive_file(callback: CallbackQuery):
    file_id = callback.data.split(":")[1]
    info = await drive_client.get_info(file_id)
    parent_id = info.get("parents", ["root"])[0]
    
    name = info.get("name", "Arquivo")
    size = info.get("size", "Desconhecido")
    link = info.get("webViewLink", "")
    
    text = f"📄 <b>{name}</b>\nTamanho: {size} bytes\n<a href='{link}'>🔗 Link</a>"
    kb = build_file_kb(file_id, parent_id)
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@drive_router.callback_query(F.data.startswith("drive_del:"))
async def cq_drive_del(callback: CallbackQuery):
    file_id = callback.data.split(":")[1]
    info = await drive_client.get_info(file_id)
    parent_id = info.get("parents", ["root"])[0]
    
    await drive_client.delete(file_id)
    await callback.answer("✅ Arquivo movido para lixeira!")
    await list_folder_ui(callback, parent_id)

@drive_router.callback_query(F.data.startswith("drive_dl:"))
async def cq_drive_dl(callback: CallbackQuery):
    file_id = callback.data.split(":")[1]
    await callback.answer("Baixando...", show_alert=False)
    try:
        data, name = await drive_client.download_file(file_id)
        from aiogram.types import BufferedInputFile
        doc = BufferedInputFile(data, filename=name)
        await callback.message.answer_document(doc)
    except Exception as e:
        await callback.message.answer(f"❌ Erro: {e}")

@drive_router.callback_query(F.data.startswith("drive_up:"))
async def cq_drive_up(callback: CallbackQuery):
    folder_id = callback.data.split(":")[1]
    _upload_pending[callback.from_user.id] = folder_id
    await callback.message.answer("Envie o arquivo ou foto agora. (Para cancelar envie /cancelar)")
    await callback.answer()

@drive_router.callback_query(F.data.startswith("drive_mkdir:"))
async def cq_drive_mkdir(callback: CallbackQuery):
    folder_id = callback.data.split(":")[1]
    _upload_pending[callback.from_user.id] = f"mkdir:{folder_id}"
    await callback.message.answer("Envie o nome da nova pasta. (Para cancelar envie /cancelar)")
    await callback.answer()

@drive_router.message(F.text)
async def handle_text_intercepts(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()
    
    # Flow de Auth OAuth
    if user_id in _auth_waiting:
        if text.startswith("/") and text.lower() not in ("/cancelar",):
            return
        
        if text.lower() == "/cancelar":
            _auth_waiting.pop(user_id, None)
            await message.answer("❌ Autenticação cancelada.")
            return
            
        success = await drive_client.complete_auth(text)
        if success:
            _auth_waiting.pop(user_id, None)
            await message.answer("✅ Autenticação concluída! Tente /drive novamente.")
        else:
            await message.answer("❌ Falha na autenticação. Verifique o código e envie novamente ou /cancelar.")
        return

    # Flow de Criar Pasta
    if user_id in _upload_pending:
        val = _upload_pending[user_id]
        if isinstance(val, str) and val.startswith("mkdir:"):
            if text.startswith("/") and text.lower() not in ("/cancelar",):
                return
            
            parent_id = val.split(":")[1]
            _upload_pending.pop(user_id, None)
            
            if text.lower() == "/cancelar":
                await message.answer("❌ Criação de pasta cancelada.")
                return
                
            res = await drive_client.create_folder(text, parent_id)
            await message.answer(f"✅ Pasta <b>{res.get('name')}</b> criada!", parse_mode="HTML")
            await list_folder_ui(message, parent_id)
            return

@drive_router.message(F.document | F.photo | F.video | F.audio)
async def handle_upload(message: Message):
    user_id = message.from_user.id
    if user_id in _upload_pending:
        val = _upload_pending[user_id]
        if isinstance(val, str) and not val.startswith("mkdir:"):
            folder_id = val
            _upload_pending.pop(user_id, None)
            
            status_msg = await message.answer("⏳ Baixando do Telegram e enviando para o Drive...")
            
            if message.document:
                fid = message.document.file_id
                fname = message.document.file_name
            elif message.photo:
                fid = message.photo[-1].file_id
                fname = "photo.jpg"
            elif message.video:
                fid = message.video.file_id
                fname = message.video.file_name or "video.mp4"
            elif message.audio:
                fid = message.audio.file_id
                fname = message.audio.file_name or "audio.mp3"
            else:
                return
                
            file_info = await message.bot.get_file(fid)
            downloaded = await message.bot.download_file(file_info.file_path)
            data = downloaded.read()
            
            res = await drive_client.upload_bytes(data, fname, folder_id)
            await status_msg.edit_text(f"✅ Upload concluído!\n<a href='{res.get('webViewLink')}'>Ver Arquivo</a>", parse_mode="HTML")
            await list_folder_ui(message, folder_id)

def setup_drive_handlers(dp: Dispatcher, pipeline=None):
    dp.include_router(drive_router)
