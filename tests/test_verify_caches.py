import sys
import os
import sqlite3
import pytest
from pathlib import Path

# Resolver caminhos para importação
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scratch.verify_and_update_caches import validate_contract

# Testar validação de contratos
class TestValidateContract:
    def test_valid_contract(self):
        c = {
            "processo_inexigibilidade": "INEX-TESTE-01-2025",
            "cidade": "Cidade Teste",
            "artista_nome": "Artista Teste",
            "valor_contrato": 150000.0,
            "data_assinatura": "2025-06-18",
            "representante_cnpj": "12.345.678/0001-99"
        }
        errors = validate_contract(c)
        assert len(errors) == 0

    def test_invalid_value(self):
        c = {
            "processo_inexigibilidade": "INEX-TESTE-01-2025",
            "cidade": "Cidade Teste",
            "artista_nome": "Artista Teste",
            "valor_contrato": -50.0,
            "data_assinatura": "2025-06-18",
            "representante_cnpj": "12.345.678/0001-99"
        }
        errors = validate_contract(c)
        assert any("Valor do contrato inválido" in err for err in errors)

    def test_invalid_date_format(self):
        c = {
            "processo_inexigibilidade": "INEX-TESTE-01-2025",
            "cidade": "Cidade Teste",
            "artista_nome": "Artista Teste",
            "valor_contrato": 150000.0,
            "data_assinatura": "18/06/2025",  # formato incorreto
            "representante_cnpj": "12.345.678/0001-99"
        }
        errors = validate_contract(c)
        assert any("Formato de data inválido" in err for err in errors)

    def test_invalid_cnpj(self):
        c = {
            "processo_inexigibilidade": "INEX-TESTE-01-2025",
            "cidade": "Cidade Teste",
            "artista_nome": "Artista Teste",
            "valor_contrato": 150000.0,
            "data_assinatura": "2025-06-18",
            "representante_cnpj": "12345"  # CNPJ curto
        }
        errors = validate_contract(c)
        assert any("CNPJ com formato incorreto" in err for err in errors)

# Testar integridade do banco de dados (chaves estrangeiras e constraints)
class TestDatabaseSchema:
    @pytest.fixture
    def mock_db(self):
        """Prepara um banco SQLite em memória com o schema v3 para testes."""
        conn = sqlite3.connect(":memory:")
        cursor = conn.cursor()
        
        # Ativar foreign keys
        cursor.execute("PRAGMA foreign_keys = ON;")
        
        # Criar tabelas
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
            CREATE TABLE event_map (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                cidade TEXT,
                estado TEXT,
                nome_evento TEXT,
                nome_normalizado TEXT,
                categoria TEXT,
                historico_anos TEXT,
                historico_mes INTEGER,
                status_previsao TEXT,
                mapeado_em TIMESTAMP,
                atualizado_em TIMESTAMP
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
        conn.commit()
        yield conn
        conn.close()

    def test_foreign_key_constraint(self, mock_db):
        """Valida que o SQLite com foreign_keys=ON rejeita contratos apontando para artistas inexistentes."""
        cursor = mock_db.cursor()
        
        # Tenta inserir contrato sem artista correspondente
        with pytest.raises(sqlite3.IntegrityError) as exc_info:
            cursor.execute("""
                INSERT INTO contratos_artisticos (processo_inexigibilidade, cidade, artista_id, valor_contrato)
                VALUES ('INEX-001', 'Cidade Teste', 999, 10000.0)
            """)
        assert "FOREIGN KEY constraint failed" in str(exc_info.value)

    def test_cascade_delete(self, mock_db):
        """Valida que a exclusão de um artista remove em cascata seus contratos e grades correspondentes."""
        cursor = mock_db.cursor()
        
        # 1. Inserir artista
        cursor.execute("INSERT INTO artistas (nome, genero, cache_estimado_mercado) VALUES ('Artista Teste', 'SERTA', 50000)")
        cursor.execute("SELECT artista_id FROM artistas WHERE nome = 'Artista Teste'")
        artista_id = cursor.fetchone()[0]
        
        # 2. Inserir contrato
        cursor.execute("""
            INSERT INTO contratos_artisticos (processo_inexigibilidade, cidade, artista_id, valor_contrato)
            VALUES ('INEX-002', 'Cidade A', ?, 50000)
        """, (artista_id,))
        
        # 3. Inserir event_map
        cursor.execute("""
            INSERT INTO event_map (cidade, nome_evento, nome_normalizado)
            VALUES ('Cidade A', 'Festa A', 'festa a')
        """)
        cursor.execute("SELECT event_id FROM event_map WHERE cidade = 'Cidade A'")
        event_id = cursor.fetchone()[0]
        
        # 4. Inserir grade
        cursor.execute("""
            INSERT INTO grades_eventos (event_id, processo_inexigibilidade, ano)
            VALUES (?, 'INEX-002', 2025)
        """, (event_id,))
        
        mock_db.commit()
        
        # Verificar que os registros existem
        cursor.execute("SELECT COUNT(*) FROM contratos_artisticos")
        assert cursor.fetchone()[0] == 1
        cursor.execute("SELECT COUNT(*) FROM grades_eventos")
        assert cursor.fetchone()[0] == 1
        
        # Excluir o artista
        cursor.execute("DELETE FROM artistas WHERE artista_id = ?", (artista_id,))
        mock_db.commit()
        
        # Verificar remoção em cascata
        cursor.execute("SELECT COUNT(*) FROM contratos_artisticos")
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT COUNT(*) FROM grades_eventos")
        assert cursor.fetchone()[0] == 0
