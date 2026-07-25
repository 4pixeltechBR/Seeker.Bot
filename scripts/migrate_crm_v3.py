"""
Migra schema CRM para v3 (Phase 5 — Muni Outreach).

Adiciona:
- Colunas em prefeituras_contatos (prefeito, secretarias emails, CNPJ, fit_score)
- Tabela crm_outreach_log (tracking cada envio)
- Tabela crm_outreach_suppression (LGPD opt-out, 5 anos)
- Tabela crm_outreach_warmup (calendario ramp-up 30->100/dia)

Schema migration idempotente (CREATE TABLE IF NOT EXISTS + ALTER TABLE seguro).

Uso:
    python scripts/migrate_crm_v3.py
    python scripts/migrate_crm_v3.py --dry-run
"""

import argparse
import asyncio
import io
import sys
from pathlib import Path

# Forca UTF-8 no stdout (Windows PowerShell)
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import aiosqlite

from src.core.memory.store import DEFAULT_DB_PATH


async def main(dry_run: bool):
    print(f"[migrate-v3] DB alvo: {DEFAULT_DB_PATH}")
    if dry_run:
        print("[migrate-v3] DRY-RUN: nenhuma alteração será gravada")

    async with aiosqlite.connect(DEFAULT_DB_PATH) as db:

        # 1. CREATE TABLE IF NOT EXISTS para tabelas novas
        if not dry_run:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS crm_outreach_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prefeitura_cidade TEXT NOT NULL,
                    prefeitura_estado TEXT NOT NULL,
                    contact_email TEXT NOT NULL,
                    contact_type TEXT NOT NULL,
                    contact_role TEXT,
                    subject TEXT,
                    body_preview TEXT,
                    sent_at INTEGER,
                    ses_message_id TEXT,
                    delivery_status TEXT DEFAULT 'pending',
                    open_count INTEGER DEFAULT 0,
                    click_count INTEGER DEFAULT 0,
                    first_open_at INTEGER,
                    last_open_at INTEGER,
                    replied_at INTEGER,
                    replied_classification TEXT,
                    lgpd_consent_at INTEGER
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_outreach_log_sent_at "
                "ON crm_outreach_log(sent_at DESC)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_outreach_log_email "
                "ON crm_outreach_log(contact_email)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_outreach_log_status "
                "ON crm_outreach_log(delivery_status)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_outreach_log_cidade "
                "ON crm_outreach_log(prefeitura_cidade, prefeitura_estado)"
            )

            await db.execute("""
                CREATE TABLE IF NOT EXISTS crm_outreach_suppression (
                    email TEXT PRIMARY KEY,
                    reason TEXT NOT NULL,
                    source TEXT,
                    suppressed_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_suppression_expires "
                "ON crm_outreach_suppression(expires_at)"
            )

            await db.execute("""
                CREATE TABLE IF NOT EXISTS crm_outreach_warmup (
                    date TEXT PRIMARY KEY,
                    quota INTEGER NOT NULL,
                    sent_count INTEGER DEFAULT 0,
                    bounce_count INTEGER DEFAULT 0,
                    complaint_count INTEGER DEFAULT 0,
                    paused INTEGER DEFAULT 0,
                    pause_reason TEXT
                )
            """)

            print("[migrate-v3] Criadas 3 tabelas novas: crm_outreach_log, crm_outreach_suppression, crm_outreach_warmup")

        # 2. Verificar prefeituras_contatos: precisa coluna estado? (PK composta cidade+estado)
        cur = await db.execute("PRAGMA table_info(prefeituras_contatos)")
        existing_cols = {row[1] for row in await cur.fetchall()}

        # A tabela atual tem só "cidade" como PK. Para FK composta precisamos de estado.
        # Verificar se já tem coluna estado
        if "estado" not in existing_cols:
            if not dry_run:
                await db.execute(
                    "ALTER TABLE prefeituras_contatos ADD COLUMN estado TEXT"
                )
                print("[migrate-v3] Adicionada coluna estado em prefeituras_contatos")
            else:
                print("[migrate-v3] [dry-run] Adicionaria coluna estado em prefeituras_contatos")
            existing_cols.add("estado")

        # 3. Adicionar colunas novas em prefeituras_contatos
        migrations = [
            # Identidade
            ("cnpj",                              "TEXT"),
            ("uf",                                "TEXT"),
            ("ibge_code",                         "INTEGER"),
            # Prefeito (Tier 2)
            ("prefeito_nome",                     "TEXT"),
            ("prefeito_partido",                  "TEXT"),
            ("prefeito_eleito_ano",               "INTEGER"),
            ("prefeito_email",                    "TEXT"),
            ("prefeito_wpp",                      "TEXT"),
            ("prefeito_fonte",                    "TEXT"),
            # Secretarias (Tier 1)
            ("sec_cultura_nome",                  "TEXT"),
            ("sec_cultura_email",                 "TEXT"),
            ("sec_cultura_fonte",                 "TEXT"),
            ("sec_turismo_email",                 "TEXT"),
            ("sec_turismo_nome",                  "TEXT"),
            ("sec_educacao_email",                "TEXT"),
            ("sec_esporte_email",                 "TEXT"),
            ("sec_saude_email",                   "TEXT"),
            ("foundation_cultural_email",         "TEXT"),
            # Institucional genérico
            ("prefeitura_email",                  "TEXT"),
            ("gabinete_email",                    "TEXT"),
            ("licitacao_email",                   "TEXT"),
            ("compras_email",                     "TEXT"),
            # Indicadores municipais
            ("populacao",                         "INTEGER"),
            ("pib_per_capita",                    "REAL"),
            ("idh",                               "REAL"),
            # URLs
            ("portal_transparencia_url",          "TEXT"),
            ("dom_url",                           "TEXT"),
            # Metadata
            ("total_secretarias",                 "INTEGER"),
            ("site_ativo",                        "INTEGER"),
            ("minerado_em",                       "INTEGER"),
            ("score_fit",                         "REAL"),
            ("last_enriched_at",                  "INTEGER"),
        ]

        added_cols = []
        for col, decl in migrations:
            if col not in existing_cols:
                if not dry_run:
                    try:
                        await db.execute(
                            f"ALTER TABLE prefeituras_contatos ADD COLUMN {col} {decl}"
                        )
                        added_cols.append(col)
                    except Exception as e:
                        print(f"[migrate-v3] ERRO ao adicionar coluna {col}: {e}")
                else:
                    added_cols.append(f"{col} (dry-run)")

        if added_cols:
            print(f"[migrate-v3] Adicionadas {len(added_cols)} colunas em prefeituras_contatos:")
            for c in added_cols:
                print(f"  + {c}")
        else:
            print("[migrate-v3] prefeituras_contatos já tinha todas as colunas")

        # 4. Criar índices em prefeituras_contatos para lookups comuns
        if not dry_run:
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_pref_cidade_estado "
                "ON prefeituras_contatos(cidade, estado)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_pref_status "
                "ON prefeituras_contatos(status_mineracao)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_pref_fit "
                "ON prefeituras_contatos(score_fit DESC)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_pref_pop "
                "ON prefeituras_contatos(populacao DESC)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_pref_uf "
                "ON prefeituras_contatos(uf)"
            )

        if not dry_run:
            await db.commit()
            print("\n[migrate-v3] ✓ Migration aplicada com sucesso")
        else:
            print("\n[migrate-v3] ✓ Dry-run OK (nenhuma alteração gravada)")

        # 5. Resumo final do estado
        cur = await db.execute("PRAGMA table_info(prefeituras_contatos)")
        final_cols = [row[1] for row in await cur.fetchall()]
        print(f"\n[migrate-v3] prefeituras_contatos agora tem {len(final_cols)} colunas:")
        print(f"  Antes: 7 colunas")
        print(f"  Depois: {len(final_cols)} colunas (+{len(final_cols) - 7})")

        # 6. Tabelas outreach
        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name LIKE 'crm_outreach_%'"
        )
        outreach_tables = [row[0] for row in await cur.fetchall()]
        print(f"\n[migrate-v3] Tabelas de outreach:")
        for t in outreach_tables:
            cur = await db.execute(f"PRAGMA table_info({t})")
            cols = [row[1] for row in await cur.fetchall()]
            print(f"  ✓ {t} ({len(cols)} colunas)")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="Não escreve, só reporta")
    args = p.parse_args()
    asyncio.run(main(args.dry_run))
