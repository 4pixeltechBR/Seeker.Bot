#!/usr/bin/env python3
"""
Seeker.Bot -> Seeker Agent Memory Sync Utility
scripts/sync_history_to_agent.py

Imports Telegram chat history (session_turns) and consolidated facts (semantic)
from Seeker.Bot SQLite to Seeker Agent state database and MEMORY.md files.
"""

import os
import sys
import sqlite3
import time
import uuid

# Garante saída UTF-8 no stdout
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Garante path correto
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

SEEKER_BOT_DB = os.path.join(ROOT_DIR, "data", "seeker_memory.db")
AGENT_HOME = os.path.expanduser("~/.seeker_agent")

# Tenta carregar SEEKER_HOME do .env do agente
ENV_PATH = os.path.join(ROOT_DIR, "SeekerAgent", ".env")
if os.path.exists(ENV_PATH):
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("SEEKER_HOME="):
                AGENT_HOME = line.split("=")[1].strip().strip('"').strip("'")
                break

AGENT_DB = os.path.join(AGENT_HOME, "state.db")
AGENT_MEMORY_MD = os.path.join(AGENT_HOME, "MEMORY.md")
AGENT_USER_MD = os.path.join(AGENT_HOME, "USER.md")

print(f"Bancos de dados detectados:")
print(f" - Seeker.Bot DB  : {SEEKER_BOT_DB}")
print(f" - Seeker Agent DB: {AGENT_DB}")
print(f" - Seeker Agent Home: {AGENT_HOME}")


def sync_conversations():
    """Migra session_turns do Seeker.Bot para a tabela messages do Seeker Agent."""
    if not os.path.exists(SEEKER_BOT_DB):
        print("❌ Banco do Seeker.Bot não encontrado. Sem histórico para sincronizar.")
        return

    os.makedirs(os.path.dirname(AGENT_DB), exist_ok=True)
    
    # Conecta no Seeker.Bot
    conn_bot = sqlite3.connect(SEEKER_BOT_DB)
    cursor_bot = conn_bot.cursor()
    
    # Conecta no Seeker Agent
    conn_agent = sqlite3.connect(AGENT_DB)
    cursor_agent = conn_agent.cursor()
    
    try:
        # Puxa os turnos do bot
        cursor_bot.execute("SELECT session_id, role, content, timestamp FROM session_turns ORDER BY timestamp ASC")
        turns = cursor_bot.fetchall()
        if not turns:
            print("🗂️ Nenhum turno de conversação encontrado no Seeker.Bot.")
            return
            
        print(f"Sincronizando {len(turns)} turnos de conversas...")
        
        # Agrupa turns por session_id
        sessions = {}
        for session_id, role, content, timestamp in turns:
            if session_id not in sessions:
                sessions[session_id] = []
            sessions[session_id].append((role, content, timestamp))
            
        for sess_id, sess_turns in sessions.items():
            agent_session_id = f"imported_{sess_id}"
            
            # Insere a sessão se não existir
            cursor_agent.execute(
                "INSERT OR IGNORE INTO sessions (id, source, started_at, message_count) VALUES (?, ?, ?, ?)",
                (agent_session_id, "telegram_imported", sess_turns[0][2], len(sess_turns))
            )
            
            # Insere as mensagens
            for role, content, timestamp in sess_turns:
                # Normaliza role ('assistant' -> 'assistant'; 'user' -> 'user', mas o SeekerAgent aceita 'user' e 'assistant' de forma padrão)
                role_normalized = "assistant" if role == "assistant" else "user"
                
                cursor_agent.execute(
                    """INSERT INTO messages (session_id, role, content, timestamp)
                       VALUES (?, ?, ?, ?)""",
                    (agent_session_id, role_normalized, content, timestamp)
                )
                
        conn_agent.commit()
        print(f"✅ Histórico de conversações sincronizado com sucesso!")
        
    except Exception as e:
        print(f"❌ Erro durante a migração das conversações: {e}")
    finally:
        conn_bot.close()
        conn_agent.close()


def sync_semantic_memories():
    """Migra fatos consolidados (semantic) do Seeker.Bot para os arquivos MEMORY.md e USER.md do Seeker Agent."""
    if not os.path.exists(SEEKER_BOT_DB):
        return
        
    conn_bot = sqlite3.connect(SEEKER_BOT_DB)
    cursor_bot = conn_bot.cursor()
    
    try:
        # Puxa fatos semânticos do bot
        cursor_bot.execute("SELECT fact, category, confidence, last_seen FROM semantic WHERE confidence >= 0.4")
        facts = cursor_bot.fetchall()
        if not facts:
            print("🗂️ Nenhum fato semântico relevante encontrado no Seeker.Bot.")
            return
            
        print(f"Sincronizando {len(facts)} fatos de memórias...")
        
        # Divide entre MEMORY.md (fatos gerais/tech) e USER.md (fatos do Victor/preferências)
        memory_entries = []
        user_entries = []
        
        for fact, category, confidence, last_seen in facts:
            # Formata metadados em comentário HTML no padrão do Seeker Agent DecayEngine
            entry = f"<!-- domain:{category}, confidence:{confidence:.2f}, last_seen:{last_seen} -->\n{fact}"
            
            # Se a categoria for sobre o usuário ou preferências pessoais
            if category in ("user", "preferences", "personal"):
                user_entries.append(entry)
            else:
                memory_entries.append(entry)
                
        # Grava MEMORY.md (adicionando separador §)
        if memory_entries:
            content_mem = "\n\n§\n\n".join(memory_entries)
            # Se o arquivo já existir, lê e faz o merge para não sobrescrever fatos nativos do SeekerAgent
            existing_content = ""
            if os.path.exists(AGENT_MEMORY_MD):
                with open(AGENT_MEMORY_MD, "r", encoding="utf-8") as f:
                    existing_content = f.read().strip()
            
            with open(AGENT_MEMORY_MD, "w", encoding="utf-8") as f:
                if existing_content:
                    f.write(existing_content + "\n\n§\n\n" + content_mem)
                else:
                    f.write(content_mem)
            print(f"✅ {len(memory_entries)} fatos gravados em {AGENT_MEMORY_MD}")
            
        # Grava USER.md (preferências do Victor)
        if user_entries:
            content_user = "\n\n§\n\n".join(user_entries)
            existing_content = ""
            if os.path.exists(AGENT_USER_MD):
                with open(AGENT_USER_MD, "r", encoding="utf-8") as f:
                    existing_content = f.read().strip()
            
            with open(AGENT_USER_MD, "w", encoding="utf-8") as f:
                if existing_content:
                    f.write(existing_content + "\n\n§\n\n" + content_user)
                else:
                    f.write(content_user)
            print(f"✅ {len(user_entries)} fatos de usuário gravados em {AGENT_USER_MD}")
            
    except Exception as e:
        print(f"❌ Erro durante a migração das memórias semânticas: {e}")
    finally:
        conn_bot.close()
        
        
def main():
    sync_conversations()
    sync_semantic_memories()
    print("\n--- Sincronização completa de memórias concluída! ---")


if __name__ == "__main__":
    main()
