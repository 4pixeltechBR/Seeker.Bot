import sqlite3
import os
import shutil
import logging

# Configuração de Logs
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("schema_migrator")

def migrate():
    db_path = r"E:\Seeker.Bot\data\seeker_memory.db"
    backup_path = db_path + ".v3_migrate_bak"
    
    logger.info(f"Iniciando migração de schema para {db_path}")
    
    # 1. Backup de segurança
    try:
        shutil.copy2(db_path, backup_path)
        logger.info(f"Backup de segurança criado em {backup_path}")
    except Exception as e:
        logger.error(f"Erro ao criar backup: {e}")
        return False
        
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Desabilita foreign keys para evitar problemas de constraint durante a migração
        cursor.execute("PRAGMA foreign_keys = OFF;")
        
        # Iniciar transação explícita
        cursor.execute("BEGIN TRANSACTION;")
        
        # 2. Deletar a view antiga
        logger.info("Deletando view antiga 'view_porte_eventos_calculado'")
        cursor.execute("DROP VIEW IF EXISTS view_porte_eventos_calculado;")
        
        # 3. Renomear tabelas se elas existirem
        logger.info("Renomeando tabelas existentes para backup temporário...")
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='artistas';")
        if cursor.fetchone():
            cursor.execute("ALTER TABLE artistas RENAME TO _artistas_old;")
            
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='contratos_artisticos';")
        if cursor.fetchone():
            cursor.execute("ALTER TABLE contratos_artisticos RENAME TO _contratos_artisticos_old;")
            
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='grades_eventos';")
        if cursor.fetchone():
            cursor.execute("ALTER TABLE grades_eventos RENAME TO _grades_eventos_old;")
            
        # 4. Criar novas tabelas com FKs, constraints e tipos corretos
        logger.info("Criando novas tabelas de artistas, contratos e grades...")
        
        cursor.execute("""
            CREATE TABLE artistas (
                artista_id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT UNIQUE NOT NULL,
                genero TEXT,
                cache_estimado_mercado REAL,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        cursor.execute("""
            CREATE TABLE contratos_artisticos (
                processo_inexigibilidade TEXT PRIMARY KEY,
                cidade TEXT NOT NULL,
                artista_id INTEGER NOT NULL,
                valor_contrato REAL,
                data_assinatura DATE,
                representante_cnpj TEXT,
                fonte_url TEXT,
                verificacao_status TEXT DEFAULT 'pendente',
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (artista_id) REFERENCES artistas (artista_id) ON DELETE CASCADE
            );
        """)
        
        cursor.execute("""
            CREATE TABLE grades_eventos (
                grade_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                processo_inexigibilidade TEXT NOT NULL,
                ano INTEGER NOT NULL,
                data_show DATE,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (processo_inexigibilidade) REFERENCES contratos_artisticos (processo_inexigibilidade) ON DELETE CASCADE,
                FOREIGN KEY (event_id) REFERENCES event_map (event_id) ON DELETE CASCADE
            );
        """)
        
        # Nova tabela de fontes de contrato (validação dupla)
        logger.info("Criando tabela 'contrato_fonte' para validação de multiplas fontes...")
        cursor.execute("""
            CREATE TABLE contrato_fonte (
                fonte_id INTEGER PRIMARY KEY AUTOINCREMENT,
                processo_inexigibilidade TEXT NOT NULL,
                fonte_url TEXT NOT NULL,
                tipo_fonte TEXT NOT NULL,
                status_validacao TEXT DEFAULT 'pendente',
                data_verificacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (processo_inexigibilidade) REFERENCES contratos_artisticos (processo_inexigibilidade) ON DELETE CASCADE,
                UNIQUE(processo_inexigibilidade, fonte_url)
            );
        """)
        
        # 5. Migrar os dados
        logger.info("Migrando dados para o novo schema...")
        
        # Copiar artistas
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='_artistas_old';")
        if cursor.fetchone():
            cursor.execute("""
                INSERT OR IGNORE INTO artistas (artista_id, nome, genero, cache_estimado_mercado, criado_em)
                SELECT artista_id, nome, genero, cache_estimado_mercado, criado_em FROM _artistas_old;
            """)
            
        # Copiar contratos
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='_contratos_artisticos_old';")
        if cursor.fetchone():
            cursor.execute("""
                INSERT OR IGNORE INTO contratos_artisticos (
                    processo_inexigibilidade, cidade, artista_id, valor_contrato, data_assinatura, representante_cnpj, fonte_url, criado_em
                )
                SELECT processo_inexigibilidade, cidade, artista_id, valor_contrato, data_assinatura, representante_cnpj, fonte_url, criado_em
                FROM _contratos_artisticos_old;
            """)
            
        # Copiar grades
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='_grades_eventos_old';")
        if cursor.fetchone():
            cursor.execute("""
                INSERT OR IGNORE INTO grades_eventos (grade_id, event_id, processo_inexigibilidade, ano, data_show, criado_em)
                SELECT grade_id, event_id, processo_inexigibilidade, ano, data_show, criado_em FROM _grades_eventos_old;
            """)
            
        # 6. Criar novos índices compostos
        logger.info("Criando índices compostos...")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_contratos_cidade_data ON contratos_artisticos(cidade, data_assinatura);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_contratos_cidade_fonte ON contratos_artisticos(cidade, fonte_url);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_grades_event_ano ON grades_eventos(event_id, ano);")
        
        # 7. Recriar a View
        logger.info("Recriando a view 'view_porte_eventos_calculado'...")
        cursor.execute("""
            CREATE VIEW view_porte_eventos_calculado AS
            SELECT 
                em.event_id,
                em.cidade,
                em.nome_evento,
                ge.ano,
                SUM(ca.valor_contrato) as custo_total_artistico,
                CASE 
                    WHEN SUM(ca.valor_contrato) <= 500000.00 THEN 'pequeno'
                    WHEN SUM(ca.valor_contrato) > 500000.00 AND SUM(ca.valor_contrato) <= 1200000.00 THEN 'médio'
                    WHEN SUM(ca.valor_contrato) > 1200000.00 THEN 'grande'
                    ELSE 'não calculado'
                END as porte_real_calculado
            FROM event_map em
            JOIN grades_eventos ge ON em.event_id = ge.event_id
            JOIN contratos_artisticos ca ON ge.processo_inexigibilidade = ca.processo_inexigibilidade
            GROUP BY em.event_id, ge.ano;
        """)
        
        # 8. Deletar tabelas de backup antigas
        logger.info("Removendo tabelas temporárias antigas...")
        cursor.execute("DROP TABLE IF EXISTS _artistas_old;")
        cursor.execute("DROP TABLE IF EXISTS _contratos_artisticos_old;")
        cursor.execute("DROP TABLE IF EXISTS _grades_eventos_old;")
        
        # Confirmar transação
        conn.commit()
        logger.info("Transação confirmada (commit) com sucesso.")
        
        # Habilitar foreign keys e testar
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute("PRAGMA foreign_key_check;")
        fk_errors = cursor.fetchall()
        if fk_errors:
            logger.warning(f"Aviso: Foram encontrados erros de chaves estrangeiras: {fk_errors}")
        else:
            logger.info("Verificação de integridade referencial (foreign_keys) passou com sucesso.")
            
        return True
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Erro durante a migração. Efetuando rollback: {e}")
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    success = migrate()
    if success:
        logger.info("Migração concluída com sucesso absoluta!")
    else:
        logger.error("Migração falhou.")
