"""
Legacy Commands Plugin for Seeker Agent

Reativando os comandos do antigo Seeker.Bot sob a nova arquitetura do Seeker Agent.
Fase 1: SenseNews, AFK Protocol e EventRadar com botões virtuais Inline interativos (InlineKeyboardMarkup).
"""

import os
import sys
import json
import time
import logging
import asyncio
import sqlite3
from pathlib import Path
from typing import Optional

# Adiciona o diretório raiz do projeto ao sys.path para carregar o pacote src
project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / "seeker_agent" / ".env")

logger = logging.getLogger("seeker.plugin.legacy_commands")

# Tenta carregar biblioteca do telegram para teclados interativos
try:
    from telegram import (
        ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
        InlineKeyboardMarkup, InlineKeyboardButton, Bot
    )
    from telegram.constants import ParseMode
    TELEGRAM_LIBS_AVAILABLE = True
except ImportError:
    ReplyKeyboardMarkup = None
    KeyboardButton = None
    ReplyKeyboardRemove = None
    InlineKeyboardMarkup = None
    InlineKeyboardButton = None
    Bot = None
    ParseMode = None
    TELEGRAM_LIBS_AVAILABLE = False

# Globais de estado do plugin
pipeline = None
sense_news_goal = None
event_radar_goal = None
desktop_watch_goal = None
init_lock = None
telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
telegram_chat_id = os.getenv("TELEGRAM_ALLOWED_USERS", "").split(",")[0].strip()

# Caminho para persistência de estado do plugin
legacy_state_path = project_root / "data" / "legacy_goals_state.json"

# Dicionário de UFs suportado pelo EventRadar
UFS = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas",
    "BA": "Bahia", "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo",
    "GO": "Goiás", "MA": "Maranhão", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul",
    "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
    "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina",
    "SP": "São Paulo", "SE": "Sergipe", "TO": "Tocantins"
}

# Mapeamento para configuração simplificada de nichos do SenseNews
NICHES_MAP = {
    "modelos": "MODELOS & OPEN-WEIGHT",
    "open": "MODELOS & OPEN-WEIGHT",
    "weight": "MODELOS & OPEN-WEIGHT",
    "infra": "INFRA & OTIMIZAÇÃO",
    "otimização": "INFRA & OTIMIZAÇÃO",
    "otimizacao": "INFRA & OTIMIZAÇÃO",
    "agentes": "AGENTES & AUTOMAÇÃO",
    "automação": "AGENTES & AUTOMAÇÃO",
    "automacao": "AGENTES & AUTOMAÇÃO",
    "criação": "CRIAÇÃO & CONTEÚDO",
    "criacao": "CRIAÇÃO & CONTEÚDO",
    "conteúdo": "CRIAÇÃO & CONTEÚDO",
    "conteudo": "CRIAÇÃO & CONTEÚDO"
}

# ---------------------------------------------------------------------------
# Helpers de Persistência e Notificação
# ---------------------------------------------------------------------------

def load_legacy_state() -> dict:
    if legacy_state_path.exists():
        try:
            with open(legacy_state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.debug(f"Erro ao ler legacy_goals_state.json: {e}")
    return {}

def save_legacy_state(state: dict):
    try:
        legacy_state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(legacy_state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=4)
    except Exception as e:
        logger.error(f"Erro ao salvar legacy_goals_state.json: {e}")

async def send_telegram_notification(message: str, media_files: list = None):
    if not telegram_token or not telegram_chat_id:
        logger.warning("Envio de notificação ignorado: Token ou Chat ID ausente no .env.")
        return
    try:
        from tools.send_message_tool import _send_telegram
        await _send_telegram(
            token=telegram_token,
            chat_id=telegram_chat_id,
            message=message,
            media_files=media_files or []
        )
    except Exception as e:
        logger.error(f"Falha ao enviar notificação via Telegram: {e}")

async def send_telegram_reply(text: str, reply_markup=None) -> bool:
    """Envia uma resposta rica diretamente para a sessão do usuário do Telegram se aplicável."""
    if not TELEGRAM_LIBS_AVAILABLE or not telegram_token:
        return False
    try:
        from gateway.session_context import get_session_env
        platform = get_session_env("HERMES_SESSION_PLATFORM")
        
        # Só prossegue se a chamada for originada do Telegram
        if platform != "telegram":
            return False
            
        chat_id = get_session_env("HERMES_SESSION_CHAT_ID")
        if not chat_id:
            chat_id = get_session_env("HERMES_SESSION_USER_ID")
        if not chat_id:
            chat_id = telegram_chat_id
            
        if not chat_id:
            logger.warning("Não foi possível identificar o chat_id para responder no Telegram.")
            return False
            
        thread_id = get_session_env("HERMES_SESSION_THREAD_ID")
        
        send_kwargs = {
            "chat_id": int(chat_id),
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": ParseMode.MARKDOWN
        }
        
        # Só define thread_id se for diferente de 1 (tópico 'General' ou fora de fóruns)
        if thread_id and str(thread_id) != "1":
            send_kwargs["message_thread_id"] = int(thread_id)
            
        async with Bot(token=telegram_token) as bot:
            await bot.send_message(**send_kwargs)
        return True
    except Exception as e:
        logger.error(f"Falha ao enviar resposta direta via Telegram: {e}", exc_info=True)
        return False

# ---------------------------------------------------------------------------
# Background loops (Goal execution)
# ---------------------------------------------------------------------------

async def sense_news_loop():
    logger.info("Iniciando background loop do SenseNews...")
    while True:
        try:
            if sense_news_goal:
                result = await sense_news_goal.run_cycle()
                if result and result.notification:
                    logger.info("SenseNews cycle executado com novas análises!")
                    pdf_path = result.data.get("pdf_path") if result.data else None
                    if pdf_path and os.path.exists(pdf_path):
                        await send_telegram_notification(result.notification, media_files=[pdf_path])
                    else:
                        await send_telegram_notification(result.notification)
                    
                    all_states = load_legacy_state()
                    all_states["sense_news"] = sense_news_goal.serialize_state()
                    save_legacy_state(all_states)
        except Exception as e:
            logger.error(f"Erro no loop do SenseNews: {e}", exc_info=True)
        
        await asyncio.sleep(60)

async def event_radar_loop():
    logger.info("Iniciando background loop do EventRadar...")
    while True:
        try:
            if event_radar_goal:
                result = await event_radar_goal.run_cycle()
                if result and result.notification:
                    logger.info("EventRadar cycle executado!")
                    await send_telegram_notification(result.notification)
        except Exception as e:
            logger.error(f"Erro no loop do EventRadar: {e}", exc_info=True)
        
        await asyncio.sleep(1800)

async def desktop_watch_loop():
    logger.info("Iniciando background loop do DesktopWatch...")
    last_run_time = 0.0
    while True:
        try:
            if desktop_watch_goal and desktop_watch_goal.is_enabled:
                now = time.time()
                if now - last_run_time >= 120.0:
                    last_run_time = now
                    result = await desktop_watch_goal.run_cycle()
                    if result and result.notification:
                        logger.info("DesktopWatch: Alerta de vigilância gerado!")
                        photo_bytes = result.data.get("photo_bytes") if result.data else None
                        
                        if photo_bytes:
                            temp_path = project_root / "data" / "screenshot.png"
                            temp_path.parent.mkdir(parents=True, exist_ok=True)
                            with open(temp_path, "wb") as f:
                                f.write(photo_bytes)
                            
                            await send_telegram_notification(result.notification, media_files=[str(temp_path)])
                            
                            try:
                                temp_path.unlink()
                            except Exception:
                                pass
                        else:
                            await send_telegram_notification(result.notification)
                        
                        all_states = load_legacy_state()
                        all_states["desktop_watch"] = desktop_watch_goal.serialize_state()
                        save_legacy_state(all_states)
        except Exception as e:
            logger.error(f"Erro no loop do DesktopWatch: {e}", exc_info=True)
        
        await asyncio.sleep(10)

# ---------------------------------------------------------------------------
# Inicializador da Pipeline e dos Goals
# ---------------------------------------------------------------------------

async def get_init_lock() -> asyncio.Lock:
    global init_lock
    if init_lock is None:
        init_lock = asyncio.Lock()
    return init_lock

async def initialize_pipeline_and_loops():
    global pipeline, sense_news_goal, event_radar_goal, desktop_watch_goal
    lock = await get_init_lock()
    async with lock:
        if pipeline is not None:
            return
            
        try:
            from src.core.pipeline import SeekerPipeline
            
            api_keys = {
                "deepseek": os.getenv("DEEPSEEK_API_KEY", ""),
                "gemini": os.getenv("GEMINI_API_KEY", ""),
                "groq": os.getenv("GROQ_API_KEY", ""),
                "kimi": os.getenv("KIMI_API_KEY", ""),
                "mistral": os.getenv("MISTRAL_API_KEY", ""),
                "nvidia": os.getenv("NVIDIA_API_KEY", ""),
            }
            
            logger.info("Inicializando SeekerPipeline legada...")
            pipeline = SeekerPipeline(api_keys)
            await pipeline.init()
            logger.info("SeekerPipeline inicializada com sucesso!")
            
            from src.skills.sense_news.goal import SenseNewsGoal
            from src.skills.event_radar.goal import EventRadarGoal
            from src.skills.desktop_watch.goal import DesktopWatchGoal
            
            sense_news_goal = SenseNewsGoal(pipeline)
            event_radar_goal = EventRadarGoal(pipeline)
            desktop_watch_goal = DesktopWatchGoal(pipeline)
            
            all_states = load_legacy_state()
            sense_news_goal.load_state(all_states.get("sense_news", {}))
            desktop_watch_goal.load_state(all_states.get("desktop_watch", {}))
            
            asyncio.create_task(sense_news_loop())
            asyncio.create_task(event_radar_loop())
            asyncio.create_task(desktop_watch_loop())
            
            logger.info("Todos os Goals legados e seus loops de background foram iniciados.")
        except Exception as e:
            logger.critical(f"Falha grave ao inicializar a pipeline e os loops legados: {e}", exc_info=True)

# ---------------------------------------------------------------------------
# Lifecycle Hooks
# ---------------------------------------------------------------------------

async def on_session_start_hook(**kwargs):
    if pipeline is None:
        try:
            asyncio.create_task(initialize_pipeline_and_loops())
        except Exception:
            pass

async def on_telegram_callback_hook(query, data: str, adapter, **kwargs):
    """Filtra e distribui cliques de botões inline customizados deste plugin."""
    if not data.startswith("pl:legacy_commands:"):
        return
        
    action_data = data[len("pl:legacy_commands:"):]
    
    if action_data.startswith("news:"):
        nicho = action_data[len("news:"):]
        await handle_news_callback(query, nicho, adapter)
    elif action_data.startswith("radar:"):
        uf_or_action = action_data[len("radar:"):]
        await handle_radar_callback(query, uf_or_action, adapter)

# ---------------------------------------------------------------------------
# Implementação dos Comandos (Slash Handlers)
# ---------------------------------------------------------------------------

async def cmd_configure_news(args: str) -> Optional[str]:
    """Configura nichos ativos do SenseNews."""
    if pipeline is None:
        await initialize_pipeline_and_loops()
        
    try:
        from gateway.session_context import get_session_env
        user_id = get_session_env("HERMES_SESSION_USER_ID")
        platform = get_session_env("HERMES_SESSION_PLATFORM")
    except ImportError:
        user_id = None
        platform = None
        
    if not user_id:
        user_id = telegram_chat_id
        
    if not user_id:
        return "❌ Erro: Não foi possível identificar o ID do usuário da sessão atual."

    db_path = project_root / "data" / "seeker_memory.db"
    
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id INTEGER PRIMARY KEY,
                telegram_id TEXT,
                niches TEXT,
                updated_at REAL
            )
        """)
        conn.commit()
    except Exception as e:
        return f"❌ Erro ao conectar ao banco de dados: {e}"

    nicho_input = args.strip().lower()

    # Carrega preferências do banco
    active_niches = []
    try:
        cursor.execute("SELECT niches FROM user_preferences WHERE user_id = ? OR telegram_id = ?", (user_id, str(user_id)))
        row = cursor.fetchone()
        if row and row["niches"]:
            active_niches = json.loads(row["niches"])
            if not isinstance(active_niches, list):
                active_niches = []
    except Exception as e:
        conn.close()
        return f"❌ Erro ao ler dados de preferências: {e}"

    # Sem argumentos: Exibe o painel inline no Telegram ou texto clássico no CLI
    if not nicho_input:
        conn.close()
        ativos_str = ", ".join(f"✅ *{n}*" for n in active_niches) if active_niches else "_Nenhum_"
        
        if platform == "telegram" and TELEGRAM_LIBS_AVAILABLE:
            msg_text = (
                f"📰 **SenseNews — Configuração de Nichos**\n\n"
                f"**Nichos ativos atualmente:**\n{ativos_str}\n\n"
                f"Selecione os nichos abaixo para alterar suas preferências:"
            )
            
            # Monta teclado inline interativo
            btn_modelos = InlineKeyboardButton(
                f"🧠 Modelos & Open-Weight [{'✅' if 'MODELOS & OPEN-WEIGHT' in active_niches else '☐'}]",
                callback_data="pl:legacy_commands:news:modelos"
            )
            btn_infra = InlineKeyboardButton(
                f"⚡ Infra & Otimização [{'✅' if 'INFRA & OTIMIZAÇÃO' in active_niches else '☐'}]",
                callback_data="pl:legacy_commands:news:infra"
            )
            btn_agentes = InlineKeyboardButton(
                f"🤖 Agentes & Automação [{'✅' if 'AGENTES & AUTOMAÇÃO' in active_niches else '☐'}]",
                callback_data="pl:legacy_commands:news:agentes"
            )
            btn_criacao = InlineKeyboardButton(
                f"🎬 Criação & Conteúdo [{'✅' if 'CRIAÇÃO & CONTEÚDO' in active_niches else '☐'}]",
                callback_data="pl:legacy_commands:news:criacao"
            )
            btn_fechar = InlineKeyboardButton("❌ Fechar Menu", callback_data="pl:legacy_commands:news:fechar")
            
            keyboard = [
                [btn_modelos],
                [btn_infra],
                [btn_agentes],
                [btn_criacao],
                [btn_fechar]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await send_telegram_reply(msg_text, reply_markup=reply_markup)
            return None
        else:
            disponiveis = [
                "- 🧠 `MODELOS & OPEN-WEIGHT` (Benchmarks, releases, open-source)",
                "- ⚡ `INFRA & OTIMIZAÇÃO` (Quantização, inferência rápida)",
                "- 🤖 `AGENTES & AUTOMAÇÃO` (Tool-use, memória, autonomia)",
                "- 🎬 `CRIAÇÃO & CONTEÚDO` (TTS, geração de imagem/vídeo)"
            ]
            disponiveis_str = "\n".join(disponiveis)
            return (
                f"📰 **SenseNews — Configuração de Nichos**\n\n"
                f"**Nichos ativos no seu perfil:**\n{ativos_str}\n\n"
                f"**Nichos disponíveis:**\n{disponiveis_str}\n\n"
                f"Para ativar/desativar um nicho, digite:\n"
                f"`/configure-news [nome_do_nicho]`\n"
                f"*(Exemplo: `/configure-news infra`)*"
            )

    # CLI fallback para comandos passados em texto puro
    matched_niche = None
    for k, v in NICHES_MAP.items():
        if k in nicho_input:
            matched_niche = v
            break
            
    if not matched_niche:
        conn.close()
        return f"❌ Nicho '{args}' não reconhecido. Tente usar palavras-chave como `infra`, `modelos`, `agentes` ou `criação`."

    if matched_niche in active_niches:
        active_niches.remove(matched_niche)
        acao = "removido"
    else:
        active_niches.append(matched_niche)
        acao = "adicionado"

    try:
        sql = """INSERT INTO user_preferences (user_id, telegram_id, niches, updated_at)
                 VALUES (?, ?, ?, ?)
                 ON CONFLICT(user_id) DO UPDATE SET niches = excluded.niches, updated_at = excluded.updated_at"""
        cursor.execute(sql, (int(user_id), str(user_id), json.dumps(active_niches), time.time()))
        conn.commit()
    except Exception as e:
        conn.close()
        return f"❌ Erro ao salvar novas preferências no banco: {e}"

    conn.close()

    ativos_str_cli = ", ".join(f"✅ `{n}`" for n in active_niches) if active_niches else "_Nenhum (SenseNews desativado)_"
    return (
        f"✨ Nicho `{matched_niche}` {acao} com sucesso!\n\n"
        f"**Nichos ativos atualmente:**\n{ativos_str_cli}"
    )

async def cmd_radar(args: str) -> Optional[str]:
    """Configura e controla o Radar de Eventos legada."""
    if pipeline is None:
        await initialize_pipeline_and_loops()

    state_path = project_root / "data" / "event_radar" / "event_radar_state.json"
    
    if not state_path.exists():
        return "❌ Estado do EventRadar não encontrado. Aguarde a inicialização da pipeline ou configure manualmente."

    try:
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception as e:
        return f"❌ Erro ao ler estado do EventRadar: {e}"

    try:
        from gateway.session_context import get_session_env
        platform = get_session_env("HERMES_SESSION_PLATFORM")
    except ImportError:
        platform = None

    # DEBUG LOGGING
    try:
        debug_log_path = project_root / "logs" / "legacy_debug.log"
        debug_log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(debug_log_path, "a", encoding="utf-8") as f_debug:
            f_debug.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] cmd_radar called: platform={repr(platform)}, TELEGRAM_LIBS_AVAILABLE={TELEGRAM_LIBS_AVAILABLE}, has_token={bool(telegram_token)}\n")
    except Exception as deb_err:
        logger.error(f"Failed to write legacy_debug.log: {deb_err}")


    param = args.strip().lower()

    # CLI fallback: controle manual de pausa
    if param == "pause":
        state["user_paused"] = True
        try:
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=4, ensure_ascii=False)
            return "⏸️ **EventRadar PAUSADO.** O processamento de lotes de cidades foi suspenso."
        except Exception as e:
            return f"❌ Erro ao gravar estado do EventRadar: {e}"

    if param in ("resume", "play"):
        state["user_paused"] = False
        try:
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=4, ensure_ascii=False)
            return "🟢 **EventRadar RETOMADO.** A varredura continuará no próximo ciclo agendado."
        except Exception as e:
            return f"❌ Erro ao gravar estado do EventRadar: {e}"

    # CLI fallback: troca de UF
    param_parts = param.split()
    uf_candidate = param_parts[0].upper() if param_parts else ""

    if uf_candidate in UFS:
        state["uf"] = uf_candidate
        state["estado_alvo"] = UFS[uf_candidate]
        state["cidade_atual"] = None
        state["cidades_pendentes"] = []
        state["finalizado"] = False
        
        try:
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=4, ensure_ascii=False)
            return f"🗺️ **Estado alterado para {state['estado_alvo']} ({uf_candidate})**.\nA fila de cidades foi reiniciada."
        except Exception as e:
            return f"❌ Erro ao salvar novo estado do EventRadar: {e}"

    # Sem argumentos: Abre painel inline no Telegram ou cospe texto no CLI
    if not param:
        if platform == "telegram" and TELEGRAM_LIBS_AVAILABLE:
            # Envia o painel com os botões inline correspondentes
            is_paused = state.get("user_paused", False)
            uf_atual = state.get("uf", "GO").upper()
            estado_nome = state.get("estado_alvo", "Goiás")
            cidade_atual = state.get("cidade_atual", "Nenhuma") or "Nenhuma"
            pendentes = len(state.get("cidades_pendentes", []))
            
            status_text = "⏸️ *PAUSADO*" if is_paused else "🟢 *RODANDO*"
            
            msg_text = (
                f"🗺️ **EventRadar — Configurações**\n\n"
                f"**Status:** {status_text}\n"
                f"**Estado Alvo:** {estado_nome} ({uf_atual})\n"
                f"**Cidade Atual:** {cidade_atual}\n"
                f"**Restantes na Fila:** {pendentes}\n\n"
                f"_Selecione um novo Estado abaixo para reiniciar a varredura, ou pause a execução atual._"
            )
            
            control_text = "⏸️ Pausar Varredura" if not is_paused else "🟢 Retomar Varredura"
            control_callback = "pl:legacy_commands:radar:pause" if not is_paused else "pl:legacy_commands:radar:resume"
            control_btn = InlineKeyboardButton(control_text, callback_data=control_callback)
            
            uf_keys = sorted(list(UFS.keys()))
            uf_buttons = []
            current_row = []
            
            for uf in uf_keys:
                text = f"✅ {uf}" if uf == uf_atual else uf
                current_row.append(InlineKeyboardButton(text, callback_data=f"pl:legacy_commands:radar:{uf.lower()}"))
                if len(current_row) == 4:
                    uf_buttons.append(current_row)
                    current_row = []
            if current_row:
                uf_buttons.append(current_row)
                
            final_keyboard = [[control_btn]] + uf_buttons + [[InlineKeyboardButton("❌ Fechar Menu", callback_data="pl:legacy_commands:radar:fechar")]]
            reply_markup = InlineKeyboardMarkup(final_keyboard)
            await send_telegram_reply(msg_text, reply_markup=reply_markup)
            return None
        else:
            is_paused = state.get("user_paused", False)
            uf_atual = state.get("uf", "GO")
            estado_nome = state.get("estado_alvo", "Goiás")
            cidade_atual = state.get("cidade_atual", "Nenhuma")
            pendentes = len(state.get("cidades_pendentes", []))
            status_text = "⏸️ PAUSADO" if is_paused else "🟢 RODANDO"
            return (
                f"🗺️ **EventRadar — Status Atual**\n\n"
                f"**Status:** {status_text}\n"
                f"**Estado Alvo:** {estado_nome} ({uf_atual})\n"
                f"**Cidade Atual:** {cidade_atual}\n"
                f"**Cidades na fila:** {pendentes}\n\n"
                f"**Comandos rápidos:**\n"
                f"- `/radar pause`: Pausa a varredura.\n"
                f"- `/radar resume`: Retoma a varredura.\n"
                f"- `/radar [UF]`: Altera estado alvo (ex: `/radar SP`)."
            )

    return f"❌ Opção ou UF '{args}' inválida. Use `/radar pause`, `/radar resume` ou `/radar [UF]`."

# ---------------------------------------------------------------------------
# Handlers específicos de clicks inline do Telegram
# ---------------------------------------------------------------------------

async def handle_news_callback(query, nicho_input: str, adapter):
    """Manipula cliques inline para preferências do SenseNews."""
    user_id = str(query.from_user.id)
    db_path = project_root / "data" / "seeker_memory.db"
    
    if nicho_input == "fechar":
        await query.answer(text="Menu fechado")
        try:
            await query.edit_message_text(
                text="🚪 **SenseNews**\nConfiguração de nichos finalizada.",
                reply_markup=None,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass
        return

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Lê preferências
        active_niches = []
        cursor.execute("SELECT niches FROM user_preferences WHERE user_id = ? OR telegram_id = ?", (user_id, user_id))
        row = cursor.fetchone()
        if row and row["niches"]:
            active_niches = json.loads(row["niches"])
            if not isinstance(active_niches, list):
                active_niches = []
    except Exception as e:
        await query.answer(text=f"Erro no banco: {e}")
        return

    matched_niche = None
    for k, v in NICHES_MAP.items():
        if k in nicho_input:
            matched_niche = v
            break

    if not matched_niche:
        conn.close()
        await query.answer(text="❌ Opção não reconhecida")
        return

    if matched_niche in active_niches:
        active_niches.remove(matched_niche)
        await query.answer(text=f"Removido: {matched_niche}")
    else:
        active_niches.append(matched_niche)
        await query.answer(text=f"Adicionado: {matched_niche}")

    try:
        sql = """INSERT INTO user_preferences (user_id, telegram_id, niches, updated_at)
                 VALUES (?, ?, ?, ?)
                 ON CONFLICT(user_id) DO UPDATE SET niches = excluded.niches, updated_at = excluded.updated_at"""
        cursor.execute(sql, (int(user_id), str(user_id), json.dumps(active_niches), time.time()))
        conn.commit()
    except Exception as e:
        logger.error(f"Erro ao salvar: {e}")
        
    conn.close()

    # Re-renderiza painel interativo instantaneamente
    ativos_str = ", ".join(f"✅ *{n}*" for n in active_niches) if active_niches else "_Nenhum_"
    msg_text = (
        f"📰 **SenseNews — Configuração de Nichos**\n\n"
        f"**Nichos ativos atualmente:**\n{ativos_str}\n\n"
        f"Selecione os nichos abaixo para alterar suas preferências:"
    )
    
    btn_modelos = InlineKeyboardButton(
        f"🧠 Modelos & Open-Weight [{'✅' if 'MODELOS & OPEN-WEIGHT' in active_niches else '☐'}]",
        callback_data="pl:legacy_commands:news:modelos"
    )
    btn_infra = InlineKeyboardButton(
        f"⚡ Infra & Otimização [{'✅' if 'INFRA & OTIMIZAÇÃO' in active_niches else '☐'}]",
        callback_data="pl:legacy_commands:news:infra"
    )
    btn_agentes = InlineKeyboardButton(
        f"🤖 Agentes & Automação [{'✅' if 'AGENTES & AUTOMAÇÃO' in active_niches else '☐'}]",
        callback_data="pl:legacy_commands:news:agentes"
    )
    btn_criacao = InlineKeyboardButton(
        f"🎬 Criação & Conteúdo [{'✅' if 'CRIAÇÃO & CONTEÚDO' in active_niches else '☐'}]",
        callback_data="pl:legacy_commands:news:criacao"
    )
    btn_fechar = InlineKeyboardButton("❌ Fechar Menu", callback_data="pl:legacy_commands:news:fechar")
    
    keyboard = [
        [btn_modelos],
        [btn_infra],
        [btn_agentes],
        [btn_criacao],
        [btn_fechar]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await query.edit_message_text(
            text=msg_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.warning(f"Erro ao atualizar mensagem: {e}")

async def handle_radar_callback(query, action_data: str, adapter):
    """Manipula cliques inline para preferências do EventRadar."""
    state_path = project_root / "data" / "event_radar" / "event_radar_state.json"
    if not state_path.exists():
        await query.answer(text="❌ Estado do Radar não encontrado")
        return

    try:
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception as e:
        await query.answer(text=f"Erro de arquivo: {e}")
        return

    if action_data == "fechar":
        await query.answer(text="Menu fechado")
        try:
            await query.edit_message_text(
                text="🗺️ **EventRadar**\nConfiguração de varredura finalizada.",
                reply_markup=None,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass
        return

    # Ação de controle: Pausar varredura
    if action_data == "pause":
        state["user_paused"] = True
        try:
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=4, ensure_ascii=False)
            await query.answer(text="⏸️ Radar Pausado")
        except Exception as e:
            await query.answer(text=f"Erro: {e}")
            return
            
    # Ação de controle: Retomar varredura
    elif action_data == "resume":
        state["user_paused"] = False
        try:
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=4, ensure_ascii=False)
            await query.answer(text="🟢 Radar Retomado")
        except Exception as e:
            await query.answer(text=f"Erro: {e}")
            return
            
    # Ação de controle: Alterar estado
    elif action_data.upper() in UFS:
        uf_upper = action_data.upper()
        state["uf"] = uf_upper
        state["estado_alvo"] = UFS[uf_upper]
        state["cidade_atual"] = None
        state["cidades_pendentes"] = []
        state["finalizado"] = False
        try:
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=4, ensure_ascii=False)
            await query.answer(text=f"Varredura definida para {state['estado_alvo']} ({uf_upper})")
        except Exception as e:
            await query.answer(text=f"Erro: {e}")
            return

    # Atualiza painel do EventRadar
    is_paused = state.get("user_paused", False)
    uf_atual = state.get("uf", "GO").upper()
    estado_nome = state.get("estado_alvo", "Goiás")
    cidade_atual = state.get("cidade_atual", "Nenhuma") or "Nenhuma"
    pendentes = len(state.get("cidades_pendentes", []))
    
    status_text = "⏸️ *PAUSADO*" if is_paused else "🟢 *RODANDO*"
    
    msg_text = (
        f"🗺️ **EventRadar — Configurações**\n\n"
        f"**Status:** {status_text}\n"
        f"**Estado Alvo:** {estado_nome} ({uf_atual})\n"
        f"**Cidade Atual:** {cidade_atual}\n"
        f"**Restantes na Fila:** {pendentes}\n\n"
        f"_Selecione um novo Estado abaixo para reiniciar a varredura, ou pause a execução atual._"
    )
    
    control_text = "⏸️ Pausar Varredura" if not is_paused else "🟢 Retomar Varredura"
    control_callback = "pl:legacy_commands:radar:pause" if not is_paused else "pl:legacy_commands:radar:resume"
    control_btn = InlineKeyboardButton(control_text, callback_data=control_callback)
    
    uf_keys = sorted(list(UFS.keys()))
    uf_buttons = []
    current_row = []
    
    for uf in uf_keys:
        text = f"✅ {uf}" if uf == uf_atual else uf
        current_row.append(InlineKeyboardButton(text, callback_data=f"pl:legacy_commands:radar:{uf.lower()}"))
        if len(current_row) == 4:
            uf_buttons.append(current_row)
            current_row = []
    if current_row:
        uf_buttons.append(current_row)
        
    final_keyboard = [[control_btn]] + uf_buttons + [[InlineKeyboardButton("❌ Fechar Menu", callback_data="pl:legacy_commands:radar:fechar")]]
    reply_markup = InlineKeyboardMarkup(final_keyboard)
    
    try:
        await query.edit_message_text(
            text=msg_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.warning(f"Erro ao atualizar mensagem do radar: {e}")

# ---------------------------------------------------------------------------
# Comandos AFK (Desktop Watch)
# ---------------------------------------------------------------------------

async def cmd_watch(args: str) -> str:
    """Ativa o modo AFK (Desktop Watch)."""
    if pipeline is None:
        await initialize_pipeline_and_loops()

    if not desktop_watch_goal:
        return "❌ O serviço Desktop Watch não foi inicializado."
    
    desktop_watch_goal.enable()
    
    all_states = load_legacy_state()
    all_states["desktop_watch"] = desktop_watch_goal.serialize_state()
    save_legacy_state(all_states)
    
    return (
        "👁️ **Desktop Watch ATIVADO**\n\n"
        "Monitoramento de tela ativo a cada 2 minutos.\n"
        "Alertas serão enviados se janelas ou diálogos exigirem atenção humana.\n\n"
        "Use `/watchoff` para desativar a qualquer momento."
    )

async def cmd_watchoff(args: str) -> str:
    """Desativa o modo AFK (Desktop Watch) e exibe estatísticas."""
    if pipeline is None:
        await initialize_pipeline_and_loops()

    if not desktop_watch_goal:
        return "❌ O serviço Desktop Watch não foi inicializado."
    
    scans = desktop_watch_goal._scans_total
    alerts = desktop_watch_goal._alerts_sent
    desktop_watch_goal.disable()
    
    all_states = load_legacy_state()
    all_states["desktop_watch"] = desktop_watch_goal.serialize_state()
    save_legacy_state(all_states)
    
    return (
        "👁️ **Desktop Watch DESATIVADO**\n\n"
        f"**Estatísticas da sessão:**\n"
        f"- Scans realizados: {scans}\n"
        f"- Alertas enviados: {alerts}\n\n"
        "Use `/watch` para reativar."
    )

# ---------------------------------------------------------------------------
# Função de Registro do Plugin
# ---------------------------------------------------------------------------

def register(ctx):
    """
    Função chamada pelo PluginManager do Seeker Agent no boot do sistema.
    """
    logger.info("Carregando Plugin de Comandos Legados com Teclado Virtual Inline (Fase 1.2)...")

    # Registro no Gateway
    ctx.register_command(
        name="configure-news",
        handler=cmd_configure_news,
        description="Personaliza os nichos do SenseNews (Legado)",
        args_hint="[nicho]"
    )

    ctx.register_command(
        name="radar",
        handler=cmd_radar,
        description="Configura e controla o Radar de Eventos (Legado)",
        args_hint="[pause|resume|UF]"
    )

    ctx.register_command(
        name="watch",
        handler=cmd_watch,
        description="Ativa vigilância de tela / modo AFK (Legado)",
    )

    ctx.register_command(
        name="watchoff",
        handler=cmd_watchoff,
        description="Desativa vigilância de tela (Legado)",
    )

    # Registra Hook de sessão para pré-inicialização do pipeline
    ctx.register_hook("on_session_start", on_session_start_hook)

    # Registra Hook de callback do Telegram Gateway
    ctx.register_hook("on_telegram_callback", on_telegram_callback_hook)

    # Tenta inicializar cedo se houver event loop ativo
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(initialize_pipeline_and_loops())
    except RuntimeError:
        pass
